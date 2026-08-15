"""Project context engine with disconnected providers."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.chat.project_context import (
    ProjectContext,
    build_existing_context,
    build_fresh_context,
    build_project_context,
    detect_project_mode,
    gather_project_topology,
)


@pytest.mark.unit
def test_detect_mode_fresh_when_no_repos_or_cloud():
    with patch("app.chat.project_context.projects.get_repos", return_value=[]):
        with patch("app.chat.project_context.github_infra.is_connected", return_value=False):
            with patch("app.chat.project_context.azure_infra.is_connected", return_value=False):
                with patch("app.chat.project_context.aws_infra.is_connected", return_value=False):
                    assert detect_project_mode("p1") == "fresh"


@pytest.mark.unit
def test_build_fresh_and_existing_context():
    project = {"id": "p1", "name": "Demo", "repos": ["acme/app"]}
    with patch("app.chat.project_context.projects.get_project", return_value=project):
        with patch("app.chat.project_context.projects.get_repos", return_value=["acme/app"]):
            with patch(
                "app.chat.project_context.connections.all_status",
                return_value=[
                    {"provider": "azure", "connected": False},
                    {"provider": "aws", "connected": False},
                    {"provider": "github", "connected": True},
                ],
            ):
                with patch("app.chat.project_context.github_infra.is_connected", return_value=True):
                    with patch("app.chat.project_context.azure_infra.is_connected", return_value=False):
                        with patch("app.chat.project_context.aws_infra.is_connected", return_value=False):
                            with patch(
                                "app.chat.project_context._extract_iac_inventory",
                                return_value=[{"path": "main.tf", "kind": "terraform"}],
                            ):
                                with patch(
                                    "app.chat.project_context._live_resource_summary",
                                    return_value={},
                                ):
                                    ctx = build_fresh_context("p1", requirements=["need api"])
                                    assert isinstance(ctx, ProjectContext)
                                    existing = build_existing_context("p1")
                                    assert existing.mode == "existing"
                                    combined = build_project_context("p1", user_messages=["hello"])
                                    assert combined.project_id == "p1"
                                    text = gather_project_topology("p1", user_messages=["hello"])
                                    assert isinstance(text, str)
