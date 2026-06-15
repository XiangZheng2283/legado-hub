"""Sensitive lexicon scanner for detecting masked blocked words in chapter text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Characters commonly used to mask sensitive words in Chinese web novels.
MASK_CHARS = frozenset("*＊□■xX×_＿ ")

# Regex that matches a single mask character (for splitting / replacement).
_MASK_RE = re.compile(r"[*＊□■xX×_＿ ]")

# How many characters of context to extract before/after a candidate.
_CONTEXT_RADIUS = 10


class _TrieNode:
    __slots__ = ("children", "is_end")

    def __init__(self) -> None:
        self.children: dict[str, _TrieNode] = {}
        self.is_end: bool = False


@dataclass
class BlockedWordCandidate:
    """One detected masked-word position with recovery hints."""

    offset: int
    masked_text: str
    context_before: str
    context_after: str
    candidates: list[str] = field(default_factory=list)
    confidence: float = 0.0


class SensitiveLexiconScanner:
    """DFA/trie-based scanner that finds masked sensitive words in text.

    Usage::

        scanner = SensitiveLexiconScanner.from_word_list(["杀意", "血腥"])
        candidates = scanner.scan("他带着杀*意冲了进去")
    """

    def __init__(self, root: _TrieNode, word_count: int) -> None:
        self._root = root
        self.word_count = word_count

    # ── construction ─────────────────────────────────────────────────────

    @classmethod
    def from_word_list(cls, words: list[str]) -> SensitiveLexiconScanner:
        root = _TrieNode()
        count = 0
        for word in words:
            w = word.strip()
            if not w:
                continue
            node = root
            for ch in w:
                if ch not in node.children:
                    node.children[ch] = _TrieNode()
                node = node.children[ch]
            node.is_end = True
            count += 1
        return cls(root, count)

    @classmethod
    def from_file(cls, path: str | Path) -> SensitiveLexiconScanner:
        """Load a lexicon from a plain-text file (one word per line)."""
        p = Path(path)
        if not p.exists():
            return cls.from_word_list([])
        words = [line.strip() for line in p.read_text(encoding="utf-8").splitlines()]
        return cls.from_word_list(words)

    @classmethod
    def from_path(cls, path: str | Path) -> SensitiveLexiconScanner:
        """Load a lexicon from a file *or* directory.

        When *path* is a directory, recursively reads all ``*.txt``,
        ``*.dict``, ``*.csv`` and ``*.md`` files and merges them into one
        word list.  Non-text files, blank lines and lines starting with
        ``#`` are skipped.
        """
        p = Path(path)
        if not p.exists():
            return cls.from_word_list([])

        if p.is_file():
            return cls.from_file(p)

        # Directory mode — walk recursively for known text extensions.
        _TEXT_EXTENSIONS = {".txt", ".dict", ".csv", ".md"}
        words: list[str] = []
        for child in sorted(p.rglob("*")):
            if not child.is_file():
                continue
            if child.suffix.lower() not in _TEXT_EXTENSIONS:
                continue
            try:
                text = child.read_text(encoding="utf-8")
            except Exception:
                continue
            for line in text.splitlines():
                w = line.strip()
                if w and not w.startswith("#"):
                    words.append(w)
        return cls.from_word_list(words)

    # ── scanning ─────────────────────────────────────────────────────────

    def scan(self, text: str) -> list[BlockedWordCandidate]:
        """Scan *text* for masked sensitive words.

        Returns a list of :class:`BlockedWordCandidate` for each detected
        position.  The list is sorted by ``offset`` ascending.
        """
        if not text or self.word_count == 0:
            return []

        candidates: list[BlockedWordCandidate] = []
        n = len(text)

        for start in range(n):
            # Try to match from every position in the text.
            self._match_from(text, start, n, candidates)

        # Deduplicate overlapping detections (keep longest / earliest).
        candidates.sort(key=lambda c: (c.offset, -len(c.masked_text)))
        return self._deduplicate(candidates)

    # ── internal matching ────────────────────────────────────────────────

    def _match_from(
        self,
        text: str,
        start: int,
        n: int,
        results: list[BlockedWordCandidate],
    ) -> None:
        """Try to match a trie word starting at *start*, allowing mask chars.

        A match can only begin on a real trie character (not a mask char).
        Mask characters are allowed *between* trie characters once matching
        has started, but the first character consumed must be a trie child.
        """
        ch0 = text[start]
        if ch0 in MASK_CHARS:
            # Cannot start a match on a mask character — prevents false
            # positives like "这里有 暴力 内容" where a normal space
            # precedes the full word.
            return

        node = self._root
        if ch0 not in node.children:
            return

        node = node.children[ch0]
        pos = start + 1
        matched_len = 1
        mask_count = 0
        max_masks = 2  # at most 2 mask chars in a single word

        # The first char matched — check immediately if it's a 1-char word.
        if node.is_end and mask_count > 0:
            self._emit_candidate(text, start, pos, n, results)

        while pos < n:
            ch = text[pos]
            if ch in MASK_CHARS:
                mask_count += 1
                if mask_count > max_masks:
                    return
                pos += 1
                matched_len += 1
                continue

            if ch not in node.children:
                return

            node = node.children[ch]
            pos += 1
            matched_len += 1

            if node.is_end and mask_count > 0:
                self._emit_candidate(text, start, pos, n, results)

    @staticmethod
    def _emit_candidate(
        text: str, start: int, pos: int, n: int, results: list[BlockedWordCandidate]
    ) -> None:
        masked_text = text[start:pos]
        ctx_before = text[max(0, start - _CONTEXT_RADIUS) : start]
        ctx_after = text[pos : min(n, pos + _CONTEXT_RADIUS)]
        clean_word = _MASK_RE.sub("", masked_text)
        results.append(
            BlockedWordCandidate(
                offset=start,
                masked_text=masked_text,
                context_before=ctx_before,
                context_after=ctx_after,
                candidates=[clean_word],
                confidence=0.7,
            )
        )

    def _deduplicate(
        self, candidates: list[BlockedWordCandidate]
    ) -> list[BlockedWordCandidate]:
        """Remove overlapping detections, keeping the longest match."""
        if not candidates:
            return []
        result: list[BlockedWordCandidate] = []
        occupied: set[int] = set()
        for c in candidates:
            positions = set(range(c.offset, c.offset + len(c.masked_text)))
            if positions & occupied:
                continue
            occupied |= positions
            result.append(c)
        return result
