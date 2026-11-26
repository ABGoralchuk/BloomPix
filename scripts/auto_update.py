"""Zero-dependency GitHub auto-updater for standalone Windows Portable BloomPix installations.

Checks the remote GitHub branch tip commit using Python standard library modules only and applies
application code/asset updates while strictly preserving user data and bundled Python runtimes.
"""

from __future__ import annotations

import argparse
import json
import shutil
import ssl
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

UPDATE_FILES: tuple[str, ...] = (
    "app.py",
    "requirements.txt",
    "README.md",
    "BloomPix_Start.bat",
)

UPDATE_DIRS: tuple[str, ...] = (
    "core",
    "ui",
    "docs",
    "assets",
    "scripts",
)

IGNORE_DIRS = {"__pycache__", ".pytest_cache"}


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _fetch_remote_sha(repo: str, branch: str, timeout: float) -> str:
    url = f"https://api.github.com/repos/{repo}/commits/{branch}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "BloomPix-AutoUpdater/1.1",
        },
    )
    with urllib.request.urlopen(req, context=_ssl_context(), timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    sha = str(payload.get("sha", "")).strip()
    if not sha:
        raise ValueError("Empty SHA returned by GitHub API")
    return sha


def _download_archive(repo: str, branch: str, dest: Path, timeout: float = 25.0) -> None:
    url = f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BloomPix-AutoUpdater/1.1"},
    )
    with urllib.request.urlopen(req, context=_ssl_context(), timeout=timeout) as resp:
        with dest.open("wb") as out_fh:
            shutil.copyfileobj(resp, out_fh)


def _safe_extract_zip(zip_path: Path, extract_root: Path) -> Path:
    root_resolved = extract_root.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            target = (extract_root / member.filename).resolve()
            if not target.is_relative_to(root_resolved):
                raise ValueError(f"Unsafe ZIP member path: {member.filename}")
        zf.extractall(extract_root)

    top_dirs = [p for p in extract_root.iterdir() if p.is_dir()]
    if len(top_dirs) == 1:
        return top_dirs[0]
    return extract_root


def _copy_if_changed(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and src.read_bytes() == dst.read_bytes():
        return
    shutil.copy2(src, dst)


def _apply_extracted_update(src_root: Path, app_root: Path) -> None:
    for rel_file in UPDATE_FILES:
        _copy_if_changed(src_root / rel_file, app_root / rel_file)

    for rel_dir in UPDATE_DIRS:
        src_dir = src_root / rel_dir
        if not src_dir.is_dir():
            continue
        dst_dir = app_root / rel_dir
        shutil.copytree(
            src_dir,
            dst_dir,
            ignore=shutil.ignore_patterns(*IGNORE_DIRS, "*.pyc", "*.pyo"),
            dirs_exist_ok=True,
        )


def run_auto_update(
    repo: str = "ABGoralchuk/BloomPix",
    branch: str = "main",
    app_root: Optional[Path] = None,
    timeout: float = 4.0,
) -> int:
    """Check GitHub for newer commits and update app files safely without touching user data."""
    root = (app_root or Path(__file__).resolve().parent.parent).resolve()
    commit_file = root / ".bloompix_commit"
    local_sha = commit_file.read_text(encoding="utf-8").strip() if commit_file.exists() else ""

    try:
        remote_sha = _fetch_remote_sha(repo=repo, branch=branch, timeout=timeout)
    except Exception:
        print("[BloomPix] Update check skipped (offline or GitHub unavailable).")
        return 0

    if local_sha and local_sha == remote_sha:
        print(f"BloomPix is up to date ({remote_sha[:7]}).")
        return 0

    try:
        print(f"[BloomPix] Downloading update ({remote_sha[:7]}) from GitHub...")
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            zip_file = tmp_path / "update.zip"
            extract_dir = tmp_path / "extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)
            _download_archive(repo=repo, branch=branch, dest=zip_file, timeout=max(25.0, timeout))
            src_root = _safe_extract_zip(zip_file, extract_dir)
            _apply_extracted_update(src_root, root)

        commit_file.write_text(f"{remote_sha}\n", encoding="utf-8")
        print(f"Updated BloomPix to {remote_sha[:7]}.")
    except Exception as exc:
        print(f"[BloomPix] Update skipped ({exc}).")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Auto-update BloomPix Portable from GitHub without overwriting data or Python runtime."
    )
    parser.add_argument("--repo", default="ABGoralchuk/BloomPix", help="GitHub owner/repo")
    parser.add_argument("--branch", default="main", help="GitHub branch name")
    parser.add_argument("--timeout", type=float, default=4.0, help="API check timeout in seconds")
    args = parser.parse_args(argv)
    return run_auto_update(repo=args.repo, branch=args.branch, timeout=args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
