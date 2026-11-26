"""Offline unit tests for scripts/auto_update.py."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from scripts import auto_update


def _make_remote_repo_zip(tmp_zip_parent: Path, commit_sha: str, app_content: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("BloomPix-main/app.py", app_content)
        zf.writestr("BloomPix-main/core/version.py", f'APP_VERSION = "1.1.0"\nSHA = "{commit_sha}"\n')
        zf.writestr("BloomPix-main/ui/tab_dsc.py", "# updated ui\n")
        zf.writestr("BloomPix-main/docs/SOP.docx", b"new-sop-bytes")
        zf.writestr("BloomPix-main/assets/bloompix.ico", b"ico-bytes")
        zf.writestr("BloomPix-main/scripts/auto_update.py", "# updater\n")
        zf.writestr("BloomPix-main/data/.gitkeep", "")
    return buf.getvalue()


def test_auto_update_offline_graceful(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        auto_update,
        "_fetch_remote_sha",
        lambda repo, branch, timeout: (_ for _ in ()).throw(TimeoutError("network timeout")),
    )
    code = auto_update.run_auto_update(app_root=tmp_path)
    assert code == 0
    assert "Update check skipped" in capsys.readouterr().out


def test_auto_update_up_to_date(monkeypatch, tmp_path: Path, capsys) -> None:
    sha = "abcdef1234567890"
    (tmp_path / ".bloompix_commit").write_text(f"{sha}\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("# current\n", encoding="utf-8")

    monkeypatch.setattr(auto_update, "_fetch_remote_sha", lambda repo, branch, timeout: sha)
    called = {"dl": False}

    def _fail_dl(*args, **kwargs):
        called["dl"] = True

    monkeypatch.setattr(auto_update, "_download_archive", _fail_dl)
    code = auto_update.run_auto_update(app_root=tmp_path)
    assert code == 0
    assert not called["dl"]
    assert "up to date" in capsys.readouterr().out


def test_auto_update_preserves_user_data_and_python_embed(monkeypatch, tmp_path: Path, capsys) -> None:
    old_sha = "1111111111111111"
    new_sha = "2222222222222222"
    (tmp_path / ".bloompix_commit").write_text(f"{old_sha}\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("# old app\n", encoding="utf-8")
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "version.py").write_text('APP_VERSION = "1.0.0"\n', encoding="utf-8")

    # Protected user directories that must NEVER be overwritten or deleted
    (tmp_path / "data" / "1").mkdir(parents=True)
    (tmp_path / "data" / "1" / "ANFW1_50um.tif").write_bytes(b"RAW-TIF")
    (tmp_path / "data" / "metadata_override.csv").write_text("custom,override\n", encoding="utf-8")
    (tmp_path / "DSC").mkdir()
    (tmp_path / "DSC" / "anfw1r1.txt").write_text("dsc-data", encoding="utf-8")
    (tmp_path / "python_embed").mkdir()
    (tmp_path / "python_embed" / "python.exe").write_bytes(b"PY-EXE")

    zip_bytes = _make_remote_repo_zip(tmp_path, new_sha, "# updated v1.1.0 app\n")
    monkeypatch.setattr(auto_update, "_fetch_remote_sha", lambda repo, branch, timeout: new_sha)

    def _fake_download(repo: str, branch: str, dest: Path, timeout: float = 25.0) -> None:
        dest.write_bytes(zip_bytes)

    monkeypatch.setattr(auto_update, "_download_archive", _fake_download)

    code = auto_update.run_auto_update(app_root=tmp_path)
    assert code == 0
    assert (tmp_path / ".bloompix_commit").read_text(encoding="utf-8").strip() == new_sha
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "# updated v1.1.0 app\n"
    assert (tmp_path / "ui" / "tab_dsc.py").exists()

    # Protected paths strictly intact
    assert (tmp_path / "data" / "1" / "ANFW1_50um.tif").read_bytes() == b"RAW-TIF"
    assert (tmp_path / "data" / "metadata_override.csv").read_text(encoding="utf-8") == "custom,override\n"
    assert (tmp_path / "DSC" / "anfw1r1.txt").read_text(encoding="utf-8") == "dsc-data"
    assert (tmp_path / "python_embed" / "python.exe").read_bytes() == b"PY-EXE"
    assert "Updated BloomPix to 2222222." in capsys.readouterr().out
