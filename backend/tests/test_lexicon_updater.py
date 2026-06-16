"""Tests for LexiconUpdater: metadata, security, validation, and atomic replace."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.lexicon_updater import (
    LexiconUpdateMeta,
    LexiconUpdateResult,
    LexiconUpdater,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_zip(entries: dict[str, str]) -> bytes:
    """Create an in-memory zip containing *entries* as {archive_path: content}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def updater_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create a minimal environment for LexiconUpdater tests."""
    backend_root = tmp_path / "backend"
    lexicon_dir = backend_root / "data" / "lexicons"
    lexicon_dir.mkdir(parents=True)

    monkeypatch.setattr("app.config.BACKEND_ROOT", backend_root)

    updater = LexiconUpdater(lexicon_dir=lexicon_dir)

    return type("Env", (), {
        "updater": updater,
        "lexicon_dir": lexicon_dir,
        "target": lexicon_dir / "Sensitive-lexicon",
        "meta_path": lexicon_dir / "lexicon_meta.json",
        "backend_root": backend_root,
    })()


# ── LexiconUpdateMeta ────────────────────────────────────────────────────────


def test_meta_to_dict_roundtrip():
    meta = LexiconUpdateMeta(
        source_repo="https://github.com/example/repo",
        branch="dev",
        commit_sha="abc123",
        updated_at="2026-01-01T00:00:00+00:00",
        file_count=5,
        word_count=1000,
        last_error="",
    )
    d = meta.to_dict()
    restored = LexiconUpdateMeta.from_dict(d)
    assert restored.source_repo == meta.source_repo
    assert restored.branch == meta.branch
    assert restored.commit_sha == meta.commit_sha
    assert restored.file_count == meta.file_count
    assert restored.word_count == meta.word_count


def test_meta_from_dict_handles_missing_fields():
    meta = LexiconUpdateMeta.from_dict({})
    assert meta.source_repo != ""
    assert meta.branch != ""
    assert meta.file_count == 0


# ── load / save meta ─────────────────────────────────────────────────────────


def test_load_meta_returns_blank_when_no_file(updater_env):
    meta = updater_env.updater.load_meta()
    assert meta.last_error == ""
    assert meta.word_count == 0


def test_save_then_load_meta(updater_env):
    meta = LexiconUpdateMeta(
        commit_sha="deadbeef",
        updated_at="2026-06-15T00:00:00+00:00",
        file_count=3,
        word_count=500,
    )
    updater_env.updater._save_meta(meta)

    loaded = updater_env.updater.load_meta()
    assert loaded.commit_sha == "deadbeef"
    assert loaded.file_count == 3
    assert loaded.word_count == 500
    assert updater_env.meta_path.exists()


# ── _is_safe_zip_path ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path,expected",
    [
        ("words.txt", True),
        ("sub/words.txt", True),
        ("sub/deep/words.txt", True),
        ("../evil.txt", False),
        ("sub/../../evil.txt", False),
        ("/etc/passwd", False),
        ("C:/Windows/System32/config", False),
        ("\\server\\share\\file", False),
        ("sub/..\\evil.txt", False),
        ("good/path/../../../bad", False),
    ],
    ids=[
        "simple_file",
        "subdir_file",
        "deep_subdir",
        "parent_traversal",
        "nested_traversal",
        "absolute_unix",
        "absolute_windows",
        "unc_path",
        "backslash_traversal",
        "deep_traversal",
    ],
)
def test_is_safe_zip_path(path, expected):
    assert LexiconUpdater._is_safe_zip_path(path) is expected


# ── _is_skipped_doc_file ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path,expected",
    [
        ("README.md", True),
        ("readme.md", True),
        ("README", True),
        ("LICENSE", True),
        ("LICENSE.md", True),
        ("CHANGELOG.md", True),
        (".gitignore", True),
        ("docs/architecture.md", True),
        ("doc/intro.md", True),
        (".github/workflows/ci.yml", True),
        ("words.txt", False),
        ("blocked.txt", False),
        ("sub/words.txt", False),
        ("lexicon_data.csv", False),
    ],
    ids=[
        "readme_upper",
        "readme_lower",
        "readme_no_ext",
        "license",
        "license_md",
        "changelog",
        "gitignore",
        "docs_dir",
        "doc_dir",
        "github_dir",
        "words_txt",
        "blocked_txt",
        "subdir_words",
        "csv_data",
    ],
)
def test_is_skipped_doc_file(path, expected):
    assert LexiconUpdater._is_skipped_doc_file(path) is expected


# ── _extract_zip: path traversal ─────────────────────────────────────────────


def test_extract_zip_rejects_parent_traversal(tmp_path):
    """A zip containing '../evil.txt' must raise ValueError, not write outside target_dir."""
    zip_bytes = _make_zip({
        "repo-main/blocked.txt": "正常内容\n",
        "repo-main/../evil.txt": "MALICIOUS",
    })

    outside_file = tmp_path / "evil.txt"
    target_dir = tmp_path / "extract"
    target_dir.mkdir()

    import zipfile as zf_mod

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        with pytest.raises(ValueError, match="Unsafe zip path"):
            LexiconUpdater._extract_zip(zf, target_dir)

    assert not outside_file.exists(), "Traversal file must NOT be created outside target_dir"


def test_extract_zip_rejects_absolute_path(tmp_path):
    """A zip entry with an absolute path must raise ValueError."""
    zip_bytes = _make_zip({
        "repo-main/words.txt": "正常\n",
        "/etc/passwd": "MALICIOUS",
    })

    target_dir = tmp_path / "extract"
    target_dir.mkdir()

    import zipfile as zf_mod

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        with pytest.raises(ValueError, match="Unsafe zip path"):
            LexiconUpdater._extract_zip(zf, target_dir)


def test_extract_zip_rejects_windows_drive_path(tmp_path):
    """A zip entry with a Windows drive letter path must raise ValueError."""
    zip_bytes = _make_zip({
        "repo-main/words.txt": "正常\n",
        "C:/Windows/evil.txt": "MALICIOUS",
    })

    target_dir = tmp_path / "extract"
    target_dir.mkdir()

    import zipfile as zf_mod

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        with pytest.raises(ValueError, match="Unsafe zip path"):
            LexiconUpdater._extract_zip(zf, target_dir)


def test_extract_zip_normal_files_succeed(tmp_path):
    """A clean zip with normal lexicon files should extract without errors."""
    zip_bytes = _make_zip({
        "repo-main/blocked.txt": "血腥\n暴力\n",
        "repo-main/sub/extra.txt": "恐怖\n",
    })

    target_dir = tmp_path / "extract"
    target_dir.mkdir()

    import zipfile as zf_mod

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        LexiconUpdater._extract_zip(zf, target_dir)

    assert (target_dir / "blocked.txt").read_text(encoding="utf-8") == "血腥\n暴力\n"
    assert (target_dir / "sub" / "extra.txt").read_text(encoding="utf-8") == "恐怖\n"


def test_extract_zip_skips_readme_and_docs(tmp_path):
    """README.md, LICENSE, docs/ files should be skipped; only lexicon files remain."""
    zip_bytes = _make_zip({
        "repo-main/words.txt": "血腥\n暴力\n",
        "repo-main/README.md": "# This is a readme\n",
        "repo-main/LICENSE": "MIT License\n",
        "repo-main/docs/architecture.md": "# Architecture\n",
        "repo-main/.github/workflows/ci.yml": "name: CI\n",
    })

    target_dir = tmp_path / "extract"
    target_dir.mkdir()

    import zipfile as zf_mod

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        LexiconUpdater._extract_zip(zf, target_dir)

    # Lexicon file should exist.
    assert (target_dir / "words.txt").exists()
    assert (target_dir / "words.txt").read_text(encoding="utf-8") == "血腥\n暴力\n"

    # Doc files must NOT be extracted.
    assert not (target_dir / "README.md").exists()
    assert not (target_dir / "LICENSE").exists()
    assert not (target_dir / "docs").exists()
    assert not (target_dir / ".github").exists()


def test_extract_zip_empty_after_filtering_raises(tmp_path):
    """If all files in the zip are docs, extraction should raise ValueError."""
    zip_bytes = _make_zip({
        "repo-main/README.md": "# Readme\n",
        "repo-main/LICENSE": "MIT\n",
    })

    target_dir = tmp_path / "extract"
    target_dir.mkdir()

    import zipfile as zf_mod

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        with pytest.raises(ValueError, match="no usable lexicon files"):
            LexiconUpdater._extract_zip(zf, target_dir)


# ── check_and_update: malicious zip end-to-end ──────────────────────────────


def test_malicious_zip_preserves_old_lexicon(updater_env):
    """When the downloaded zip contains path traversal, check_and_update must fail
    and preserve the pre-existing lexicon."""
    # Pre-populate old lexicon.
    updater_env.target.mkdir(parents=True)
    (updater_env.target / "old.txt").write_text("旧词库内容\n", encoding="utf-8")

    malicious_zip = _make_zip({
        "repo-main/good.txt": "正常\n",
        "repo-main/../../../evil.txt": "MALICIOUS\n",
    })

    def fake_download(target_dir: Path) -> str:
        import zipfile as zf_mod

        with zipfile.ZipFile(io.BytesIO(malicious_zip)) as zf:
            LexiconUpdater._extract_zip(zf, target_dir)
        return "bad_sha"

    with patch.object(LexiconUpdater, "_download_lexicon", side_effect=fake_download):
        result = updater_env.updater.check_and_update()

    assert result.success is False
    assert "Download failed" in result.error
    assert "Unsafe zip path" in result.error

    # Old lexicon must be intact.
    assert updater_env.target.exists()
    assert (updater_env.target / "old.txt").read_text(encoding="utf-8") == "旧词库内容\n"


# ── check_and_update: normal zip success ─────────────────────────────────────


def test_check_and_update_with_normal_zip_succeeds(updater_env):
    """A normal zip with lexicon files should succeed and update the target."""
    normal_zip = _make_zip({
        "repo-main/blocked.txt": "血腥\n暴力\n杀意\n",
        "repo-main/extra.txt": "恐怖\n",
        "repo-main/README.md": "# Sensitive Lexicon\nThis is a readme.\n",
    })

    def fake_download(target_dir: Path) -> str:
        import zipfile as zf_mod

        with zipfile.ZipFile(io.BytesIO(normal_zip)) as zf:
            LexiconUpdater._extract_zip(zf, target_dir)
        return "good_sha"

    with patch.object(LexiconUpdater, "_download_lexicon", side_effect=fake_download):
        result = updater_env.updater.check_and_update()

    assert result.success is True
    assert result.word_count >= 4
    assert result.file_count == 2  # README.md excluded
    assert result.commit_sha == "good_sha"

    # Target should contain only lexicon files, not README.
    assert updater_env.target.exists()
    assert (updater_env.target / "blocked.txt").exists()
    assert (updater_env.target / "extra.txt").exists()
    assert not (updater_env.target / "README.md").exists()

    meta = updater_env.updater.load_meta()
    assert meta.last_error == ""
    assert meta.word_count >= 4


# ── check_and_update failure modes ───────────────────────────────────────────


def test_check_and_update_returns_error_on_download_failure(updater_env):
    with patch.object(LexiconUpdater, "_download_lexicon", side_effect=RuntimeError("network down")):
        result = updater_env.updater.check_and_update()

    assert result.success is False
    assert "Download failed" in result.error
    assert "network down" in result.error

    meta = updater_env.updater.load_meta()
    assert meta.last_error != ""
    assert "Download failed" in meta.last_error


def test_check_and_update_returns_error_on_validation_failure(updater_env):
    def fake_download(target_dir: Path) -> str:
        (target_dir / "empty.txt").write_text("# nothing here\n", encoding="utf-8")
        return "fake_sha"

    with patch.object(LexiconUpdater, "_download_lexicon", side_effect=fake_download):
        result = updater_env.updater.check_and_update()

    assert result.success is False
    assert "Validation failed" in result.error

    meta = updater_env.updater.load_meta()
    assert "Validation failed" in meta.last_error


def test_check_and_update_preserves_old_lexicon_on_failure(updater_env):
    updater_env.target.mkdir(parents=True)
    (updater_env.target / "old.txt").write_text("旧词库内容\n", encoding="utf-8")

    with patch.object(LexiconUpdater, "_download_lexicon", side_effect=RuntimeError("boom")):
        result = updater_env.updater.check_and_update()

    assert result.success is False
    assert updater_env.target.exists()
    assert (updater_env.target / "old.txt").read_text(encoding="utf-8") == "旧词库内容\n"


# ── atomic replace rollback ──────────────────────────────────────────────────


def test_atomic_replace_rollback_preserves_old_lexicon(updater_env):
    """When tmp_dir.rename() fails, old lexicon must survive via rollback."""
    # Pre-populate old lexicon.
    updater_env.target.mkdir(parents=True)
    (updater_env.target / "old.txt").write_text("旧词库\n", encoding="utf-8")

    def fake_download(target_dir: Path) -> str:
        (target_dir / "new.txt").write_text("新词库\n", encoding="utf-8")
        return "rollback_sha"

    # Make rename fail after backup is created.
    original_rename = Path.rename

    def failing_rename(self, target):
        # Allow the backup rename to succeed, but fail on tmp_dir → target.
        if "new.txt" in str(self) or "lexicon_dl_" in str(self):
            raise OSError("Simulated rename failure")
        return original_rename(self, target)

    with (
        patch.object(LexiconUpdater, "_download_lexicon", side_effect=fake_download),
        patch.object(Path, "rename", failing_rename),
    ):
        result = updater_env.updater.check_and_update()

    assert result.success is False
    assert "Atomic replace failed" in result.error

    # Old lexicon must still be intact (rollback restored it).
    assert updater_env.target.exists()
    assert (updater_env.target / "old.txt").read_text(encoding="utf-8") == "旧词库\n"


def test_check_and_update_replaces_lexicon_atomically(updater_env):
    """A successful update should replace the lexicon dir and write correct meta."""
    def fake_download(target_dir: Path) -> str:
        (target_dir / "blocked.txt").write_text("血腥\n暴力\n杀意\n死亡\n", encoding="utf-8")
        (target_dir / "extra.txt").write_text("恐怖\n", encoding="utf-8")
        return "abc123sha"

    with patch.object(LexiconUpdater, "_download_lexicon", side_effect=fake_download):
        result = updater_env.updater.check_and_update()

    assert result.success is True
    assert result.word_count >= 4
    assert result.file_count == 2
    assert result.commit_sha == "abc123sha"

    assert updater_env.target.exists()
    assert (updater_env.target / "blocked.txt").exists()
    assert (updater_env.target / "extra.txt").exists()

    meta = updater_env.updater.load_meta()
    assert meta.commit_sha == "abc123sha"
    assert meta.word_count >= 4
    assert meta.last_error == ""


# ── temp dir cleanup ─────────────────────────────────────────────────────────


def test_check_and_update_cleans_up_temp_dir(updater_env):
    import tempfile

    def fake_download(target_dir: Path) -> str:
        (target_dir / "words.txt").write_text("测试\n", encoding="utf-8")
        return "sha_temp"

    before_tmp = set(Path(tempfile.gettempdir()).iterdir())

    with patch.object(LexiconUpdater, "_download_lexicon", side_effect=fake_download):
        updater_env.updater.check_and_update()

    after_tmp = set(Path(tempfile.gettempdir()).iterdir())
    new_entries = after_tmp - before_tmp
    lexicon_tmp = [e for e in new_entries if e.name.startswith("lexicon_dl_")]
    assert len(lexicon_tmp) == 0, f"Temp lexicon dirs not cleaned up: {lexicon_tmp}"


# ── default lexicon_dir ──────────────────────────────────────────────────────


def test_default_lexicon_dir_uses_resolver(tmp_path, monkeypatch):
    backend_root = tmp_path / "backend"
    lex_dir = backend_root / "data" / "lexicons"
    lex_dir.mkdir(parents=True)
    monkeypatch.setattr("app.config.BACKEND_ROOT", backend_root)

    updater = LexiconUpdater()
    assert updater.lexicon_dir == lex_dir
    assert updater.lexicon_target == lex_dir / "Sensitive-lexicon"
