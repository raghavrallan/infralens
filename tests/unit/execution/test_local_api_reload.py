"""Local API reload must ignore generated Terraform workspace Python files."""
from __future__ import annotations

from pathlib import Path

import pytest
from uvicorn.config import Config
from uvicorn.supervisors.watchfilesreload import FileFilter

from scripts.run_local_api import reload_excludes


@pytest.mark.unit
def test_reload_excludes_generated_workspace_python(tmp_path: Path):
    (tmp_path / ".terraform-workspaces").mkdir()
    (tmp_path / "frontend").mkdir()
    smoke = (
        tmp_path
        / ".terraform-workspaces"
        / "proj"
        / "run"
        / "test_smoke.py"
    )
    smoke.parent.mkdir(parents=True)
    smoke.write_text("assert True\n", encoding="utf-8")
    app_file = tmp_path / "app" / "main.py"
    app_file.parent.mkdir()
    app_file.write_text("app = None\n", encoding="utf-8")

    config = Config(
        "app.main:app",
        reload=True,
        reload_dirs=[str(tmp_path / "app")],
        reload_excludes=reload_excludes(tmp_path),
    )
    filt = FileFilter(config)
    assert filt(app_file.resolve()) is True
    assert filt(smoke.resolve()) is False
