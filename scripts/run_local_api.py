"""Local uvicorn that ignores generated trees so IaC writes cannot bounce the API.

Uvicorn 0.34 always watches the process cwd for `*.py`. Isolated workspaces
write `test_smoke.py`, which retriggers reload unless that directory is
excluded by absolute path. This launcher also pins cwd/sys.path to the repo
root so the WatchFiles child can still `import app`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ["PYTHONPATH"] = str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")

import uvicorn

_IGNORE = (
    ".terraform-workspaces",
    "frontend",
    ".venv",
    ".pytest_cache",
    ".local-run",
)


def reload_excludes(root: Path | None = None) -> list[str]:
    base = root or ROOT
    return [str((base / name).resolve()) for name in _IGNORE if (base / name).exists()]


def main() -> None:
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT", "8000"))
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True,
        reload_dirs=[str(ROOT / "app")],
        reload_excludes=reload_excludes(),
    )


if __name__ == "__main__":
    main()
