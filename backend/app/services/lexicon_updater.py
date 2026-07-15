"""Lexicon updater: download and atomically replace the local sensitive-word lexicon.

Source repository: https://github.com/konsheng/Sensitive-lexicon

This module does NOT perform network I/O at import time. Startup and manual
updates both call ``LexiconUpdater.check_and_update()`` explicitly.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── defaults ─────────────────────────────────────────────────────────────────

_SOURCE_REPO = "https://github.com/konsheng/Sensitive-lexicon"
_SOURCE_BRANCH = "main"
_DEFAULT_LEXICON_DIR_NAME = "Sensitive-lexicon"

# File extensions recognized by SensitiveLexiconScanner.from_path()
_TEXT_EXTENSIONS = {".txt", ".dict", ".csv", ".md"}

# Documentation / repo metadata files that should NOT be loaded as lexicon words.
# Matched case-insensitively against the full filename.
_SKIP_FILE_NAMES: frozenset[str] = frozenset({
    "readme.md",
    "readme.txt",
    "readme",
    "license",
    "license.md",
    "license.txt",
    "changelog",
    "changelog.md",
    "changelog.txt",
    "contributing.md",
    "contributing.txt",
    "code_of_conduct.md",
    ".gitignore",
    ".gitattributes",
})

# Top-level directories to skip during extraction (repo metadata, not lexicon data).
_SKIP_TOP_DIRS: frozenset[str] = frozenset({
    "docs",
    "doc",
    ".github",
    ".git",
    "__pycache__",
    "test",
    "tests",
})


# ── metadata ─────────────────────────────────────────────────────────────────


@dataclass
class LexiconUpdateMeta:
    """Persisted metadata about the last lexicon update attempt."""

    source_repo: str = _SOURCE_REPO
    branch: str = _SOURCE_BRANCH
    commit_sha: str = ""
    updated_at: str = ""
    file_count: int = 0
    word_count: int = 0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceRepo": self.source_repo,
            "branch": self.branch,
            "commitSha": self.commit_sha,
            "updatedAt": self.updated_at,
            "fileCount": self.file_count,
            "wordCount": self.word_count,
            "lastError": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LexiconUpdateMeta:
        return cls(
            source_repo=data.get("sourceRepo", _SOURCE_REPO),
            branch=data.get("branch", _SOURCE_BRANCH),
            commit_sha=data.get("commitSha", ""),
            updated_at=data.get("updatedAt", ""),
            file_count=data.get("fileCount", 0),
            word_count=data.get("wordCount", 0),
            last_error=data.get("lastError", ""),
        )


@dataclass
class LexiconUpdateResult:
    """Result of a single update attempt."""

    success: bool = False
    file_count: int = 0
    word_count: int = 0
    commit_sha: str = ""
    error: str = ""


# ── updater ──────────────────────────────────────────────────────────────────


class LexiconUpdater:
    """Manages downloading, validating, and atomically replacing the lexicon directory.

    Usage::

        updater = LexiconUpdater()
        result = updater.check_and_update()
        print(result)
    """

    def __init__(
        self,
        lexicon_dir: Path | str | None = None,
        *,
        source_repo: str = _SOURCE_REPO,
        branch: str = _SOURCE_BRANCH,
    ):
        from app.services.aggregate_settings import resolve_sensitive_lexicon_path

        if lexicon_dir is not None:
            self._lexicon_dir = Path(lexicon_dir)
        else:
            self._lexicon_dir = resolve_sensitive_lexicon_path(None).parent
        self._lexicon_target = self._lexicon_dir / _DEFAULT_LEXICON_DIR_NAME
        self._meta_path = self._lexicon_dir / "lexicon_meta.json"
        self._source_repo = source_repo
        self._branch = branch

    # ── public API ──────────────────────────────────────────────────────────

    @property
    def lexicon_dir(self) -> Path:
        return self._lexicon_dir

    @property
    def lexicon_target(self) -> Path:
        return self._lexicon_target

    def load_meta(self) -> LexiconUpdateMeta:
        """Load persisted metadata, or return a blank meta if none exists."""
        if not self._meta_path.exists():
            return LexiconUpdateMeta(source_repo=self._source_repo, branch=self._branch)
        try:
            data = json.loads(self._meta_path.read_text(encoding="utf-8"))
            return LexiconUpdateMeta.from_dict(data)
        except Exception as exc:
            logger.warning("Failed to read lexicon meta: %s", exc)
            return LexiconUpdateMeta(source_repo=self._source_repo, branch=self._branch)

    def _save_meta(self, meta: LexiconUpdateMeta) -> None:
        self._meta_path.parent.mkdir(parents=True, exist_ok=True)
        self._meta_path.write_text(
            json.dumps(meta.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def check_and_update(self) -> LexiconUpdateResult:
        """Download the lexicon, validate it, and atomically replace the local copy.

        Returns a :class:`LexiconUpdateResult` indicating success or failure.
        On failure the existing local lexicon is preserved.
        """
        meta = self.load_meta()
        result = LexiconUpdateResult()
        tmp_dir: Path | None = None

        try:
            # 1. Download to a temporary directory.
            tmp_dir = Path(tempfile.mkdtemp(prefix="lexicon_dl_"))
            try:
                commit_sha = self._download_lexicon(tmp_dir)
            except Exception as exc:
                result.error = f"Download failed: {exc}"
                meta.last_error = result.error
                meta.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_meta(meta)
                logger.warning("Lexicon download failed: %s", exc)
                return result

            # 2. Validate: ensure SensitiveLexiconScanner can load the content.
            try:
                from app.ai.lexicon import SensitiveLexiconScanner

                scanner = SensitiveLexiconScanner.from_path(tmp_dir)
                if scanner.word_count == 0:
                    raise ValueError("Lexicon contains 0 words after loading")
            except Exception as exc:
                result.error = f"Validation failed: {exc}"
                meta.last_error = result.error
                meta.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_meta(meta)
                logger.warning("Lexicon validation failed: %s", exc)
                return result

            # 3. Count files (excluding documentation files).
            file_count = sum(
                1
                for f in tmp_dir.rglob("*")
                if f.is_file()
                and f.suffix.lower() in _TEXT_EXTENSIONS
                and not self._is_skipped_doc_file(str(f.relative_to(tmp_dir)))
            )

            # 4. Atomic replace: rename old → backup, rename new → target, remove backup.
            backup = self._lexicon_target.with_suffix(".bak")
            try:
                if self._lexicon_target.exists():
                    if backup.exists():
                        shutil.rmtree(backup)
                    self._lexicon_target.rename(backup)
                tmp_dir.rename(self._lexicon_target)
                # Clean up backup on success.
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
            except Exception as exc:
                # Rollback: restore backup if the target was lost.
                # If both backup and target exist, do nothing — no data loss.
                if backup.exists() and not self._lexicon_target.exists():
                    try:
                        backup.rename(self._lexicon_target)
                    except Exception:
                        logger.warning("Rollback failed: backup exists at %s but could not restore", backup)
                result.error = f"Atomic replace failed: {exc}"
                meta.last_error = result.error
                meta.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_meta(meta)
                logger.warning("Lexicon atomic replace failed: %s", exc)
                return result

            # 5. Update metadata.
            result.success = True
            result.file_count = file_count
            result.word_count = scanner.word_count
            result.commit_sha = commit_sha

            meta.commit_sha = commit_sha
            meta.updated_at = datetime.now(timezone.utc).isoformat()
            meta.file_count = file_count
            meta.word_count = scanner.word_count
            meta.last_error = ""
            self._save_meta(meta)

            logger.info(
                "Lexicon updated: %d files, %d words, commit %s",
                file_count,
                scanner.word_count,
                commit_sha[:12] if commit_sha else "unknown",
            )
            return result

        except Exception as exc:
            result.error = f"Unexpected error: {exc}"
            logger.warning("Lexicon update unexpected error: %s", exc, exc_info=True)
            return result

        finally:
            # Clean up temp directory if it still exists (wasn't renamed into target).
            if tmp_dir is not None and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── internal ────────────────────────────────────────────────────────────

    def _download_lexicon(self, target_dir: Path) -> str:
        """Download the lexicon repo as a zipball and extract text files.

        Returns the commit SHA of the downloaded snapshot.

        Raises:
            ValueError: If the zipball is empty or contains path-traversal entries.
            httpx.HTTPStatusError: On download failure.
        """
        import httpx

        repo_path = self._source_repo.split("github.com/")[-1]
        api_url = f"https://api.github.com/repos/{repo_path}/commits/{self._branch}"
        commit_sha = ""

        with httpx.Client(timeout=30, follow_redirects=True) as client:
            # Get latest commit SHA.
            resp = client.get(api_url, headers={"Accept": "application/vnd.github.v3+json"})
            if resp.status_code == 200:
                commit_sha = resp.json().get("sha", "")

            # Download zipball.
            zip_url = f"https://github.com/{repo_path}/archive/refs/heads/{self._branch}.zip"
            resp = client.get(zip_url, follow_redirects=True)
            resp.raise_for_status()

            import io
            import zipfile

            zip_data = io.BytesIO(resp.content)
            with zipfile.ZipFile(zip_data) as zf:
                self._extract_zip(zf, target_dir)

        return commit_sha

    @staticmethod
    def _is_safe_zip_path(rel_path: str) -> bool:
        """Return True if *rel_path* is safe for extraction (no traversal, no absolute, no Windows drive)."""
        # Reject absolute paths and Windows drive-letter paths.
        if rel_path.startswith(("/", "\\")):
            return False
        if len(rel_path) >= 2 and rel_path[1] == ":":
            return False

        # Reject any component that is ".." (path traversal).
        for part in Path(rel_path).parts:
            if part == "..":
                return False

        return True

    @staticmethod
    def _is_skipped_doc_file(rel_path: str) -> bool:
        """Return True if *rel_path* points to a documentation file that should not be
        treated as lexicon word data."""
        p = Path(rel_path)
        # Skip well-known doc files by name (case-insensitive).
        if p.name.lower() in _SKIP_FILE_NAMES:
            return True
        # Skip files inside documentation directories.
        if p.parts and p.parts[0].lower() in _SKIP_TOP_DIRS:
            return True
        return False

    @staticmethod
    def _extract_zip(zf: "zipfile.ZipFile", target_dir: Path) -> None:
        """Extract *zf* into *target_dir*, applying path-traversal and doc-file filters.

        Raises:
            ValueError: If a zip entry has a traversal path or the zipball is empty.
        """
        import zipfile as _zipfile_mod

        target_resolved = target_dir.resolve()

        # Detect the top-level directory prefix (e.g. "Sensitive-lexicon-main/").
        top_level = None
        for name in zf.namelist():
            parts = name.split("/")
            if len(parts) > 1 and parts[0]:
                top_level = parts[0]
                break
        if not top_level:
            raise ValueError("Empty zipball")

        extracted_count = 0
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            # Strip the top-level directory prefix.
            if member.startswith(top_level + "/"):
                rel_path = member[len(top_level) + 1 :]
            else:
                rel_path = member
            if not rel_path:
                continue

            # ── Security: reject path traversal and absolute paths ──────────
            if not LexiconUpdater._is_safe_zip_path(rel_path):
                raise ValueError(
                    f"Unsafe zip path detected: {member!r} (resolved rel: {rel_path!r}). "
                    "Refusing to extract to prevent path traversal."
                )

            # ── Quality: skip documentation files ───────────────────────────
            if LexiconUpdater._is_skipped_doc_file(rel_path):
                logger.debug("Skipping documentation file in zip: %s", rel_path)
                continue

            target_file = (target_dir / rel_path).resolve()
            # Final guard: resolved path must be inside target_dir.
            try:
                target_file.relative_to(target_resolved)
            except ValueError:
                raise ValueError(
                    f"Zip path {member!r} escapes target directory after resolution. "
                    f"Resolved to {target_file}, target is {target_resolved}."
                )

            target_file.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target_file, "wb") as dst:
                dst.write(src.read())
            extracted_count += 1

        if extracted_count == 0:
            raise ValueError("Zipball contained no usable lexicon files after filtering")
