"""Run docker compose from a plain copy of the source, for checkouts inside OneDrive.

OneDrive turns synced files into cloud reparse points, and Docker's build context can't read
them ("invalid file request"). Copying to a folder outside OneDrive produces ordinary files.
A checkout outside OneDrive doesn't need this: plain `docker compose` works there.

Usage: python tools/stack.py up -d --wait --build
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = Path(os.environ.get("ORRFIN_BUILD_DIR", Path(os.environ.get("LOCALAPPDATA", Path.home())) / "orrfin-build"))
EXCLUDE = {
    ".git", ".next", ".next-build", ".venv", ".pytest_cache", ".claude", ".mcp.json",
    "node_modules", "__pycache__", "backend", "graphify-out", "test-results", "playwright-report",
}


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in EXCLUDE or name.endswith((".db", ".pyc", ".tsbuildinfo"))}


def sync() -> None:
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    shutil.copytree(ROOT, BUILD_DIR, ignore=_ignore)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    sync()
    return subprocess.call(["docker", "compose", *sys.argv[1:]], cwd=BUILD_DIR)


if __name__ == "__main__":
    sys.exit(main())
