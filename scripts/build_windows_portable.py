"""Build a standalone Windows x64 Portable ZIP distribution for BloomPix."""

from __future__ import annotations

import argparse
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

try:
    import certifi
except ImportError:  # pragma: no cover - optional outside venv
    certifi = None

PYTHON_EMBED_URL = (
    "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

INCLUDE_ROOT_FILES: list[str] = [
    "app.py",
    "BloomPix_Start.bat",
    "README.md",
    "requirements.txt",
]

INCLUDE_SUBDIRS: list[str] = [
    "core",
    "ui",
    "docs",
]

INCLUDE_EXPLICIT_FILES: list[str] = [
    "assets/bloompix.ico",
    "assets/bloompix.png",
    "data/.gitkeep",
    "scripts/auto_update.py",
    "scripts/create_windows_shortcut.vbs",
]

IGNORE_PATTERNS = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "Thumbs.db",
    "~$*",
)


def _download_file(url: str, dest: Path) -> None:
    """Download ``url`` to ``dest`` using ``certifi`` CA bundle when available."""
    ctx = (
        ssl.create_default_context(cafile=certifi.where())
        if certifi is not None
        else ssl.create_default_context()
    )
    req = urllib.request.Request(url, headers={"User-Agent": "BloomPix-Packager/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        with dest.open("wb") as out_fh:
            shutil.copyfileobj(resp, out_fh)


def _enable_embed_site_packages(embed_dir: Path) -> None:
    pth_files = sorted(embed_dir.glob("python*._pth"))
    if not pth_files:
        raise FileNotFoundError(f"No python*._pth file found in {embed_dir}")
    pth_path = pth_files[0]
    lines = pth_path.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    has_site_pkg = False
    has_parent = False
    for line in lines:
        stripped = line.strip()
        if stripped in ("#import site", "import site"):
            updated.append("import site")
            continue
        if stripped == "Lib\\site-packages":
            has_site_pkg = True
        if stripped == "..":
            has_parent = True
        updated.append(line)

    if not has_site_pkg:
        updated.insert(max(len(updated) - 1, 0), "Lib\\site-packages")
    if not has_parent:
        updated.insert(max(len(updated) - 1, 0), "..")
    pth_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def _resolve_head_sha(project_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5.0,
        ).strip()
    except Exception:
        return ""


def _stage_project_files(project_root: Path, stage_dir: Path) -> list[str]:
    copied: list[str] = []
    for rel in INCLUDE_ROOT_FILES + INCLUDE_EXPLICIT_FILES:
        src = project_root / rel
        if not src.exists():
            raise FileNotFoundError(f"Required portable file missing: {src}")
        dst = stage_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)

    for sub in INCLUDE_SUBDIRS:
        src_dir = project_root / sub
        dst_dir = stage_dir / sub
        shutil.copytree(src_dir, dst_dir, ignore=IGNORE_PATTERNS, dirs_exist_ok=True)
        for f in sorted(dst_dir.rglob("*")):
            if f.is_file():
                copied.append(f.relative_to(stage_dir).as_posix())

    head_sha = _resolve_head_sha(project_root)
    if head_sha:
        commit_marker = stage_dir / ".bloompix_commit"
        commit_marker.write_text(f"{head_sha}\n", encoding="utf-8")
        copied.append(".bloompix_commit")
    return sorted(copied)


def _install_windows_dependencies(
    embed_dir: Path,
    requirements_path: Path,
) -> None:
    site_packages = embed_dir / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        with tempfile.TemporaryDirectory() as tmp_dl:
            get_pip = Path(tmp_dl) / "get-pip.py"
            _download_file(GET_PIP_URL, get_pip)
            py_exe = embed_dir / "python.exe"
            subprocess.check_call([str(py_exe), str(get_pip), "--no-warn-script-location"])
            subprocess.check_call(
                [
                    str(py_exe),
                    "-m",
                    "pip",
                    "install",
                    "--no-warn-script-location",
                    "-r",
                    str(requirements_path),
                ]
            )
    else:
        # Cross-platform installation of Windows x64 wheels from macOS/Linux
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--platform",
                "win_amd64",
                "--python-version",
                "3.11",
                "--implementation",
                "cp",
                "--abi",
                "cp311",
                "--only-binary=:all:",
                "--upgrade",
                "--target",
                str(site_packages),
                "-r",
                str(requirements_path),
            ]
        )


def build_windows_portable(
    project_root: Path,
    output_zip: Path,
    python_url: str = PYTHON_EMBED_URL,
    dry_run: bool = False,
) -> Path:
    """Assemble ``BloomPix_Windows_Portable.zip`` with embedded Python 3.11 x64."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        stage_dir = tmp_path / "BloomPix_Portable"
        stage_dir.mkdir(parents=True, exist_ok=True)

        staged_files = _stage_project_files(project_root, stage_dir)
        if dry_run:
            print(f"[DRY RUN] Verified {len(staged_files)} project files ready for portable ZIP.")
            return output_zip

        embed_zip = tmp_path / "python_embed.zip"
        print(f"Downloading Python 3.11 x64 embeddable runtime from {python_url}...")
        _download_file(python_url, embed_zip)

        embed_dir = stage_dir / "python_embed"
        embed_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(embed_zip, "r") as zf:
            zf.extractall(embed_dir)

        _enable_embed_site_packages(embed_dir)
        print("Installing Windows x64 wheel dependencies into python_embed/Lib/site-packages...")
        _install_windows_dependencies(embed_dir, project_root / "requirements.txt")

        output_zip.parent.mkdir(parents=True, exist_ok=True)
        print(f"Packaging {output_zip}...")
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as out_zf:
            for path in sorted(stage_dir.rglob("*")):
                if path.is_file():
                    arcname = path.relative_to(tmp_path).as_posix()
                    out_zf.write(path, arcname=arcname)

    size_mb = output_zip.stat().st_size / (1024.0 * 1024.0)
    print(f"Built {output_zip} ({size_mb:.2f} MB)")
    return output_zip


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a standalone Windows x64 Portable ZIP for BloomPix."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/BloomPix_Windows_Portable.zip"),
        help="Output ZIP path.",
    )
    parser.add_argument(
        "--python-url",
        type=str,
        default=PYTHON_EMBED_URL,
        help="Official Python Windows x64 embeddable ZIP URL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate staged project files without downloading Python or building the ZIP.",
    )
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parent.parent
    out_path = args.output if args.output.is_absolute() else project_root / args.output
    build_windows_portable(
        project_root=project_root,
        output_zip=out_path,
        python_url=args.python_url,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
