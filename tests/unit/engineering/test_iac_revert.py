"""Gated isolated-stack revert and non-admin revert requests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.platform.engineering import iac_delivery, iac_revert


@pytest.mark.unit
def test_run_destroy_requires_apply_and_confirm():
    with patch(
        "app.platform.engineering.iac_delivery._run",
        return_value={"id": "r1", "project_id": "p1", "artifacts": {}},
    ):
        with pytest.raises(ValueError, match="Nothing to revert"):
            iac_delivery.run_destroy("r1", confirm=True)
    with patch(
        "app.platform.engineering.iac_delivery._run",
        return_value={
            "id": "r1",
            "project_id": "p1",
            "artifacts": {"apply_result": {"status": "applied"}},
        },
    ):
        with pytest.raises(ValueError, match="confirm"):
            iac_delivery.run_destroy("r1", confirm=False)


@pytest.mark.unit
def test_run_allows_completed_delivery_for_isolated_iac():
    row = MagicMock()
    row.id = "r1"
    row.project_id = "p1"
    row.status = "completed"
    row.artifacts = {"apply_result": {"status": "applied"}}
    session = MagicMock()
    session.get.return_value = row
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    with patch("app.platform.engineering.iac_delivery.SessionLocal", return_value=context):
        loaded = iac_delivery._run("r1")
    assert loaded == {
        "id": "r1",
        "project_id": "p1",
        "artifacts": {"apply_result": {"status": "applied"}},
    }
    row.status = "abandoned"
    with patch("app.platform.engineering.iac_delivery.SessionLocal", return_value=context):
        with pytest.raises(ValueError, match="not active"):
            iac_delivery._run("r1")


@pytest.mark.unit
def test_developer_raises_revert_request_instead_of_destroy():
    created = {"id": "req1", "status": "pending", "reason": "undo"}

    with patch(
        "app.platform.engineering.iac_delivery._run",
        return_value={
            "id": "r1",
            "project_id": "p1",
            "artifacts": {"apply_result": {"status": "applied"}},
        },
    ):
        with patch("app.platform.engineering.iac_revert.can_execute_revert", return_value=False):
            with patch("app.platform.engineering.iac_revert.create_request", return_value=created):
                result = iac_revert.request_or_run(
                    "r1",
                    {"id": "u1", "role": "developer"},
                    confirm=False,
                    reason="undo",
                )
    assert result["mode"] == "requested"
    assert result["request"]["id"] == "req1"


@pytest.mark.unit
def test_org_admin_executes_revert():
    run = {"id": "r1", "artifacts": {"revert_result": {"status": "reverted"}}}
    with patch(
        "app.platform.engineering.iac_delivery._run",
        return_value={
            "id": "r1",
            "project_id": "p1",
            "artifacts": {"apply_result": {"status": "applied"}},
        },
    ):
        with patch("app.platform.engineering.iac_revert.can_execute_revert", return_value=True):
            with patch("app.platform.engineering.iac_delivery.run_destroy", return_value=run) as destroy:
                result = iac_revert.request_or_run(
                    "r1",
                    {"id": "admin", "role": "org_admin"},
                    confirm=True,
                )
    destroy.assert_called_once_with("r1", confirm=True)
    assert result["mode"] == "executed"
    assert result["run"]["artifacts"]["revert_result"]["status"] == "reverted"


@pytest.mark.unit
def test_destroy_once_records_revert_result():
    with patch(
        "app.platform.engineering.iac_workspace.sync",
        return_value={"workspace": "/tmp/ws"},
    ):
        with patch(
            "app.platform.engineering.iac_workspace.run_phase",
            return_value={"returncode": 0, "stdout": "Destroy complete", "stderr": "", "workspace": "/tmp/ws"},
        ):
            outcome = iac_delivery._run_destroy_once("p1", "r1")
    assert outcome["ok"] is True
    assert outcome["revert_result"]["status"] == "reverted"


@pytest.mark.unit
def test_can_execute_revert_uses_effective_org_admin():
    with patch(
        "app.platform.engineering.iac_revert.memberships.effective_role_for_project",
        return_value="org_admin",
    ):
        assert iac_revert.can_execute_revert({"role": "developer"}, "p1") is True
    with patch(
        "app.platform.engineering.iac_revert.memberships.effective_role_for_project",
        return_value="devops_lead",
    ):
        assert iac_revert.can_execute_revert({"role": "devops_lead"}, "p1") is False
    with patch(
        "app.platform.engineering.iac_revert.memberships.effective_role_for_project",
        return_value="super_admin",
    ):
        assert iac_revert.can_execute_revert({"role": "super_admin"}, "p1") is True
