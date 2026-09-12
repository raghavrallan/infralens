"""AWS parity extensions outside aws_infra/orchestrator wiring."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.providers import aws_infra
from app.providers.aws_infra import AwsCredentials


@pytest.mark.unit
def test_parse_cost_period_last_month_returns_tuple():
    result = aws_infra.parse_cost_period("last month", today=date(2026, 9, 12))
    assert isinstance(result, tuple)
    assert len(result) == 3
    start, end, label = result
    assert isinstance(start, date)
    assert isinstance(end, date)
    assert isinstance(label, str)


@pytest.mark.unit
def test_format_rows_empty_still_none_found():
    assert aws_infra._format_rows([]) == "(none found)"


@pytest.mark.unit
def test_discover_topology_edge_uses_security_groups():
    creds = AwsCredentials("AKI", "SECRET", "us-east-1")
    instance = {
        "instanceId": "i-abc",
        "securityGroups": ["sg-111", "sg-222"],
        "subnetId": "subnet-1",
        "vpcId": "vpc-1",
    }
    with patch("app.providers.aws_infra.load_credentials", return_value=creds):
        with patch("app.providers.aws_infra._session", return_value=MagicMock()):
            with patch(
                "app.providers.aws_infra._caller_identity",
                return_value={"Account": "123456789012"},
            ):
                with patch(
                    "app.providers.aws_infra._ec2_summary",
                    return_value=([instance], []),
                ):
                    with patch("app.providers.aws_infra._s3_summary", return_value=[]):
                        with patch(
                            "app.providers.aws_infra._rds_summary", return_value=[]
                        ):
                            with patch(
                                "app.providers.aws_infra._vpc_summary",
                                return_value={
                                    "vpcs": [],
                                    "subnets": [],
                                    "publicRoutes": [],
                                },
                            ):
                                with patch(
                                    "app.providers.aws_infra._elb_summary",
                                    return_value=[],
                                ):
                                    with patch(
                                        "app.providers.aws_infra._lambda_summary",
                                        return_value=[],
                                    ):
                                        topo = aws_infra.discover_topology("p1")
    relations = {
        (edge.get("from"), edge.get("to"), edge.get("relation"))
        for edge in topo.get("relationships") or []
    }
    assert ("i-abc", "sg-111", "uses_security_group") in relations
    assert ("i-abc", "sg-222", "uses_security_group") in relations
