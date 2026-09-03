"""Discovery and structured architecture model."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.agents.solution_architect.discovery import discover
from app.agents.solution_architect.model import (
    build_architecture,
    fallback_candidates,
    mermaid_from_discovery,
)
from app.platform.engineering.generate import _select_specs
from app.platform.engineering.iac_generate import generate_artifact_content, load_architecture


def test_discover_selects_aws_when_azure_is_absent():
    found = discover(
        project_id="p1",
        inventory="aws: 2 eks clusters, 1 rds",
        code="terraform aws_vpc",
        objective="Keep the existing EKS platform",
        seed="",
    )
    assert found["cloud"] == "aws"


def test_discover_does_not_treat_always_as_aws():
    found = discover(
        project_id="default",
        inventory="azure: 4 containerapps always available",
        code="",
        objective="Always keep the existing Azure estate",
        seed="",
    )
    assert found["cloud"] == "azure"


def test_discover_infers_saas_stack_from_repo_and_ask():
    found = discover(
        project_id="default",
        inventory="azure: 4 containerapps, 1 postgresql",
        code="requirements.txt fastapi redis frontend/package.json next.js Dockerfile .github/workflows/ci.yml",
        objective="InfraLens FastAPI + Next + Postgres + Redis worker",
        seed="",
    )
    assert found["cloud"] == "azure"
    assert "fastapi" in found["signals"]
    assert "nextjs" in found["signals"]
    assert "postgres" in found["signals"]
    assert "python" in found["languages"]


def test_build_architecture_emits_components_not_queue_stub():
    model = build_architecture(
        {
            "project_id": "default",
            "tier": "T1",
            "mode": "brownfield",
            "objective": "FastAPI Next Postgres Redis ACA private data plane",
            "discovery": {
                "cloud": "azure",
                "signals": ["fastapi", "nextjs", "postgres", "redis", "aca"],
                "languages": ["python", "node"],
                "frameworks": ["fastapi", "nextjs"],
            },
            "mermaid": "flowchart LR\n  api-->db",
            "decisions": [{"title": "Dedicated RG", "decision": "New RG", "gate_decision": "human_approval"}],
        }
    )
    names = [item["name"] for item in model["components"]]
    assert model["cloud"] == "azure"
    assert "Compute platform" in names
    assert "Database and backups" in names
    assert "IAM / identity least privilege" in names
    assert model["analysis"]["security"]
    assert all("queue" not in name.lower() for name in names)


def test_mermaid_follows_discovered_stack():
    diagram = mermaid_from_discovery(
        {
            "objective": "InfraLens FastAPI Next Postgres Redis worker",
            "discovery": {"signals": ["fastapi", "nextjs", "postgres", "redis", "worker"]},
        }
    )
    assert "Next.js" in diagram
    assert "FastAPI" in diagram
    assert "PostgreSQL" in diagram
    assert "queue" not in diagram.lower()


def test_fallback_candidates_are_not_managed_queue():
    items = fallback_candidates({"discovery": {"cloud": "azure"}})
    titles = " ".join(item["title"] for item in items).lower()
    assert "queue" not in titles
    assert "container" in titles or "postgres" in titles


def test_select_specs_prefers_architecture_components():
    architecture = {
        "components": [
            {
                "name": "Compute platform",
                "stage": "infrastructure",
                "artifacts": [{"name": "compute.tf", "kind": "terraform"}],
                "purpose": "ACA",
            }
        ]
    }
    specs = _select_specs("hello", [], architecture=architecture)
    titles = [item["title"] for item in specs]
    assert titles[0] == "Compute platform"
    assert any("documentation" in title.lower() for title in titles)


def test_load_architecture_reads_checkpoint_without_live_tables():
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            return None

        def scalar(self, *_args, **_kwargs):
            return SimpleNamespace(
                checkpoint={"architecture": {"cloud": "azure", "components": [{"name": "VNet"}]}}
            )

    with patch("app.platform.engineering.iac_generate.SessionLocal", return_value=Session()):
        model = load_architecture("p1")
    assert model["cloud"] == "azure"
    assert model["components"][0]["name"] == "VNet"


def test_generate_artifact_content_is_real_azure_hcl():
    with patch("app.platform.engineering.iac_generate.load_architecture", return_value={}):
        providers = generate_artifact_content(
            name="providers.tf", kind="terraform", title="providers", description="", project_id=""
        )
        network = generate_artifact_content(
            name="network.tf", kind="terraform", title="network", description="", project_id=""
        )
    assert "hashicorp/azurerm" in providers
    assert "azurerm_resource_group" in providers
    assert "azurerm_virtual_network" in network
    assert "null_resource" not in network
