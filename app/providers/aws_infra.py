"""Live AWS connector.

Uses the AWS connection stored in Settings (access key id / secret access key /
region) to call AWS APIs through boto3 and build a compact, security-focused
report of the account: caller identity, EC2 exposure, security groups open to
the internet, S3 public-access and encryption posture, RDS exposure and IAM
hygiene. Skills reason over this REAL data, so "review my AWS" analyses the
actual account instead of asking the user to paste files.

Everything here is READ-ONLY: it only issues describe/list/get calls; it never
creates, updates or deletes anything.
"""
import json
from dataclasses import dataclass
from typing import Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app import connections

_DEFAULT_REGION = "us-east-1"
_SENSITIVE_PORTS = {22, 3389, 3306, 5432, 1433, 6379, 27017, 9200, 5984}
_MAX_BUCKETS = 25


class AwsConnectionError(RuntimeError):
    """Raised when AWS is not connected or credentials are incomplete."""


class AwsApiError(RuntimeError):
    """Raised when an AWS API call fails (auth, permissions, throttling…)."""


@dataclass
class AwsCredentials:
    access_key_id: str
    secret_access_key: str
    region: str = _DEFAULT_REGION


def load_credentials(project_id: str) -> AwsCredentials:
    fields = connections.get_secret_fields(project_id, "aws")
    if not fields:
        raise AwsConnectionError("No AWS connection is configured for this project.")
    access_key = fields.get("access_key_id") or ""
    secret_key = fields.get("secret_access_key") or ""
    missing = [
        name
        for name, value in (
            ("Access key ID", access_key),
            ("Secret access key", secret_key),
        )
        if not value
    ]
    if missing:
        raise AwsConnectionError(
            "AWS connection is missing: " + ", ".join(missing) + "."
        )
    return AwsCredentials(
        access_key_id=access_key,
        secret_access_key=secret_key,
        region=fields.get("region") or _DEFAULT_REGION,
    )


def is_connected(project_id: str) -> bool:
    try:
        load_credentials(project_id)
        return True
    except AwsConnectionError:
        return False


def _session(creds: AwsCredentials) -> boto3.session.Session:
    return boto3.session.Session(
        aws_access_key_id=creds.access_key_id,
        aws_secret_access_key=creds.secret_access_key,
        region_name=creds.region,
    )


def _client(session: boto3.session.Session, service: str):
    return session.client(service, config=Config(retries={"max_attempts": 2}))


def _api_message(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        err = exc.response.get("Error", {})
        return f"{err.get('Code', 'Error')}: {err.get('Message', str(exc))}"[:300]
    return str(exc)[:300]


def _format_rows(rows: list[dict[str, Any]], limit: int = 60) -> str:
    if not rows:
        return "(none found)"
    shown = rows[:limit]
    lines = [json.dumps(row, default=str, separators=(",", ": ")) for row in shown]
    if len(rows) > limit:
        lines.append(f"... and {len(rows) - limit} more")
    return "\n".join(lines)


def _caller_identity(session: boto3.session.Session) -> dict[str, Any]:
    try:
        sts = _client(session, "sts")
        return sts.get_caller_identity()
    except (BotoCoreError, ClientError) as exc:
        raise AwsApiError(
            f"AWS authentication failed: {_api_message(exc)}. Check the access key, "
            "secret and that the key is active."
        ) from exc


def _ec2_summary(session: boto3.session.Session) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ec2 = _client(session, "ec2")
    instances: list[dict[str, Any]] = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                instances.append(
                    {
                        "instanceId": inst.get("InstanceId"),
                        "type": inst.get("InstanceType"),
                        "state": inst.get("State", {}).get("Name"),
                        "publicIp": inst.get("PublicIpAddress"),
                        "az": inst.get("Placement", {}).get("AvailabilityZone"),
                    }
                )

    open_rules: list[dict[str, Any]] = []
    sg_paginator = ec2.get_paginator("describe_security_groups")
    for page in sg_paginator.paginate():
        for group in page.get("SecurityGroups", []):
            for perm in group.get("IpPermissions", []):
                open_ipv4 = any(
                    rng.get("CidrIp") == "0.0.0.0/0" for rng in perm.get("IpRanges", [])
                )
                open_ipv6 = any(
                    rng.get("CidrIpv6") == "::/0" for rng in perm.get("Ipv6Ranges", [])
                )
                if not (open_ipv4 or open_ipv6):
                    continue
                from_port = perm.get("FromPort")
                to_port = perm.get("ToPort")
                is_all = from_port is None
                sensitive = is_all or any(
                    from_port <= port <= to_port for port in _SENSITIVE_PORTS
                )
                if not sensitive:
                    continue
                open_rules.append(
                    {
                        "securityGroup": group.get("GroupId"),
                        "name": group.get("GroupName"),
                        "protocol": perm.get("IpProtocol"),
                        "portRange": "all" if is_all else f"{from_port}-{to_port}",
                        "source": "0.0.0.0/0" if open_ipv4 else "::/0",
                    }
                )
    return instances, open_rules


def _s3_summary(session: boto3.session.Session) -> list[dict[str, Any]]:
    s3 = _client(session, "s3")
    buckets = s3.list_buckets().get("Buckets", [])
    rows: list[dict[str, Any]] = []
    for bucket in buckets[:_MAX_BUCKETS]:
        name = bucket.get("Name")
        row: dict[str, Any] = {"bucket": name}
        try:
            pab = s3.get_public_access_block(Bucket=name)
            cfg = pab.get("PublicAccessBlockConfiguration", {})
            row["publicAccessBlocked"] = all(
                cfg.get(flag)
                for flag in (
                    "BlockPublicAcls",
                    "IgnorePublicAcls",
                    "BlockPublicPolicy",
                    "RestrictPublicBuckets",
                )
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            row["publicAccessBlocked"] = (
                False if code == "NoSuchPublicAccessBlockConfiguration" else "unknown"
            )
        try:
            s3.get_bucket_encryption(Bucket=name)
            row["encryptionAtRest"] = True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            row["encryptionAtRest"] = (
                False if code == "ServerSideEncryptionConfigurationNotFoundError" else "unknown"
            )
        rows.append(row)
    return rows


def _rds_summary(session: boto3.session.Session) -> list[dict[str, Any]]:
    rds = _client(session, "rds")
    rows: list[dict[str, Any]] = []
    paginator = rds.get_paginator("describe_db_instances")
    for page in paginator.paginate():
        for db in page.get("DBInstances", []):
            rows.append(
                {
                    "identifier": db.get("DBInstanceIdentifier"),
                    "engine": db.get("Engine"),
                    "publiclyAccessible": db.get("PubliclyAccessible"),
                    "encrypted": db.get("StorageEncrypted"),
                    "multiAz": db.get("MultiAZ"),
                }
            )
    return rows


def _iam_summary(session: boto3.session.Session) -> dict[str, Any]:
    iam = _client(session, "iam")
    summary = iam.get_account_summary().get("SummaryMap", {})
    return {
        "users": summary.get("Users"),
        "usersWithMfa": summary.get("AccountMFAEnabled"),
        "accessKeysPerUserQuota": summary.get("AccessKeysPerUserQuota"),
        "mfaDevices": summary.get("MFADevices"),
        "policies": summary.get("Policies"),
    }


def build_environment_report(project_id: str) -> dict[str, Any]:
    """Fetch a live, read-only AWS environment report.

    Returns a dict with a formatted ``text`` block for the LLM plus structured
    ``meta``. Raises AwsConnectionError / AwsApiError on failure so the caller
    can surface a precise message.
    """
    creds = load_credentials(project_id)
    session = _session(creds)
    identity = _caller_identity(session)

    sections: list[str] = []
    sections.append(
        f"AWS account: {identity.get('Account')} | region: {creds.region} | "
        f"caller ARN: {identity.get('Arn')}"
    )

    def _probe(label: str, fn) -> None:
        try:
            fn()
        except (BotoCoreError, ClientError) as exc:
            sections.append(f"{label}:\n(could not evaluate: {_api_message(exc)})")

    def _ec2() -> None:
        instances, open_rules = _ec2_summary(session)
        sections.append(
            f"EC2 instances ({len(instances)} in {creds.region}):\n"
            + _format_rows(instances)
        )
        sections.append(
            "Security-group rules open to the internet on sensitive ports:\n"
            + _format_rows(open_rules)
        )

    def _s3() -> None:
        rows = _s3_summary(session)
        sections.append(
            "S3 buckets (public-access block & encryption at rest):\n"
            + _format_rows(rows)
        )

    def _rds() -> None:
        rows = _rds_summary(session)
        sections.append(
            f"RDS instances (public accessibility & encryption) in {creds.region}:\n"
            + _format_rows(rows)
        )

    def _iam() -> None:
        summary = _iam_summary(session)
        sections.append(
            "IAM account summary:\n" + json.dumps(summary, default=str, indent=None)
        )

    _probe("EC2 & security groups", _ec2)
    _probe("S3 buckets", _s3)
    _probe("RDS instances", _rds)
    _probe("IAM", _iam)

    text = "\n\n".join(sections)
    return {
        "text": text,
        "meta": {
            "account": identity.get("Account"),
            "region": creds.region,
        },
    }
