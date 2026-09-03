"""Unit tests for the connected architect / delivery / memory workflow."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from app.api.routes_engineering import _stub_artifact
from app.core import rbac
from app.platform.engineering.artifacts import _validate
from app.platform.engineering.generate import _select_specs
from app.platform.engineering.health import (
    _blockers,
    _pct,
    _recommendations,
    _summary,
    _timeline,
    production_readiness,
)
from app.platform.engineering.intake import extract_text, infer_kind
from app.platform.engineering.knowledge import _category_from_kind, _enrich, _is_stale, _prompt
from app.platform.engineering.state_machine import (
    STATUSES,
    TRANSITIONS,
    assert_transition,
    can_transition,
    completion_blockers,
    missing_artifacts,
)


@pytest.mark.unit
def test_task_transitions_are_gated():
    assert can_transition("ready", "in_progress")
    assert can_transition("approved", "completed")
    assert not can_transition("ready", "completed")
    assert not can_transition("completed", "ready")
    assert not can_transition("not_started", "completed")


@pytest.mark.unit
def test_every_status_has_an_explicit_edge_map():
    assert set(STATUSES) == set(TRANSITIONS)
    for status, targets in TRANSITIONS.items():
        for target in targets:
            assert target in STATUSES
            assert can_transition(status, target)


@pytest.mark.unit
def test_assert_transition_rejects_skip():
    with pytest.raises(ValueError, match="in_progress"):
        assert_transition("in_progress", "completed")
    assert_transition("approved", "approved")


@pytest.mark.unit
def test_missing_artifacts_and_completion_rules():
    required = [{"name": "vpc.tf"}, {"name": "variables.tf"}]
    assert missing_artifacts(required, ["vpc.tf"]) == ["variables.tf"]
    blockers = completion_blockers(
        status="approved",
        required_artifacts=required,
        attached_names=["vpc.tf", "variables.tf"],
        validation_ok=True,
        dependency_ids=["dep-1"],
        completed_ids=set(),
        acceptance=["plan passed"],
        evidence=[],
    )
    assert any("dependenc" in item for item in blockers)
    assert any("evidence" in item.lower() for item in blockers)
    clear = completion_blockers(
        status="approved",
        required_artifacts=required,
        attached_names=["vpc.tf", "variables.tf"],
        validation_ok=True,
        dependency_ids=["dep-1"],
        completed_ids={"dep-1"},
        acceptance=["plan passed"],
        evidence=[{"name": "plan.txt"}],
    )
    assert clear == []
    unapproved = completion_blockers(
        status="in_progress",
        required_artifacts=[],
        attached_names=[],
        validation_ok=True,
        dependency_ids=[],
        completed_ids=set(),
        acceptance=[],
        evidence=[],
    )
    assert any("approved" in item.lower() for item in unapproved)
    failed_validation = completion_blockers(
        status="approved",
        required_artifacts=[],
        attached_names=[],
        validation_ok=False,
        dependency_ids=[],
        completed_ids=set(),
        acceptance=[],
        evidence=[],
    )
    assert any("Validation" in item for item in failed_validation)


@pytest.mark.unit
def test_checklist_generated_from_architecture_text_not_hardcoded_only():
    specs = _select_specs("aws eks rds redis s3 cloudfront waf terraform github actions", [])
    titles = [item["title"] for item in specs]
    assert any("Compute" in title or "cluster" in title.lower() for title in titles)
    assert any("Database" in title for title in titles)
    assert any("CI/CD" in title for title in titles)
    assert any("documentation" in title.lower() or title.lower().startswith("architecture") for title in titles[-2:])


@pytest.mark.unit
def test_checklist_includes_adr_implementation_tasks():
    specs = _select_specs("generic web app", [{"id": "d1", "title": "Use Amazon EKS", "decision": "EKS"}])
    titles = [item["title"] for item in specs]
    assert any("Use Amazon EKS" in title for title in titles)
    assert any(item.get("decision_id") == "d1" for item in specs)


@pytest.mark.unit
def test_empty_architecture_still_gets_baseline_tasks():
    specs = _select_specs("hello world", [])
    titles = [item["title"] for item in specs]
    assert any("baseline" in title.lower() or "terraform" in title.lower() for title in titles)
    assert len(specs) >= 3


@pytest.mark.unit
def test_health_percent_uses_real_counts():
    assert _pct(4, 5) == 80
    assert _pct(0, 0) == 0
    assert _pct(1, 3) == 33


@pytest.mark.unit
def test_infer_kind_and_extract_text():
    assert infer_kind("vpc.tf") == "terraform"
    assert infer_kind("chart.yaml") == "yaml"
    assert infer_kind("app.py") == "python"
    assert infer_kind("Dockerfile") == "docker"
    assert infer_kind("shot.png", "image/png") == "diagram"
    assert infer_kind("notes.bin") == "document"
    assert "hello" in extract_text("readme.md", b"hello infra")
    binary = extract_text("blob.bin", b"\x00\x01\x02secret")
    assert "binary" in binary.lower()
    assert "could not parse" in extract_text("brief.docx", b"not-a-zip")


@pytest.mark.unit
def test_extract_docx_reads_word_xml():
    buffer = BytesIO()
    xml = (
        b'<?xml version="1.0"?><w:document xmlns:w='
        b'"http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body><w:p><w:r><w:t>Need EKS and RDS</w:t></w:r></w:p></w:body></w:document>"
    )
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    text = extract_text("reqs.docx", buffer.getvalue())
    assert "EKS" in text and "RDS" in text


@pytest.mark.unit
def test_artifact_validation_terraform_yaml_docker_python_json():
    with patch("app.platform.engineering.artifacts._maybe_terraform_validate", return_value=None):
        tf = _validate("terraform", "main.tf", 'resource "aws_vpc" "main" {}')
    assert tf["status"] == "passed"


@pytest.mark.unit
def test_null_resource_stub_fails_terraform_validation():
    report = _validate(
        "terraform",
        "network.tf",
        'terraform {}\nresource "null_resource" "x" { triggers = { a = "1" } }\n',
    )
    assert report["status"] == "failed"


@pytest.mark.unit
def test_backend_tf_validates_as_backend_companion():
    report = _validate(
        "terraform",
        "backend.tf",
        'terraform {\n  backend "local" {\n    path = "terraform.tfstate"\n  }\n}\n',
    )
    assert report["status"] == "passed"
    assert any(item["name"] == "terraform_backend" for item in report["checks"])


@pytest.mark.unit
def test_artifact_validation_python_docker_json():
    bad_py = _validate("python", "app.py", "def broken(:\n  pass")
    assert bad_py["status"] == "failed"
    good_py = _validate("python", "app.py", "def ok():\n    return 1\n")
    assert good_py["status"] == "passed"
    docker = _validate("docker", "Dockerfile", "FROM python:3.12\nCMD python")
    assert docker["status"] == "passed"
    js = _validate("json", "x.json", '{"ok": true}')
    assert js["status"] == "passed"
    bad_json = _validate("json", "x.json", "{nope")
    assert bad_json["status"] == "failed"


@pytest.mark.unit
def test_get_artifact_full_returns_complete_text():
    from app.platform.engineering.artifacts import get_artifact

    with patch("app.platform.engineering.artifacts.SessionLocal") as session_local:
        row = SimpleNamespace(
            id="a1",
            project_id="p1",
            delivery_run_id="",
            task_id="t1",
            name="README.md",
            kind="document",
            mime="text/plain",
            filename="README.md",
            origin="generated",
            stage="",
            content_text="x" * 25_000,
            validation_status="passed",
            validation_report={},
            version=1,
            created_by="u",
            created_at=None,
            updated_at=None,
        )
        session_local.return_value.__enter__.return_value.get.return_value = row
        preview = get_artifact("a1")
        full = get_artifact("a1", full=True)
    assert preview is not None and full is not None
    assert len(preview["content_text"]) == 20_000
    assert len(full["content_text"]) == 25_000


@pytest.mark.unit
def test_generated_stubs_are_valid_enough_to_attach():
    with patch("app.platform.engineering.iac_generate.load_architecture", return_value={}):
        tf = _stub_artifact("terraform", "network.tf", "Create VPC", "")
        providers = _stub_artifact("terraform", "providers.tf", "Terraform backend", "")
        yml = _stub_artifact("yaml", "ci.yml", "CI/CD", "")
        py = _stub_artifact("python", "test_smoke.py", "Tests", "")
        md = _stub_artifact("document", "architecture.md", "Docs", "Write the HLD")
    assert "azurerm_virtual_network" in tf
    assert "required_providers" in providers
    assert "jobs:" in yml
    assert "def test_architecture_contract" in py
    assert "Docs" in md


@pytest.mark.unit
def test_timeline_and_blockers_reflect_task_state():
    items = [
        {"id": "a", "stage": "architecture", "status": "completed", "title": "ADR", "priority": "low", "missing_artifacts": []},
        {"id": "b", "stage": "infrastructure", "status": "blocked", "title": "VPC", "priority": "high", "blocked_reason": "Waiting on ADR", "missing_artifacts": []},
        {"id": "c", "stage": "security", "status": "validation_failed", "title": "IAM", "priority": "medium", "missing_artifacts": ["iam.tf"]},
        {"id": "d", "stage": "testing", "status": "not_started", "title": "pytest", "priority": "low", "missing_artifacts": []},
        {"id": "e", "stage": "deployment", "status": "not_started", "title": "prod", "priority": "high", "missing_artifacts": []},
    ]
    timeline = {row["stage"]: row["state"] for row in _timeline(items)}
    assert timeline["architecture"] == "done"
    assert timeline["infrastructure"] == "blocked"
    assert timeline["deployment"] == "pending"
    blockers = _blockers(items, [{"id": "r1", "title": "No backups", "severity": "high"}])
    levels = {row["level"] for row in blockers}
    assert "high" in levels
    assert any("VPC" in row["title"] for row in blockers)
    assert any("Validation failed" in row["title"] for row in blockers)


@pytest.mark.unit
def test_production_readiness_blocks_incomplete_gates():
    items = [
        {"stage": "architecture", "status": "completed", "missing_artifacts": []},
        {"stage": "infrastructure", "status": "in_progress", "missing_artifacts": ["vpc.tf"]},
        {"stage": "security", "status": "completed", "missing_artifacts": []},
        {"stage": "testing", "status": "completed", "missing_artifacts": []},
    ]
    result = production_readiness("p1", items=items, risks=[{"severity": "low"}])
    assert result["ready"] is False
    assert "Not Ready" in result["status"]
    names = {check["name"]: check["ok"] for check in result["checks"]}
    assert names["Architecture approved"] is True
    assert names["Infrastructure validated"] is False
    assert names["Required artifacts available"] is False

    ready = production_readiness(
        "p1",
        items=[
            {"stage": "architecture", "status": "completed", "missing_artifacts": []},
            {"stage": "infrastructure", "status": "completed", "missing_artifacts": []},
            {"stage": "security", "status": "completed", "missing_artifacts": []},
            {"stage": "testing", "status": "completed", "missing_artifacts": []},
        ],
        risks=[],
    )
    assert ready["ready"] is True

    empty = production_readiness("p1", items=[], risks=[])
    names = {check["name"]: check["ok"] for check in empty["checks"]}
    assert names["Architecture approved"] is False
    assert names["Tests passed"] is True
    assert empty["ready"] is False


@pytest.mark.unit
def test_recommendations_and_summary_use_live_gaps():
    items = [
        {
            "id": "t1",
            "title": "VPC",
            "status": "ready",
            "stage": "infrastructure",
            "priority": "high",
            "ai_recommendation": "Start here",
        }
    ]
    recs = _recommendations(
        items,
        artifacts=[],
        risks=[
            {
                "id": "r1",
                "title": "No backups",
                "severity": "high",
                "impact": "data loss",
                "recommendation": "Add RDS backups",
                "related_task_id": "t1",
            }
        ],
        memory_rows=[{"stale": True, "status": "active"}],
    )
    titles = [row["title"] for row in recs]
    assert any("backup" in title.lower() for title in titles)
    assert any("Work next" in title for title in titles)
    assert any("stale" in title.lower() for title in titles)
    assert any(row["action"] == "generate_terraform" for row in recs)
    summary = _summary(
        {"architecture": {"percent": 80}},
        [{"level": "high", "title": "IAM pending"}],
        items + [{"status": "blocked", "title": "EKS"}],
        {"ready": False, "checks": [{"name": "Security approved", "ok": False}]},
    )
    assert "80%" in summary
    assert "blocked" in summary.lower()
    assert "Security approved" in summary
    ready_summary = _summary(
        {"architecture": {"percent": 0}},
        [],
        items,
        {"ready": False, "checks": []},
        architecture_status="ready",
    )
    assert "proposal is ready" in ready_summary.lower()


@pytest.mark.unit
def test_memory_lifecycle_helpers():
    assert _category_from_kind("architecture_decision") == "decision"
    assert _category_from_kind("requirement") == "requirement"
    assert _category_from_kind("action") == "infrastructure"
    old = datetime.now(timezone.utc) - timedelta(days=120)
    assert _is_stale({"status": "active"}, old) is True
    assert _is_stale({"status": "verified", "last_verified_at": datetime.now(timezone.utc).isoformat()}, old) is False
    assert _is_stale({"status": "superseded"}, datetime.now(timezone.utc)) is True
    prompt = _prompt(
        ["fact-a"],
        ["use postgres"],
        ["maybe redis"],
        [{"category": "compute", "entries": [{"summary": "EKS"}, {"summary": "ECS"}]}],
    )
    assert "Known facts" in prompt
    assert "CONFLICTS" in prompt
    assert "EKS" in prompt
    row = SimpleNamespace(
        id="m1",
        project_id="p1",
        kind="architecture_decision",
        ref_id="d1",
        summary="Use EKS",
        outcome="proposed",
        payload={"status": "active", "confidence": "high", "source": "architect", "category": "decision"},
        created_at=datetime.now(timezone.utc),
    )
    enriched = _enrich(row)
    assert enriched["status"] == "active"
    assert enriched["confidence"] == "high"
    assert enriched["title"]


@pytest.mark.unit
def test_memory_rbac_capabilities():
    assert rbac.can({"role": "devops_engineer"}, "verify_memory")
    assert not rbac.can({"role": "developer"}, "verify_memory")
    assert rbac.can({"role": "devops_lead"}, "archive_memory")
    assert not rbac.can({"role": "devops_engineer"}, "archive_memory")


@pytest.mark.unit
def test_build_health_aggregates_mocked_project_state():
    items = [
        {"id": "1", "stage": "architecture", "status": "completed", "title": "HLD", "priority": "low", "missing_artifacts": [], "ai_recommendation": ""},
        {"id": "2", "stage": "infrastructure", "status": "in_progress", "title": "VPC", "priority": "high", "missing_artifacts": [], "ai_recommendation": "Attach TF"},
    ]
    with patch("app.platform.engineering.health.task_store.list_tasks", return_value=items):
        with patch("app.platform.engineering.health.knowledge.list_knowledge", return_value=[{"status": "verified"}]):
            with patch("app.platform.engineering.health.artifact_store.list_artifacts", return_value=[{"kind": "terraform"}]):
                with patch("app.platform.engineering.health._open_risks", return_value=[]):
                    with patch("app.platform.engineering.health._pending_adrs", return_value=2):
                        with patch("app.platform.engineering.health._delivery_architecture_status", return_value=""):
                            from app.platform.engineering.health import build_health

                            snapshot = build_health("proj-1")
    assert snapshot["bars"]["architecture"]["percent"] == 100
    assert snapshot["bars"]["infrastructure"]["percent"] == 0
    assert snapshot["task_counts"]["total"] == 2
    assert snapshot["pending_adrs"] == 2
    assert snapshot["memory_count"] == 1
    assert "summary" in snapshot


@pytest.mark.unit
def test_delivery_architecture_status_reads_latest_run():
    from app.platform.engineering.health import _delivery_architecture_status

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, *_args, **_kwargs):
            return SimpleNamespace(artifacts={"architecture_status": "ready"})

    with patch("app.platform.engineering.health.SessionLocal", return_value=Session()):
        assert _delivery_architecture_status("proj-1") == "ready"


@pytest.mark.unit
def test_apply_architect_result_requires_project():
    from app.platform.engineering.generate import apply_architect_result

    assert apply_architect_result({}, run_id="r1", gated=[])["ok"] is False


@pytest.mark.unit
def test_apply_architect_result_writes_requirements_tasks_and_memory():
    from app.platform.engineering.generate import apply_architect_result

    created = []

    def fake_create_task(**kwargs):
        item = {"id": f"task-{len(created)+1}", **kwargs}
        created.append(item)
        return item

    with patch("app.platform.engineering.generate._latest_delivery_run", return_value="del-1"):
        with patch("app.platform.engineering.generate._save_requirement", return_value="req-1"):
            with patch("app.platform.engineering.generate.knowledge.remember"):
                with patch("app.platform.engineering.generate.task_store.list_tasks", return_value=[]):
                    with patch("app.platform.engineering.generate.task_store.create_task", side_effect=fake_create_task):
                        with patch("app.platform.engineering.generate._risks_from_text", return_value=["risk-1"]):
                            with patch("app.platform.engineering.generate.activity.record"):
                                result = apply_architect_result(
                                    {
                                        "project_id": "p1",
                                        "objective": "EKS plus RDS on AWS with terraform",
                                        "assumptions": ["single region"],
                                        "clarifying_qa": [{"q": "Region?", "a": "us-east-1"}],
                                        "hld": "EKS RDS terraform",
                                    },
                                    run_id="run-9",
                                    gated=[{"id": "adr-1", "title": "Use EKS"}],
                                )
    assert result["ok"] is True
    assert result["tasks"] == len(created)
    assert created[0]["depends_on"] == []
    assert created[1]["depends_on"] == [created[0]["id"]]


@pytest.mark.unit
def test_apply_architect_result_chat_does_not_append_tasks():
    from app.platform.engineering.generate import apply_architect_result

    with patch("app.platform.engineering.generate._latest_delivery_run", return_value="del-1"):
        with patch("app.platform.engineering.generate._save_requirement", return_value="req-1"):
            with patch("app.platform.engineering.generate.knowledge.remember"):
                with patch("app.platform.engineering.generate.task_store.create_task") as create_task:
                    with patch("app.platform.engineering.generate._risks_from_text", return_value=[]):
                        with patch("app.platform.engineering.generate.activity.record"):
                            result = apply_architect_result(
                                {
                                    "project_id": "p1",
                                    "source": "chat",
                                    "objective": "EKS plus RDS",
                                    "assumptions": ["single region"],
                                },
                                run_id="run-chat",
                                gated=[{"id": "adr-1", "title": "Use EKS"}],
                            )
    assert result["ok"] is True
    assert result["tasks"] == 0
    create_task.assert_not_called()


@pytest.mark.unit
def test_architect_initial_state_merges_memory_seed():
    from app.agents.solution_architect import graph

    with patch("app.platform.engineering.context.architect_seed", return_value="ENGINEERING MEMORY\n- use postgres"):
        state = graph._initial_state({"objective": "add cache", "project_id": "p1"}, "chat-9")
    assert "postgres" in state["seed_context"]
    assert state["thread_id"] == "chat-9"


@pytest.mark.unit
def test_search_precedent_prefers_knowledge_prompt():
    from app.agents.solution_architect import tools

    with patch(
        "app.platform.engineering.knowledge.architect_context",
        return_value={"prompt": "ENGINEERING MEMORY\n- prior EKS decision"},
    ):
        text = tools.search_precedent("p1")
    assert "EKS" in text


@pytest.mark.unit
def test_generate_missing_for_project_writes_required_files():
    from app.platform.engineering.iac_generate import generate_missing_for_project

    tasks = [
        {
            "id": "t1",
            "title": "Network (VPC/VNet, subnets, routing)",
            "description": "vnet",
            "delivery_run_id": "d1",
            "required_artifacts": [{"name": "network.tf", "kind": "terraform"}],
            "artifacts": [],
        }
    ]
    with patch("app.platform.engineering.tasks.list_tasks", return_value=tasks):
        with patch(
            "app.platform.engineering.artifacts.save_artifact",
            return_value={"validation_status": "passed"},
        ) as save:
            with patch("app.platform.engineering.iac_workspace.sync", return_value={"workspace": "w"}):
                with patch(
                    "app.platform.engineering.iac_generate.load_architecture",
                    return_value={"cloud": "azure"},
                ):
                    out = generate_missing_for_project("p1", actor="admin")
    assert out["count"] == 1
    assert save.call_args.kwargs["name"] == "network.tf"
    assert "azurerm_" in save.call_args.kwargs["content_text"]
