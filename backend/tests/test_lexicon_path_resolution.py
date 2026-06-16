"""Tests for resolve_sensitive_lexicon_path and DEFAULT_LEXICON_PATH consistency.

Validates that the sensitive lexicon path resolves correctly regardless of
whether the runtime CWD is the repo root or ``backend/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.aggregate_settings import (
    DEFAULT_CONTENT_WORKFLOW,
    DEFAULT_LEXICON_PATH,
    _LEGACY_LEXICON_PATH,
    resolve_sensitive_lexicon_path,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def lexicon_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create a fake project tree with a populated lexicon directory.

    Structure::

        tmp_path/                          ← repo root
        ├── backend/
        │   └── data/
        │       └── lexicons/
        │           └── Sensitive-lexicon/
        │               └── words.txt
        └── ...

    Monkeypatches ``app.config.BACKEND_ROOT`` so the resolver uses this tree.
    """
    repo_root = tmp_path
    backend_root = repo_root / "backend"
    lex_dir = backend_root / "data" / "lexicons" / "Sensitive-lexicon"
    lex_dir.mkdir(parents=True)
    (lex_dir / "words.txt").write_text("血腥\n暴力\n杀戮\n", encoding="utf-8")

    monkeypatch.setattr("app.config.BACKEND_ROOT", backend_root)
    monkeypatch.setattr("app.config.PROJECT_ROOT", repo_root)

    return type("Tree", (), {
        "repo_root": repo_root,
        "backend_root": backend_root,
        "lex_dir": lex_dir,
        "words_file": lex_dir / "words.txt",
    })()


# ── path resolution tests ────────────────────────────────────────────────────


def test_absolute_path_returned_as_is(lexicon_tree):
    """An absolute path should be returned directly, no resolution."""
    abs_path = Path("C:/some/absolute/path")
    result = resolve_sensitive_lexicon_path(abs_path)
    assert result == abs_path


def test_default_path_is_relative(lexicon_tree):
    """DEFAULT_LEXICON_PATH must be a relative path without 'backend/' prefix."""
    assert not Path(DEFAULT_LEXICON_PATH).is_absolute()
    assert not DEFAULT_LEXICON_PATH.startswith("backend/")


def test_legacy_path_contains_backend_prefix(lexicon_tree):
    """The legacy constant should still carry 'backend/' for backward compat."""
    assert _LEGACY_LEXICON_PATH.startswith("backend/")


def test_new_default_resolves_from_backend_cwd(lexicon_tree, monkeypatch):
    """With CWD=backend/ and new default 'data/lexicons/Sensitive-lexicon',
    the CWD-relative path should resolve directly."""
    backend_cwd = lexicon_tree.backend_root
    monkeypatch.chdir(backend_cwd)

    result = resolve_sensitive_lexicon_path(DEFAULT_LEXICON_PATH)
    assert result.exists()
    assert result == lexicon_tree.lex_dir


def test_legacy_path_resolves_from_repo_root_cwd(lexicon_tree, monkeypatch):
    """With CWD=repo_root and old default 'backend/data/lexicons/Sensitive-lexicon',
    the CWD-relative path should resolve correctly."""
    monkeypatch.chdir(lexicon_tree.repo_root)

    result = resolve_sensitive_lexicon_path(_LEGACY_LEXICON_PATH)
    assert result.exists()
    assert result == lexicon_tree.lex_dir


def test_legacy_path_does_not_double_backend_from_backend_cwd(lexicon_tree, monkeypatch):
    """With CWD=backend/ and legacy path 'backend/data/lexicons/...',
    must NOT resolve to backend/backend/data/..."""
    monkeypatch.chdir(lexicon_tree.backend_root)

    result = resolve_sensitive_lexicon_path(_LEGACY_LEXICON_PATH)
    # Should resolve to backend/data/lexicons/Sensitive-lexicon, not backend/backend/...
    assert "backend" not in result.name
    assert str(result).count("backend") <= str(lexicon_tree.backend_root).count("backend") + 1
    assert result.exists()


def test_none_path_uses_default(lexicon_tree):
    """When raw_path is None, should use DEFAULT_LEXICON_PATH resolved against BACKEND_ROOT."""
    result = resolve_sensitive_lexicon_path(None)
    assert result.exists()
    assert result == lexicon_tree.lex_dir


def test_new_default_from_repo_root_falls_back_to_backend_root(lexicon_tree, monkeypatch):
    """With CWD=repo_root and new default 'data/lexicons/...',
    the CWD-relative path doesn't exist, so it should fall back to BACKEND_ROOT."""
    monkeypatch.chdir(lexicon_tree.repo_root)

    result = resolve_sensitive_lexicon_path(DEFAULT_LEXICON_PATH)
    assert result.exists()
    assert result == lexicon_tree.lex_dir


def test_nonexistent_path_still_returns_absolute(lexicon_tree):
    """A path that doesn't exist should still return an absolute Path (for logging)."""
    result = resolve_sensitive_lexicon_path("data/lexicons/nonexistent_dir")
    assert result.is_absolute()


# ── default value consistency ────────────────────────────────────────────────


def test_default_workflow_uses_new_lexicon_path():
    """DEFAULT_CONTENT_WORKFLOW.sensitiveLexiconPath must equal DEFAULT_LEXICON_PATH."""
    assert DEFAULT_CONTENT_WORKFLOW["sensitiveLexiconPath"] == DEFAULT_LEXICON_PATH
