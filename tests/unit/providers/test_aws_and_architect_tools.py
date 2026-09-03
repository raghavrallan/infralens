"""Architect tool adapters and AWS inventory helpers with mocked SDKs."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import app.skills  # noqa: F401  register skills before importing architect tools
from app.agents.solution_architect import tools
from app.providers import aws_infra
from app.providers.aws_infra import AwsCredentials


@pytest.mark.unit
def test_clip_safe_and_inventory_empty():
    assert len(tools._clip("x" * 50, 10)) == 10
    assert "hello" in tools._clip({"text": "hello"})
    assert tools._safe("x", lambda: None).endswith("(empty)")
    assert "unavailable" in tools._safe("x", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert tools.inventory_is_empty("azure: not connected\naws: not connected")
    assert not tools.inventory_is_empty("azure ENVIRONMENT DATA\nresource count 12")


@pytest.mark.unit
def test_get_cloud_inventory_and_cost_when_disconnected():
    with patch("app.providers.azure_infra.is_connected", return_value=False):
        with patch("app.providers.aws_infra.is_connected", return_value=False):
            with patch("app.providers.github_infra.is_connected", return_value=False):
                text = tools.get_cloud_inventory("p1")
    assert "not connected" in text
    with patch("app.providers.azure_infra.is_connected", return_value=False):
        assert "not connected" in tools.get_cost_report("p1")
    with patch("app.providers.github_infra.is_connected", return_value=False):
        assert "not connected" in tools.get_code_artifacts("p1")


@pytest.mark.unit
def test_run_skill_allowlist_and_preview_gate():
    assert "allow-list" in tools.run_skill("terraform_executor", {})
    skill = MagicMock()
    skill.run.return_value = MagicMock(content="ok")
    with patch("app.skills.registry.get", return_value=skill):
        assert tools.run_skill("iac_reviewer", {"input": "x"}) == "ok"
    gate = tools.preview_gate("config_code_change", "low", "dev")
    assert gate["gate"]
    with patch("app.platform.engineering.knowledge.architect_context", return_value={}):
        with patch("app.platform.memory.list_precedent", return_value=[]):
            assert "No engineering precedent" in tools.search_precedent("p1")


@pytest.mark.unit
def test_aws_ec2_s3_rds_iam_summaries():
    session = MagicMock()
    ec2 = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-1",
                            "InstanceType": "t3.micro",
                            "State": {"Name": "running"},
                            "PublicIpAddress": "1.2.3.4",
                            "Placement": {"AvailabilityZone": "us-east-1a"},
                        }
                    ]
                }
            ]
        }
    ]
    sg_paginator = MagicMock()
    sg_paginator.paginate.return_value = [
        {
            "SecurityGroups": [
                {
                    "GroupId": "sg-1",
                    "GroupName": "open",
                    "IpPermissions": [
                        {
                            "FromPort": 22,
                            "ToPort": 22,
                            "IpProtocol": "tcp",
                            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                            "Ipv6Ranges": [],
                        }
                    ],
                }
            ]
        }
    ]
    ec2.get_paginator.side_effect = lambda name: paginator if name == "describe_instances" else sg_paginator
    s3 = MagicMock()
    s3.list_buckets.return_value = {"Buckets": [{"Name": "b1"}]}
    s3.get_public_access_block.return_value = {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        }
    }
    s3.get_bucket_encryption.return_value = {}
    rds = MagicMock()
    rds_paginator = MagicMock()
    rds_paginator.paginate.return_value = [
        {
            "DBInstances": [
                {
                    "DBInstanceIdentifier": "db1",
                    "PubliclyAccessible": False,
                    "StorageEncrypted": True,
                    "Engine": "postgres",
                    "MultiAZ": False,
                }
            ]
        }
    ]
    rds.get_paginator.return_value = rds_paginator
    iam = MagicMock()
    iam.get_account_summary.return_value = {"SummaryMap": {"Users": 2}}

    def client(_session, service, **_k):
        return {"ec2": ec2, "s3": s3, "rds": rds, "iam": iam, "sts": MagicMock()}[service]

    with patch("app.providers.aws_infra._client", side_effect=client):
        instances, rules = aws_infra._ec2_summary(session)
        buckets = aws_infra._s3_summary(session)
        rds_rows = aws_infra._rds_summary(session)
        iam_summary = aws_infra._iam_summary(session)
    assert instances[0]["instanceId"] == "i-1"
    assert rules[0]["securityGroup"] == "sg-1"
    assert buckets[0]["encryptionAtRest"] is True
    assert rds_rows[0]["identifier"] == "db1"
    assert iam_summary


@pytest.mark.unit
def test_aws_api_message_and_discover_topology():
    err = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "nope"}},
        "GetCallerIdentity",
    )
    assert "AccessDenied" in aws_infra._api_message(err)
    creds = AwsCredentials("AKI", "SECRET", "us-east-1")
    session = MagicMock()
    with patch("app.providers.aws_infra.load_credentials", return_value=creds):
        with patch("app.providers.aws_infra._session", return_value=session):
            with patch("app.providers.aws_infra._caller_identity", return_value={"Account": "1"}):
                with patch("app.providers.aws_infra._ec2_summary", return_value=([{"instanceId": "i-1"}], [])):
                    with patch("app.providers.aws_infra._s3_summary", return_value=[]):
                        with patch("app.providers.aws_infra._rds_summary", return_value=[]):
                            topo = aws_infra.discover_topology("p1")
    assert topo["provider"] == "aws"
    assert topo["resource_count"] >= 1
