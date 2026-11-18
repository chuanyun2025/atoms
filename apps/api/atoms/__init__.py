"""Atoms Studio backend package."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[2]
SHARED_ROOT = REPO_ROOT / "shared"
