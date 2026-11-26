"""Version and build metadata utilities for BloomPix."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

APP_NAME = "BloomPix"
APP_VERSION = "1.1.0"
FALLBACK_DATE = "2026-11-26"


def get_git_info(repo_dir: Optional[Path] = None) -> tuple[str, str]:
    """Return ``(short_commit_hash, commit_date)`` with a safe offline fallback."""
    root = Path(repo_dir or Path(__file__).resolve().parent.parent)
    cwd = str(root)
    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
        ).strip()
        commit_date = subprocess.check_output(
            ["git", "show", "-s", "--format=%cs", "HEAD"],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
        ).strip()
        if commit_hash:
            return commit_hash, commit_date or FALLBACK_DATE
    except Exception:
        pass
    commit_marker = root / ".bloompix_commit"
    if commit_marker.exists():
        sha = commit_marker.read_text(encoding="utf-8").strip()
        if sha:
            return sha[:7], FALLBACK_DATE
    return "local", FALLBACK_DATE


def get_build_label(repo_dir: Optional[Path] = None) -> str:
    """Format a compact human-readable build string for UI headers and exports."""
    commit_hash, commit_date = get_git_info(repo_dir=repo_dir)
    if commit_hash == "local":
        return f"v{APP_VERSION} ({commit_hash}, {commit_date})"
    return f"v{APP_VERSION} ({commit_hash}, {commit_date})"
