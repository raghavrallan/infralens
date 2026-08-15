"""Additional execution validation branches and queue naming."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.execution.queue import (
    enqueue_action,
    provider_queue_names,
    queue_depth,
    queue_name,
    queue_snapshot,
)
from app.execution.validation import (
    command_argv,
    command_preview,
    validate_operation,
    validate_rollback_plan,
)


@pytest.mark.unit
def test_validate_operation_rejects_unknown_provider_and_scope():
    with pytest.raises(ValueError, match="Unsupported provider"):
        validate_operation("gcp", "gcloud", ["x"], "t", "read_only")
    with pytest.raises(ValueError, match="Unsupported access scope"):
        validate_operation("azure", "az", ["account", "show"], "t", "admin")
    with pytest.raises(ValueError, match="Invalid action target"):
        validate_operation("azure", "az", ["account", "show"], "bad|target", "read_only")


@pytest.mark.unit
def test_validate_operation_arg_limits_and_empty():
    with pytest.raises(ValueError, match="at least one"):
        validate_operation("azure", "az", [], "t", "read_only")
    with pytest.raises(ValueError, match="invalid argument"):
        validate_operation("azure", "az", [""], "t", "read_only")
    with pytest.raises(ValueError, match="invalid argument"):
        validate_operation("azure", "az", [None], "t", "read_only")  # type: ignore[list-item]
    with pytest.raises(ValueError, match="too many"):
        validate_operation("azure", "az", ["a"] * 200, "t", "read_only")
    with pytest.raises(ValueError, match="Nested shell"):
        validate_operation("azure", "az", ["bash"], "t", "read_only")


@pytest.mark.unit
def test_terraform_write_must_be_apply_or_destroy():
    with pytest.raises(ValueError, match="apply or destroy"):
        validate_operation(
            "terraform",
            "terraform",
            ["plan"],
            "ws",
            "write",
            ["validate"],
            ["show"],
        )
    op = validate_operation(
        "terraform",
        "terraform",
        ["apply", "-auto-approve"],
        "ws",
        "write",
        ["validate"],
        ["show"],
    )
    assert op["executable"] == "terraform"


@pytest.mark.unit
def test_rollback_plan_structured_and_prose():
    structured = validate_rollback_plan(
        "",
        provider="azure",
        args=["group", "create"],
        rollback_operation={
            "provider": "azure",
            "executable": "az",
            "args": ["group", "delete", "--name", "x", "--yes"],
        },
    )
    assert structured["mode"] == "structured"
    prose = validate_rollback_plan(
        "delete the resource group with az group delete",
        provider="azure",
        args=["group", "create"],
    )
    assert prose["mode"] == "prose"
    with pytest.raises(ValueError, match="rollback"):
        validate_rollback_plan("", provider="azure", args=["group", "create"])
    with pytest.raises(ValueError, match="rollback"):
        validate_rollback_plan("too short", provider="azure", args=["x"])


@pytest.mark.unit
def test_rollback_json_object_and_invalid_provider():
    plan = validate_rollback_plan(
        '{"provider":"aws","executable":"aws","args":["s3","rb","s3://x"]}',
        provider="aws",
        args=["s3", "mb"],
    )
    assert plan["provider"] == "aws"
    with pytest.raises(ValueError, match="unsupported provider"):
        validate_rollback_plan(
            '{"provider":"gcp","args":["x"]}',
            provider="azure",
            args=["x"],
        )


@pytest.mark.unit
def test_command_argv_and_preview():
    op = validate_operation("aws", "aws", ["sts", "get-caller-identity"], "acct", "read_only")
    assert command_argv(op)[0] == "aws"
    assert "sts" in command_preview(op)


@pytest.mark.unit
def test_queue_name_and_snapshot_failure():
    assert queue_name("org1", "azure", "write").endswith(".write")
    assert provider_queue_names("org1", "azure") == [
        "org.org1.provider.azure.read",
        "org.org1.provider.azure.write",
    ]
    with patch("app.execution.queue.get_redis", side_effect=RuntimeError("down")):
        snap = queue_snapshot("org1", "azure", "read_only")
    assert snap["redis_available"] is False
    assert snap["executor_available"] is False


@pytest.mark.unit
def test_queue_depth_swallows_errors():
    with patch("app.execution.queue.get_queue", side_effect=RuntimeError("down")):
        assert queue_depth("org1") == 0


@pytest.mark.unit
def test_enqueue_action_only_sends_action_id():
    queue = MagicMock()
    job = MagicMock(id="rq-1")
    queue.enqueue.return_value = job
    with patch("app.execution.queue.get_queue", return_value=queue):
        with patch(
            "app.execution.queue.queue_snapshot",
            return_value={"queue": "q", "redis_available": True},
        ):
            result = enqueue_action("act-1", "org1", "azure", "read_only")
    assert result["rq_job_id"] == "rq-1"
    args, kwargs = queue.enqueue.call_args
    assert args[1] == "act-1"
    assert "secret" not in str(args)
