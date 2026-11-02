"""Live AWS connector (read-only).

Uses the AWS connection stored in Settings (access key / secret / region, plus
optional session token and AssumeRole fields) to call AWS APIs through boto3
and build compact, security-focused reports: identity, EC2/SG, VPC, ELB,
Lambda, S3, RDS, IAM, Config/Security Hub summaries, Cost Explorer, and
CloudWatch metrics/logs.

Skills reason over this REAL data so "review my AWS" analyses the connected
account instead of asking the user to paste files.
"""
from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.platform import connections

_DEFAULT_REGION = "us-east-1"
_SENSITIVE_PORTS = {22, 3389, 3306, 5432, 1433, 6379, 27017, 9200, 5984}
_MAX_BUCKETS = 25
_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


class AwsConnectionError(RuntimeError):
    """Raised when AWS is not connected or credentials are incomplete."""


class AwsApiError(RuntimeError):
    """Raised when an AWS API call fails (auth, permissions, throttling…)."""


@dataclass
class AwsCredentials:
    access_key_id: str
    secret_access_key: str
    region: str = _DEFAULT_REGION
    session_token: str = ""
    role_arn: str = ""
    external_id: str = ""
    regions: list[str] = field(default_factory=list)


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
    extra_regions = [
        part.strip()
        for part in str(fields.get("regions") or "").split(",")
        if part.strip()
    ]
    return AwsCredentials(
        access_key_id=access_key,
        secret_access_key=secret_key,
        region=fields.get("region") or _DEFAULT_REGION,
        session_token=str(fields.get("session_token") or ""),
        role_arn=str(fields.get("role_arn") or ""),
        external_id=str(fields.get("external_id") or ""),
        regions=extra_regions,
    )


def is_connected(project_id: str) -> bool:
    try:
        load_credentials(project_id)
        return True
    except AwsConnectionError:
        return False


def _base_session(creds: AwsCredentials) -> boto3.session.Session:
    kwargs: dict[str, Any] = {
        "aws_access_key_id": creds.access_key_id,
        "aws_secret_access_key": creds.secret_access_key,
        "region_name": creds.region,
    }
    if creds.session_token:
        kwargs["aws_session_token"] = creds.session_token
    return boto3.session.Session(**kwargs)


def _session(creds: AwsCredentials) -> boto3.session.Session:
    """Build a boto3 session, optionally assuming ``role_arn``."""
    base = _base_session(creds)
    if not creds.role_arn:
        return base
    sts = base.client("sts", config=Config(retries={"max_attempts": 2}))
    assume_kwargs: dict[str, Any] = {
        "RoleArn": creds.role_arn,
        "RoleSessionName": "infralens-readonly",
    }
    if creds.external_id:
        assume_kwargs["ExternalId"] = creds.external_id
    try:
        assumed = sts.assume_role(**assume_kwargs)["Credentials"]
    except (BotoCoreError, ClientError) as exc:
        raise AwsApiError(
            f"AWS AssumeRole failed for {creds.role_arn}: {_api_message(exc)}"
        ) from exc
    return boto3.session.Session(
        aws_access_key_id=assumed["AccessKeyId"],
        aws_secret_access_key=assumed["SecretAccessKey"],
        aws_session_token=assumed["SessionToken"],
        region_name=creds.region,
    )


def _client(session: boto3.session.Session, service: str, region: Optional[str] = None):
    kwargs: dict[str, Any] = {"config": Config(retries={"max_attempts": 2})}
    if region:
        kwargs["region_name"] = region
    return session.client(service, **kwargs)


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


def _scan_regions(creds: AwsCredentials) -> list[str]:
    regions = [creds.region]
    for item in creds.regions:
        if item and item not in regions:
            regions.append(item)
    return regions


def _ec2_summary(
    session: boto3.session.Session, region: Optional[str] = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ec2 = _client(session, "ec2", region=region)
    instances: list[dict[str, Any]] = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                sg_ids = [
                    g.get("GroupId")
                    for g in inst.get("SecurityGroups", [])
                    if g.get("GroupId")
                ]
                instances.append(
                    {
                        "instanceId": inst.get("InstanceId"),
                        "type": inst.get("InstanceType"),
                        "state": inst.get("State", {}).get("Name"),
                        "publicIp": inst.get("PublicIpAddress"),
                        "az": inst.get("Placement", {}).get("AvailabilityZone"),
                        "vpcId": inst.get("VpcId"),
                        "subnetId": inst.get("SubnetId"),
                        "securityGroups": sg_ids,
                        "securityGroup": ",".join(sg_ids),
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
                        "vpcId": group.get("VpcId"),
                    }
                )
    return instances, open_rules


def _vpc_summary(session: boto3.session.Session, region: Optional[str] = None) -> dict[str, Any]:
    ec2 = _client(session, "ec2", region=region)
    vpcs = ec2.describe_vpcs().get("Vpcs", [])
    subnets = ec2.describe_subnets().get("Subnets", [])
    route_tables = ec2.describe_route_tables().get("RouteTables", [])
    public_routes: list[dict[str, Any]] = []
    for table in route_tables:
        for route in table.get("Routes", []):
            if route.get("GatewayId", "").startswith("igw-") and route.get("DestinationCidrBlock") == "0.0.0.0/0":
                public_routes.append(
                    {
                        "routeTable": table.get("RouteTableId"),
                        "vpcId": table.get("VpcId"),
                        "gateway": route.get("GatewayId"),
                    }
                )
    return {
        "vpcs": [
            {
                "vpcId": v.get("VpcId"),
                "cidr": (v.get("CidrBlockAssociationSet") or [{}])[0].get("CidrBlock")
                or v.get("CidrBlock"),
                "isDefault": v.get("IsDefault"),
            }
            for v in vpcs
        ],
        "subnets": [
            {
                "subnetId": s.get("SubnetId"),
                "vpcId": s.get("VpcId"),
                "az": s.get("AvailabilityZone"),
                "publicIpOnLaunch": s.get("MapPublicIpOnLaunch"),
                "cidr": s.get("CidrBlock"),
            }
            for s in subnets
        ],
        "publicRoutes": public_routes,
    }


def _elb_summary(session: boto3.session.Session, region: Optional[str] = None) -> list[dict[str, Any]]:
    elbv2 = _client(session, "elbv2", region=region)
    rows: list[dict[str, Any]] = []
    paginator = elbv2.get_paginator("describe_load_balancers")
    for page in paginator.paginate():
        for lb in page.get("LoadBalancers", []):
            rows.append(
                {
                    "name": lb.get("LoadBalancerName"),
                    "arn": lb.get("LoadBalancerArn"),
                    "type": lb.get("Type"),
                    "scheme": lb.get("Scheme"),
                    "internetFacing": lb.get("Scheme") == "internet-facing",
                    "vpcId": lb.get("VpcId"),
                    "dnsName": lb.get("DNSName"),
                }
            )
    return rows


def _lambda_summary(session: boto3.session.Session, region: Optional[str] = None) -> list[dict[str, Any]]:
    client = _client(session, "lambda", region=region)
    rows: list[dict[str, Any]] = []
    paginator = client.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page.get("Functions", [])[:80]:
            cfg = fn.get("VpcConfig") or {}
            rows.append(
                {
                    "name": fn.get("FunctionName"),
                    "runtime": fn.get("Runtime"),
                    "packageType": fn.get("PackageType"),
                    "inVpc": bool(cfg.get("VpcId")),
                    "vpcId": cfg.get("VpcId"),
                    "url": None,
                }
            )
    for row in rows[:40]:
        try:
            url_cfg = client.get_function_url_config(FunctionName=row["name"])
            row["url"] = url_cfg.get("FunctionUrl")
        except ClientError:
            continue
    return rows


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
                False
                if code == "ServerSideEncryptionConfigurationNotFoundError"
                else "unknown"
            )
        rows.append(row)
    return rows


def _rds_summary(
    session: boto3.session.Session, region: Optional[str] = None
) -> list[dict[str, Any]]:
    rds = _client(session, "rds", region=region)
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
                    "vpcId": (db.get("DBSubnetGroup") or {}).get("VpcId"),
                }
            )
    return rows


def _iam_summary(session: boto3.session.Session) -> dict[str, Any]:
    iam = _client(session, "iam")
    summary = iam.get_account_summary().get("SummaryMap", {})
    result: dict[str, Any] = {
        "users": summary.get("Users"),
        "usersWithMfa": summary.get("AccountMFAEnabled"),
        "accessKeysPerUserQuota": summary.get("AccessKeysPerUserQuota"),
        "mfaDevices": summary.get("MFADevices"),
        "policies": summary.get("Policies"),
    }
    try:
        policy = iam.get_account_password_policy().get("PasswordPolicy", {})
        result["passwordPolicy"] = {
            "minimumPasswordLength": policy.get("MinimumPasswordLength"),
            "requireSymbols": policy.get("RequireSymbols"),
            "requireNumbers": policy.get("RequireNumbers"),
            "requireUppercaseCharacters": policy.get("RequireUppercaseCharacters"),
            "requireLowercaseCharacters": policy.get("RequireLowercaseCharacters"),
            "expirePasswords": policy.get("ExpirePasswords"),
            "maxPasswordAge": policy.get("MaxPasswordAge"),
        }
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        result["passwordPolicy"] = (
            "not_set" if code == "NoSuchEntity" else f"unavailable:{code}"
        )
    try:
        aa = _client(session, "accessanalyzer")
        analyzers = aa.list_analyzers().get("analyzers", [])
        result["accessAnalyzers"] = [
            {"name": a.get("name"), "status": a.get("status"), "type": a.get("type")}
            for a in analyzers[:10]
        ]
        findings: list[dict[str, Any]] = []
        for analyzer in analyzers[:3]:
            name = analyzer.get("name")
            if not name:
                continue
            try:
                page = aa.list_findings(analyzerArn=analyzer.get("arn"), maxResults=10)
            except ClientError:
                continue
            for finding_id in (page.get("findings") or [])[:10]:
                findings.append({"analyzer": name, "id": finding_id})
        result["accessAnalyzerFindings"] = findings[:20]
    except Exception as exc:  # noqa: BLE001 — optional analyzer; mocks may lack the client
        result["accessAnalyzers"] = f"unavailable:{exc}"
    return result


def _security_services_summary(
    session: boto3.session.Session, region: Optional[str] = None
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        cfg = _client(session, "config", region=region)
        recorders = cfg.describe_configuration_recorders().get("ConfigurationRecorders", [])
        status = cfg.describe_configuration_recorder_status().get(
            "ConfigurationRecordersStatus", []
        )
        out["configRecorders"] = [
            {
                "name": r.get("name"),
                "recording": next(
                    (
                        s.get("recording")
                        for s in status
                        if s.get("name") == r.get("name")
                    ),
                    None,
                ),
            }
            for r in recorders
        ]
    except ClientError as exc:
        out["configRecorders"] = f"unavailable:{_api_message(exc)}"
    try:
        hub = _client(session, "securityhub", region=region)
        enabled = hub.describe_hub()
        out["securityHub"] = {
            "hubArn": enabled.get("HubArn"),
            "subscribedAt": enabled.get("SubscribedAt"),
        }
        findings = hub.get_findings(
            Filters={"RecordState": [{"Value": "ACTIVE", "Comparison": "EQUALS"}]},
            MaxResults=10,
        ).get("Findings", [])
        out["securityHubFindings"] = [
            {
                "title": f.get("Title"),
                "severity": f.get("Severity", {}).get("Label"),
                "product": f.get("ProductName"),
            }
            for f in findings
        ]
    except ClientError as exc:
        out["securityHub"] = f"unavailable:{_api_message(exc)}"
    try:
        gd = _client(session, "guardduty", region=region)
        detectors = gd.list_detectors().get("DetectorIds", [])
        out["guardDutyDetectors"] = detectors
    except ClientError as exc:
        out["guardDutyDetectors"] = f"unavailable:{_api_message(exc)}"
    return out


def build_environment_report(project_id: str) -> dict[str, Any]:
    """Fetch a live, read-only AWS environment report."""
    creds = load_credentials(project_id)
    session = _session(creds)
    identity = _caller_identity(session)
    regions = _scan_regions(creds)

    sections: list[str] = []
    sections.append(
        f"AWS account: {identity.get('Account')} | primary region: {creds.region} | "
        f"scan regions: {', '.join(regions)} | caller ARN: {identity.get('Arn')}"
        + (f" | assumed role: {creds.role_arn}" if creds.role_arn else "")
    )

    def _probe(label: str, fn) -> None:
        try:
            fn()
        except (BotoCoreError, ClientError) as exc:
            sections.append(f"{label}:\n(could not evaluate: {_api_message(exc)})")
        except AwsApiError as exc:
            sections.append(f"{label}:\n(could not evaluate: {exc})")

    all_instances: list[dict[str, Any]] = []
    all_open: list[dict[str, Any]] = []
    all_rds: list[dict[str, Any]] = []
    all_elbs: list[dict[str, Any]] = []
    all_lambdas: list[dict[str, Any]] = []
    vpc_blocks: list[str] = []

    def _regional() -> None:
        nonlocal all_instances, all_open, all_rds, all_elbs, all_lambdas
        for region in regions:
            instances, open_rules = _ec2_summary(session, region)
            for row in instances:
                row["region"] = region
            for row in open_rules:
                row["region"] = region
            all_instances.extend(instances)
            all_open.extend(open_rules)
            vpc = _vpc_summary(session, region)
            vpc_blocks.append(
                f"Region {region} VPCs ({len(vpc['vpcs'])}), "
                f"subnets ({len(vpc['subnets'])}), "
                f"public IGW routes ({len(vpc['publicRoutes'])}):\n"
                + _format_rows(vpc["vpcs"][:20])
                + "\nSubnets:\n"
                + _format_rows(vpc["subnets"][:30])
                + "\nPublic routes:\n"
                + _format_rows(vpc["publicRoutes"][:20])
            )
            elbs = _elb_summary(session, region)
            for row in elbs:
                row["region"] = region
            all_elbs.extend(elbs)
            lambdas = _lambda_summary(session, region)
            for row in lambdas:
                row["region"] = region
            all_lambdas.extend(lambdas)
            rds_rows = _rds_summary(session, region)
            for row in rds_rows:
                row["region"] = region
            all_rds.extend(rds_rows)

        sections.append(
            f"EC2 instances ({len(all_instances)} across {', '.join(regions)}):\n"
            + _format_rows(all_instances)
        )
        sections.append(
            "Security-group rules open to the internet on sensitive ports:\n"
            + _format_rows(all_open)
        )
        sections.extend(vpc_blocks)
        sections.append(
            f"Load balancers ({len(all_elbs)}):\n" + _format_rows(all_elbs)
        )
        sections.append(f"Lambda functions ({len(all_lambdas)}):\n" + _format_rows(all_lambdas))
        sections.append(
            f"RDS instances (public accessibility & encryption):\n"
            + _format_rows(all_rds)
        )

    def _s3() -> None:
        rows = _s3_summary(session)
        sections.append(
            "S3 buckets (public-access block & encryption at rest):\n"
            + _format_rows(rows)
        )

    def _iam() -> None:
        summary = _iam_summary(session)
        sections.append(
            "IAM account summary:\n" + json.dumps(summary, default=str, indent=None)
        )

    def _security_services() -> None:
        pack = _security_services_summary(session, creds.region)
        sections.append(
            "AWS Config / Security Hub / GuardDuty summary:\n"
            + json.dumps(pack, default=str, indent=2)
        )

    _probe("Regional compute/network/database", _regional)
    _probe("S3 buckets", _s3)
    _probe("IAM", _iam)
    _probe("Config/Security Hub/GuardDuty", _security_services)

    text = "\n\n".join(sections)
    return {
        "text": text,
        "meta": {
            "account": identity.get("Account"),
            "region": creds.region,
            "regions": regions,
            "resource_count": len(all_instances)
            + len(all_rds)
            + len(all_elbs)
            + len(all_lambdas),
        },
    }


def discover_topology(project_id: str) -> dict[str, Any]:
    """Return a structured AWS inventory with relationship edges."""
    creds = load_credentials(project_id)
    session = _session(creds)
    identity = _caller_identity(session)
    regions = _scan_regions(creds)
    instances: list[dict[str, Any]] = []
    open_rules: list[dict[str, Any]] = []
    rds_rows: list[dict[str, Any]] = []
    elbs: list[dict[str, Any]] = []
    lambdas: list[dict[str, Any]] = []
    vpcs: list[dict[str, Any]] = []
    for region in regions:
        inst, rules = _ec2_summary(session, region)
        for row in inst:
            row["region"] = region
        for row in rules:
            row["region"] = region
        instances.extend(inst)
        open_rules.extend(rules)
        vpc = _vpc_summary(session, region)
        for row in vpc["vpcs"]:
            row["region"] = region
            vpcs.append(row)
        for row in _elb_summary(session, region):
            row["region"] = region
            elbs.append(row)
        for row in _lambda_summary(session, region):
            row["region"] = region
            lambdas.append(row)
        for row in _rds_summary(session, region):
            row["region"] = region
            rds_rows.append(row)
    buckets = _s3_summary(session)
    edges: list[dict[str, str]] = []
    for inst in instances:
        for sg in inst.get("securityGroups") or []:
            edges.append(
                {
                    "from": str(inst.get("instanceId") or ""),
                    "to": str(sg),
                    "relation": "uses_security_group",
                }
            )
        if inst.get("subnetId"):
            edges.append(
                {
                    "from": str(inst.get("instanceId") or ""),
                    "to": str(inst.get("subnetId")),
                    "relation": "in_subnet",
                }
            )
        if inst.get("vpcId"):
            edges.append(
                {
                    "from": str(inst.get("instanceId") or ""),
                    "to": str(inst.get("vpcId")),
                    "relation": "in_vpc",
                }
            )
    for lb in elbs:
        if lb.get("vpcId"):
            edges.append(
                {
                    "from": str(lb.get("arn") or lb.get("name") or ""),
                    "to": str(lb.get("vpcId")),
                    "relation": "in_vpc",
                }
            )
    return {
        "provider": "aws",
        "account": identity.get("Account"),
        "region": creds.region,
        "regions": regions,
        "resource_count": len(instances)
        + len(buckets)
        + len(rds_rows)
        + len(elbs)
        + len(lambdas)
        + len(vpcs),
        "ec2": instances,
        "s3": buckets,
        "rds": rds_rows,
        "elb": elbs,
        "lambda": lambdas,
        "vpc": vpcs,
        "open_sg_rules": open_rules,
        "relationships": edges[:500],
        "text": (
            f"AWS TOPOLOGY — account {identity.get('Account')} region {creds.region}; "
            f"ec2={len(instances)} s3={len(buckets)} rds={len(rds_rows)} "
            f"elb={len(elbs)} lambda={len(lambdas)} vpc={len(vpcs)}; "
            f"{len(edges)} relationship edges."
        ),
    }


def parse_cost_period(text: str, today: Optional[date] = None) -> tuple[date, date, str]:
    """Resolve a natural-language billing period into (from, to, label)."""
    today = today or date.today()
    lowered = (text or "").lower()

    def _month_range(year: int, month: int) -> tuple[date, date, str]:
        first = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        last = date(year, month, last_day)
        if year == today.year and month == today.month:
            last = today
        return first, last, f"{calendar.month_name[month]} {year}"

    iso = re.search(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])\b", lowered)
    if iso:
        return _month_range(int(iso.group(1)), int(iso.group(2)))
    if "last month" in lowered or "previous month" in lowered:
        year, month = (
            (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        )
        return _month_range(year, month)
    if "this month" in lowered or "current month" in lowered:
        return _month_range(today.year, today.month)
    if "last 30" in lowered or "past 30" in lowered:
        start = today - timedelta(days=29)
        return start, today, "last 30 days"
    year_match = re.search(r"\b(20\d{2})\b", lowered)
    for token, month in _MONTHS.items():
        if re.search(rf"\b{token}\b", lowered):
            year = int(year_match.group(1)) if year_match else (
                today.year if month <= today.month else today.year - 1
            )
            return _month_range(year, month)
    return _month_range(today.year, today.month)


def build_cost_report(
    project_id: str,
    from_date: date,
    to_date: date,
    label: str,
    group_by: str = "service",
    service_filter: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Fetch real AWS spend via Cost Explorer for a period."""
    creds = load_credentials(project_id)
    session = _session(creds)
    # Cost Explorer is us-east-1 only.
    ce = _client(session, "ce", "us-east-1")
    end_exclusive = to_date + timedelta(days=1)
    group_key = "SERVICE" if group_by != "meter" else "USAGE_TYPE"
    try:
        response = ce.get_cost_and_usage(
            TimePeriod={
                "Start": from_date.isoformat(),
                "End": end_exclusive.isoformat(),
            },
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": group_key}],
        )
    except (BotoCoreError, ClientError) as exc:
        raise AwsApiError(
            f"Cost Explorer query failed: {_api_message(exc)}. Attach "
            "ce:GetCostAndUsage (Billing) permissions to the IAM principal."
        ) from exc

    filters = [s.lower() for s in (service_filter or [])]
    lines: list[dict[str, Any]] = []
    total = 0.0
    currency = "USD"
    for result in response.get("ResultsByTime", []):
        for group in result.get("Groups", []):
            keys = group.get("Keys") or ["(unknown)"]
            service = keys[0]
            if filters and not any(f in str(service).lower() for f in filters):
                continue
            amount_raw = (
                (group.get("Metrics") or {})
                .get("UnblendedCost", {})
                .get("Amount", "0")
            )
            amount = float(amount_raw or 0)
            total += amount
            currency = (
                (group.get("Metrics") or {})
                .get("UnblendedCost", {})
                .get("Unit", currency)
            )
            entry: dict[str, Any] = {"service": service, "cost": round(amount, 2)}
            if group_by == "meter" and len(keys) > 1:
                entry["meter"] = keys[1]
            elif group_by == "meter":
                entry["meter"] = service
            lines.append(entry)
    lines.sort(key=lambda item: item["cost"], reverse=True)
    filter_label = ", ".join(service_filter) if service_filter else ""
    scope = f"for {filter_label} " if filter_label else ""
    text_lines = [
        f"AWS Cost Explorer spend {scope}for {label} "
        f"({from_date.isoformat()} → {to_date.isoformat()}): "
        f"{round(total, 2)} {currency}",
        "By service:" if group_by != "meter" else "By usage type:",
    ]
    for item in lines[:40]:
        meter = f" / {item['meter']}" if item.get("meter") else ""
        text_lines.append(f"- {item['service']}{meter}: {item['cost']} {currency}")
    if not lines:
        text_lines.append("- (no charges in this period)")
    return {
        "text": "\n".join(text_lines),
        "meta": {
            "total": round(total, 2),
            "currency": currency,
            "label": label,
            "lines": lines,
            "provider": "aws",
        },
    }


def build_metrics_report(
    project_id: str,
    task: str,
    resource_types: Optional[list[str]] = None,
    resource_name: Optional[str] = None,
    metric_hints: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Fetch CloudWatch metrics for common AWS compute/database resources."""
    creds = load_credentials(project_id)
    session = _session(creds)
    cw = _client(session, "cloudwatch", creds.region)
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    lowered = (task or "").lower()
    hints = [h.lower() for h in (metric_hints or [])]
    want_cpu = any(h in hints or h in lowered for h in ("cpu", "utilization"))
    want_mem = any(h in hints or h in lowered for h in ("memory", "mem"))
    want_net = any(h in hints or h in lowered for h in ("network", "bytes"))
    if not (want_cpu or want_mem or want_net):
        want_cpu = True

    targets: list[dict[str, Any]] = []
    types = set(resource_types or [])
    if not types:
        if "rds" in lowered or "database" in lowered:
            types.add("rds")
        if "lambda" in lowered:
            types.add("lambda")
        if "elb" in lowered or "alb" in lowered or "load balancer" in lowered:
            types.add("elb")
        if not types:
            types.add("ec2")

    if "ec2" in types:
        instances, _ = _ec2_summary(session, creds.region)
        for inst in instances:
            if resource_name and resource_name.lower() not in str(inst.get("instanceId") or "").lower():
                continue
            if inst.get("state") not in (None, "running", "pending"):
                continue
            targets.append(
                {
                    "id": inst.get("instanceId"),
                    "label": inst.get("instanceId"),
                    "namespace": "AWS/EC2",
                    "dim_name": "InstanceId",
                    "metrics": (
                        (["CPUUtilization"] if want_cpu else [])
                        + (["NetworkIn", "NetworkOut"] if want_net else [])
                    ),
                }
            )
    if "rds" in types:
        for db in _rds_summary(session, creds.region):
            ident = db.get("identifier")
            if resource_name and resource_name.lower() not in str(ident or "").lower():
                continue
            targets.append(
                {
                    "id": ident,
                    "label": ident,
                    "namespace": "AWS/RDS",
                    "dim_name": "DBInstanceIdentifier",
                    "metrics": (
                        (["CPUUtilization"] if want_cpu else [])
                        + (["FreeableMemory"] if want_mem else [])
                    ),
                }
            )
    if "lambda" in types:
        for fn in _lambda_summary(session, creds.region):
            name = fn.get("name")
            if resource_name and resource_name.lower() not in str(name or "").lower():
                continue
            targets.append(
                {
                    "id": name,
                    "label": name,
                    "namespace": "AWS/Lambda",
                    "dim_name": "FunctionName",
                    "metrics": ["Invocations", "Errors", "Duration"],
                }
            )
    if "elb" in types:
        for lb in _elb_summary(session, creds.region):
            name = lb.get("name")
            if resource_name and resource_name.lower() not in str(name or "").lower():
                continue
            targets.append(
                {
                    "id": name,
                    "label": name,
                    "namespace": "AWS/ApplicationELB",
                    "dim_name": "LoadBalancer",
                    "metrics": ["RequestCount", "HTTPCode_Target_5XX_Count"],
                    "dim_value": (lb.get("arn") or "").split("loadbalancer/", 1)[-1],
                }
            )

    if not targets:
        raise AwsApiError(
            "No AWS resources matched the metrics request in region "
            f"{creds.region}."
        )

    charts: list[dict[str, Any]] = []
    lines: list[str] = [
        f"LIVE AWS CloudWatch metrics for the last 24h in {creds.region}:"
    ]
    for target in targets[:12]:
        dim_value = target.get("dim_value") or target["id"]
        for metric in target["metrics"]:
            try:
                resp = cw.get_metric_statistics(
                    Namespace=target["namespace"],
                    MetricName=metric,
                    Dimensions=[{"Name": target["dim_name"], "Value": dim_value}],
                    StartTime=start,
                    EndTime=end,
                    Period=300,
                    Statistics=["Average", "Maximum"],
                )
            except (BotoCoreError, ClientError) as exc:
                lines.append(
                    f"- {target['label']} {metric}: unavailable ({_api_message(exc)})"
                )
                continue
            points = sorted(resp.get("Datapoints", []), key=lambda p: p["Timestamp"])
            if not points:
                lines.append(f"- {target['label']} {metric}: no datapoints")
                continue
            avg = sum(float(p.get("Average") or 0) for p in points) / len(points)
            peak = max(float(p.get("Maximum") or 0) for p in points)
            lines.append(
                f"- {target['label']} {metric}: avg={round(avg, 2)} peak={round(peak, 2)}"
            )
            charts.append(
                {
                    "title": f"{target['label']} {metric}",
                    "unit": points[0].get("Unit") or "",
                    "type": "line",
                    "series": [
                        {
                            "name": target["label"],
                            "points": [
                                {
                                    "t": p["Timestamp"].isoformat(),
                                    "v": round(float(p.get("Average") or 0), 2),
                                }
                                for p in points
                            ],
                        }
                    ],
                }
            )
    return {"text": "\n".join(lines), "charts": charts, "meta": {"provider": "aws"}}


def build_status_report(
    project_id: str, task: str, resource_name: Optional[str] = None
) -> dict[str, Any]:
    """Lightweight AWS error/status signals from CloudWatch (ELB/Lambda)."""
    report = build_metrics_report(
        project_id,
        task or "errors 5xx lambda alb",
        resource_types=["lambda", "elb"],
        resource_name=resource_name,
        metric_hints=["errors", "requests"],
    )
    return {
        "text": "AWS status / error signals (CloudWatch):\n" + report["text"],
        "charts": report.get("charts", []),
        "meta": {"provider": "aws"},
    }


def build_logs_report(
    project_id: str, task: str, resource_name: Optional[str] = None
) -> dict[str, Any]:
    """Read recent CloudWatch log events for Lambda / common groups."""
    creds = load_credentials(project_id)
    session = _session(creds)
    logs = _client(session, "logs", creds.region)
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = end - 24 * 60 * 60 * 1000
    groups: list[str] = []
    try:
        paginator = logs.get_paginator("describe_log_groups")
        for page in paginator.paginate():
            for group in page.get("logGroups", []):
                name = group.get("logGroupName") or ""
                if resource_name and resource_name.lower() not in name.lower():
                    continue
                if any(
                    token in name.lower()
                    for token in ("lambda", "ecs", "api-gateway", "/aws/")
                ) or resource_name:
                    groups.append(name)
                if len(groups) >= 8:
                    break
            if len(groups) >= 8:
                break
    except (BotoCoreError, ClientError) as exc:
        raise AwsApiError(
            f"CloudWatch Logs list failed: {_api_message(exc)}"
        ) from exc
    if not groups:
        raise AwsApiError(
            f"No CloudWatch log groups matched in {creds.region}."
        )

    lines = [
        f"LIVE AWS CloudWatch Logs (last 24h) in {creds.region}:",
    ]
    lowered = (task or "").lower()
    filter_pattern = None
    if any(tok in lowered for tok in ("error", "exception", "fail", "5xx", "traceback")):
        filter_pattern = "?ERROR ?Error ?Exception ?Fail ?5xx"
    for group in groups:
        try:
            kwargs: dict[str, Any] = {
                "logGroupName": group,
                "startTime": start,
                "endTime": end,
                "limit": 20,
            }
            if filter_pattern:
                kwargs["filterPattern"] = filter_pattern
            events = logs.filter_log_events(**kwargs).get("events", [])
        except (BotoCoreError, ClientError) as exc:
            lines.append(f"- {group}: unavailable ({_api_message(exc)})")
            continue
        lines.append(f"- {group}: {len(events)} matching events")
        for event in events[:8]:
            msg = str(event.get("message") or "").strip().replace("\n", " ")
            lines.append(f"  · {msg[:240]}")
    return {"text": "\n".join(lines), "meta": {"provider": "aws", "groups": groups}}
