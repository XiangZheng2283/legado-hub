"""Conservative paragraph cleanup backed by multiple source bodies."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from app.services.content_purify import CHAPTER_TITLE_RE
from app.services.text_convert import to_simplified


LINE_MATCH_THRESHOLD = 0.88
NEAR_PARAGRAPH_PRESERVATION_THRESHOLD = 0.80
LINE_MATCH_WINDOW = 3
SHORT_PARAGRAPH_LENGTH = 8
AUDIT_SAMPLE_LIMIT = 20
MIN_DIRECT_ANCHOR_COVERAGE = 0.75
MIN_CONSENSUS_SOURCE_COUNT = 3
MIN_ANCHOR_PEER_COUNT = 2
MAX_REMOVABLE_BLOCK_PARAGRAPHS = 3
MAX_REMOVAL_RATIO = 0.02


def _paragraphs(content: str) -> list[tuple[int, str]]:
    """Return non-empty paragraphs with their original line indexes."""
    return [
        (line_index, line.strip())
        for line_index, line in enumerate(content.splitlines())
        if line.strip()
    ]


def _normalize_paragraph(value: str) -> str:
    """Normalize Traditional Chinese, Unicode forms, punctuation and whitespace."""
    simplified = str(to_simplified(unicodedata.normalize("NFKC", value)) or "")
    return re.sub(r"[\W_]+", "", simplified.casefold())


def _paragraph_similarity(left: str, right: str) -> float:
    """Compare normalized paragraphs while rejecting fuzzy short-text matches."""
    if not left or not right:
        return 0.0
    if min(len(left), len(right)) < SHORT_PARAGRAPH_LENGTH:
        return 1.0 if left == right else 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def _aligned_reference_indexes(
    reference: list[str],
    peer: list[str],
) -> tuple[set[int], set[int]]:
    """Greedily align one peer with +/-3 search and 1:1, 1:2, 2:1 spans."""
    supported: set[int] = set()
    direct_supported: set[int] = set()
    used_peer_indexes: set[int] = set()
    peer_cursor = 0
    reference_index = 0

    while reference_index < len(reference):
        best_rank: tuple[float, int, int, int] | None = None
        best_match: tuple[int, int, int] | None = None
        lower = max(0, peer_cursor - LINE_MATCH_WINDOW)
        upper = min(len(peer), peer_cursor + LINE_MATCH_WINDOW + 1)
        for peer_index in range(lower, upper):
            for reference_span, peer_span in ((1, 1), (1, 2), (2, 1)):
                if reference_index + reference_span > len(reference):
                    continue
                if peer_index + peer_span > len(peer):
                    continue
                peer_indexes = range(peer_index, peer_index + peer_span)
                if any(index in used_peer_indexes for index in peer_indexes):
                    continue
                left = "".join(reference[reference_index : reference_index + reference_span])
                right = "".join(peer[peer_index : peer_index + peer_span])
                score = _paragraph_similarity(left, right)
                if score < LINE_MATCH_THRESHOLD:
                    continue
                rank = (
                    score,
                    -abs(peer_index - peer_cursor),
                    -(reference_span + peer_span),
                    -peer_index,
                )
                if best_rank is None or rank > best_rank:
                    best_rank = rank
                    best_match = (peer_index, reference_span, peer_span)

        if best_match is None:
            reference_index += 1
            continue

        peer_index, reference_span, peer_span = best_match
        supported.update(range(reference_index, reference_index + reference_span))
        if reference_span == 1 and peer_span == 1:
            direct_supported.add(reference_index)
        used_peer_indexes.update(range(peer_index, peer_index + peer_span))
        peer_cursor = peer_index + peer_span
        reference_index += reference_span

    return supported, direct_supported


def _is_duplicate_title(text: str, chapter_title: str, paragraph_index: int) -> bool:
    """Recognize an embedded title only near the beginning of a chapter."""
    if not chapter_title or paragraph_index > 2:
        return False
    from app.services.aggregate_alignment import chapter_title_similarity

    candidate = text.lstrip("#").strip()
    if ">" in candidate or "＞" in candidate:
        candidate = re.split(r"[>＞]", candidate)[-1].strip()
    if chapter_title_similarity(chapter_title, candidate) >= 0.80:
        return True
    return bool(CHAPTER_TITLE_RE.match(candidate)) and (
        _normalize_paragraph(chapter_title) in _normalize_paragraph(candidate)
        or _normalize_paragraph(candidate) in _normalize_paragraph(chapter_title)
    )


def _audit_line(
    *,
    paragraph_index: int,
    text: str,
    support_count: int,
    reason: str,
    include_content: bool = False,
) -> dict[str, Any]:
    """Build an audit record, optionally retaining text that was removed."""
    record = {
        "paragraphIndex": paragraph_index,
        "supportCount": support_count,
        "reason": reason,
        "sample": text[:120],
    }
    if include_content:
        record["content"] = text
    return record


def _support_counts(
    selected_paragraphs: list[tuple[int, str]],
    source_bodies: dict[str, str],
    selected_source_id: str,
) -> tuple[list[int], list[int]]:
    """Count general and direct 1:1 support for every selected paragraph."""
    reference = [_normalize_paragraph(text) for _, text in selected_paragraphs]
    support_counts = [1] * len(reference)
    direct_support_counts = [1] * len(reference)
    for source_id, peer_content in source_bodies.items():
        if source_id == selected_source_id:
            continue
        peer = [_normalize_paragraph(text) for _, text in _paragraphs(peer_content)]
        supported, direct_supported = _aligned_reference_indexes(reference, peer)
        for paragraph_index in supported:
            support_counts[paragraph_index] += 1
        for paragraph_index in direct_supported:
            direct_support_counts[paragraph_index] += 1
    return support_counts, direct_support_counts


def _has_near_peer_paragraph(
    reference_text: str,
    peer_paragraphs: list[list[str]],
    paragraph_index: int,
) -> bool:
    """Keep a source-unique paragraph when a peer has a close single-line form.

    The stricter alignment threshold remains responsible for structural anchors.
    This lower, single-paragraph threshold only vetoes deletion, covering short
    synonym substitutions without allowing cross-paragraph watermark matches.
    """
    for peer in peer_paragraphs:
        lower = max(0, paragraph_index - LINE_MATCH_WINDOW)
        upper = min(len(peer), paragraph_index + LINE_MATCH_WINDOW + 1)
        for peer_text in peer[lower:upper]:
            if _paragraph_similarity(reference_text, peer_text) >= NEAR_PARAGRAPH_PRESERVATION_THRESHOLD:
                return True
    return False


def direct_consensus_gap_count(
    selected_content: str,
    candidates: list[dict[str, Any]],
    *,
    selected_source_id: str,
) -> int:
    """Count selected paragraphs without direct support from a source majority."""
    source_bodies: dict[str, str] = {}
    for candidate in candidates:
        source_id = str(candidate.get("source_id", "") or "")
        content = str(candidate.get("content", "") or "")
        if source_id and content.strip() and source_id not in source_bodies:
            source_bodies[source_id] = content
    source_bodies[selected_source_id] = selected_content
    if len(source_bodies) < 2 or not selected_content.strip():
        return 0
    paragraphs = _paragraphs(selected_content)
    _, direct_support_counts = _support_counts(paragraphs, source_bodies, selected_source_id)
    majority_count = len(source_bodies) // 2 + 1
    return sum(count < majority_count for count in direct_support_counts)


def _anchor_bounded_unique_indexes(
    selected_paragraphs: list[tuple[int, str]],
    source_bodies: dict[str, str],
    selected_source_id: str,
    support_counts: list[int],
    chapter_title: str,
) -> dict[int, list[str]]:
    """Find short source-unique blocks bracketed by two matching peers."""
    reference = [_normalize_paragraph(text) for _, text in selected_paragraphs]
    title_indexes = {
        index
        for index, (_, text) in enumerate(selected_paragraphs)
        if _is_duplicate_title(text, chapter_title, index)
    }
    peer_direct_support: dict[str, set[int]] = {}
    for source_id, peer_content in source_bodies.items():
        if source_id == selected_source_id:
            continue
        peer = [_normalize_paragraph(text) for _, text in _paragraphs(peer_content)]
        _, direct_supported = _aligned_reference_indexes(reference, peer)
        comparable_count = max(1, len(reference) - len(title_indexes))
        if len(direct_supported) / comparable_count < MIN_DIRECT_ANCHOR_COVERAGE:
            continue
        peer_direct_support[source_id] = direct_supported

    removable: dict[int, list[str]] = {}
    paragraph_index = 0
    while paragraph_index < len(reference):
        if support_counts[paragraph_index] > 1:
            paragraph_index += 1
            continue
        block_start = paragraph_index
        while paragraph_index < len(reference) and support_counts[paragraph_index] == 1:
            paragraph_index += 1
        block_end = paragraph_index - 1
        if (
            block_start == 0
            or block_end + 1 >= len(reference)
            or block_end - block_start + 1 > MAX_REMOVABLE_BLOCK_PARAGRAPHS
        ):
            continue
        anchor_source_ids = sorted(
            source_id
            for source_id, direct_supported in peer_direct_support.items()
            if block_start - 1 in direct_supported and block_end + 1 in direct_supported
        )
        if len(anchor_source_ids) < MIN_ANCHOR_PEER_COUNT:
            continue
        for index in range(block_start, block_end + 1):
            removable[index] = anchor_source_ids
    return removable


def purify_by_line_consensus(
    selected_content: str,
    candidates: list[dict[str, Any]],
    *,
    selected_source_id: str,
    chapter_title: str = "",
) -> tuple[str, dict[str, Any]]:
    """Remove short source-unique insertions proven by two aligned peers."""
    source_bodies: dict[str, str] = {}
    for candidate in candidates:
        source_id = str(candidate.get("source_id", "") or "")
        content = str(candidate.get("content", "") or "")
        if source_id and content.strip() and source_id not in source_bodies:
            source_bodies[source_id] = content
    source_bodies[selected_source_id] = selected_content

    source_count = len(source_bodies)
    majority_count = source_count // 2 + 1
    audit: dict[str, Any] = {
        "applied": False,
        "reason": "pending" if source_count >= MIN_CONSENSUS_SOURCE_COUNT else "insufficient_sources",
        "sourceCount": source_count,
        "majorityCount": majority_count,
        "minimumSourceCount": MIN_CONSENSUS_SOURCE_COUNT,
        "minimumAnchorPeerCount": MIN_ANCHOR_PEER_COUNT,
        "windowSize": LINE_MATCH_WINDOW,
        "maxBlockParagraphs": MAX_REMOVABLE_BLOCK_PARAGRAPHS,
        "maxRemovalRatio": MAX_REMOVAL_RATIO,
        "originalLength": len(selected_content),
        "cleanedLength": len(selected_content),
        "removalRatio": 0.0,
        "removedCount": 0,
        "suspiciousCount": 0,
        "removalPolicy": "strict_three_source_anchor_bounded_unique",
        "removedLines": [],
        "suspiciousLines": [],
    }
    if source_count < MIN_CONSENSUS_SOURCE_COUNT or not selected_content.strip():
        return selected_content, audit

    selected_paragraphs = _paragraphs(selected_content)
    peer_paragraphs = [
        [_normalize_paragraph(text) for _, text in _paragraphs(content)]
        for source_id, content in source_bodies.items()
        if source_id != selected_source_id
    ]
    support_counts, direct_support_counts = _support_counts(
        selected_paragraphs,
        source_bodies,
        selected_source_id,
    )
    anchor_bounded_unique_indexes = _anchor_bounded_unique_indexes(
        selected_paragraphs,
        source_bodies,
        selected_source_id,
        support_counts,
        chapter_title,
    )

    removed: list[dict[str, Any]] = []
    suspicious: list[dict[str, Any]] = []
    dropped_line_indexes: set[int] = set()
    for paragraph_index, ((line_index, text), support_count) in enumerate(
        zip(selected_paragraphs, support_counts)
    ):
        reason = ""
        if (
            paragraph_index in anchor_bounded_unique_indexes
            and not _has_near_peer_paragraph(
                _normalize_paragraph(text), peer_paragraphs, paragraph_index
            )
        ):
            reason = "anchor_bounded_source_unique"
        if reason:
            dropped_line_indexes.add(line_index)
            removal = _audit_line(
                paragraph_index=paragraph_index,
                text=text,
                support_count=direct_support_counts[paragraph_index],
                reason=reason,
                include_content=True,
            )
            removal["anchorSourceIds"] = anchor_bounded_unique_indexes[paragraph_index]
            removed.append(removal)
        elif support_count < majority_count:
            suspicious.append(_audit_line(
                paragraph_index=paragraph_index,
                text=text,
                support_count=support_count,
                reason="minority_difference_preserved",
            ))

    audit["suspiciousCount"] = len(suspicious)
    audit["suspiciousLines"] = suspicious[:AUDIT_SAMPLE_LIMIT]
    if not dropped_line_indexes:
        audit["reason"] = "no_removable_segments"
        return selected_content, audit

    original_size = max(1, len(re.sub(r"\s+", "", selected_content)))
    removed_size = sum(len(re.sub(r"\s+", "", item["content"])) for item in removed)
    removal_ratio = removed_size / original_size
    audit["removalRatio"] = round(removal_ratio, 6)
    if removal_ratio > MAX_REMOVAL_RATIO:
        audit["reason"] = "removal_ratio_exceeded"
        audit["proposedRemovedCount"] = len(removed)
        audit["proposedRemovedLines"] = removed
        return selected_content, audit

    lines = selected_content.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    cleaned = "\n".join(
        line for line_index, line in enumerate(lines) if line_index not in dropped_line_indexes
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    audit["applied"] = True
    audit["reason"] = "ok"
    audit["removedCount"] = len(removed)
    audit["removedLines"] = removed
    audit["cleanedLength"] = len(cleaned)
    return cleaned, audit


def removed_segments_overlap_content(audit: dict[str, Any], content: str) -> bool:
    """Return whether a proposed deletion is present in an official body or preview."""
    normalized_content = _normalize_paragraph(content)
    for item in audit.get("removedLines", []) or []:
        segment = _normalize_paragraph(str(item.get("content", "") or ""))
        if not segment:
            continue
        if segment in normalized_content:
            return True
        if len(segment) < SHORT_PARAGRAPH_LENGTH or len(segment) > len(normalized_content):
            continue
        for start in range(len(normalized_content) - len(segment) + 1):
            window = normalized_content[start : start + len(segment)]
            if _paragraph_similarity(segment, window) >= NEAR_PARAGRAPH_PRESERVATION_THRESHOLD:
                return True
    return False


def diagnose_line_consensus(
    selected_content: str,
    candidates: list[dict[str, Any]],
    *,
    selected_source_id: str,
    chapter_title: str = "",
) -> dict[str, Any]:
    """Record cross-source paragraph differences without changing published text."""
    _discarded_content, audit = purify_by_line_consensus(
        selected_content,
        candidates,
        selected_source_id=selected_source_id,
        chapter_title=chapter_title,
    )
    findings = [
        *list(audit.get("removedLines", []) or []),
        *list(audit.get("proposedRemovedLines", []) or []),
        *list(audit.get("suspiciousLines", []) or []),
    ]
    audit["removalPolicy"] = "diagnostic_only"
    audit["sourceOnlySegments"] = findings[:AUDIT_SAMPLE_LIMIT]
    audit["removedLines"] = []
    audit["removedCount"] = 0
    audit["suspiciousLines"] = findings[:AUDIT_SAMPLE_LIMIT]
    audit["suspiciousCount"] = len(findings)
    audit["cleanedLength"] = len(selected_content)
    return audit
