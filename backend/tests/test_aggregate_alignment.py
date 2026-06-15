"""Tests for chapter content classification and cross-source alignment."""

import json

from app.services.aggregate_alignment import (
    classify_source_content,
    align_candidate_chapter,
    build_source_alignment_json,
    _title_similarity,
    _sliding_preview_similarity,
)


# ── classify_source_content ──────────────────────────────────────────────────


def test_classify_full_content():
    content = "这是一段足够长的正文内容，超过两百个字。" * 20
    result = classify_source_content(content, source_id="qidian_com", is_official=True)
    assert result["classification"] == "full"
    assert result["isOfficial"] is True
    assert result["contentLength"] > 200


def test_classify_preview_content():
    # VIP preview: short content (< 200 chars), typical of paid chapter previews.
    content = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道，这一切才刚刚开始……（本章为VIP章节，请登录后阅读完整内容）"
    result = classify_source_content(content, source_id="qidian_com", is_official=True)
    assert result["classification"] == "preview"
    assert result["previewText"] != ""
    assert result["contentLength"] < 200


def test_classify_empty_content():
    result = classify_source_content("", source_id="qidian_com", is_official=True)
    assert result["classification"] == "empty"
    assert result["contentLength"] == 0


def test_classify_none_content():
    result = classify_source_content(None, source_id="example_com", is_official=False)
    assert result["classification"] == "empty"


def test_classify_third_party_full():
    content = "这是一段第三方源的完整正文。" * 30
    result = classify_source_content(content, source_id="example_com", is_official=False)
    assert result["classification"] == "full"
    assert result["isOfficial"] is False


# ── title_similarity ─────────────────────────────────────────────────────────


def test_title_similarity_identical():
    assert _title_similarity("第一百二十八章 风起", "第一百二十八章 风起") >= 0.95


def test_title_similarity_similar():
    sim = _title_similarity("第一百二十八章 风起", "第128章 风起")
    assert sim >= 0.5  # different numeral form


def test_title_similarity_different():
    sim = _title_similarity("第一百二十八章 风起", "第五十章 落日")
    assert sim < 0.5


# ── sliding_preview_similarity ───────────────────────────────────────────────


def test_sliding_preview_match():
    preview = "少年站在山巅，望着远方的云海。"
    # Candidate contains the preview text near the start but with a site prefix.
    candidate = "【某某小说网】少年站在山巅，望着远方的云海。他知道这一切才刚刚开始，未来还有很长的路要走。" * 5
    sim = _sliding_preview_similarity(preview, candidate)
    assert sim >= 0.70


def test_sliding_preview_no_match():
    preview = "少年站在山巅，望着远方的云海。"
    candidate = "这一段完全是不同的内容，和预览没有任何关系。" * 10
    sim = _sliding_preview_similarity(preview, candidate)
    assert sim < 0.50


def test_sliding_preview_short_preview():
    """Even a very short preview (40 chars) should work."""
    preview = "少年站在山巅"
    candidate = "本站提示少年站在山巅，望着远方。" * 5
    sim = _sliding_preview_similarity(preview, candidate)
    assert sim >= 0.60


# ── align_candidate_chapter ──────────────────────────────────────────────────


def test_alignment_passes_with_good_title_and_preview():
    official_preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来还有很长的路。"
    candidate_title = "第一百二十八章 风起"
    candidate_content = "【小说网】少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来还有很长的路。后续正文内容很多很多。" * 5
    expected_title = "第一百二十八章 风起"

    result = align_candidate_chapter(
        official_preview=official_preview,
        candidate_title=candidate_title,
        candidate_content=candidate_content,
        expected_title=expected_title,
    )
    assert result["alignmentPassed"] is True
    assert result["titleSimilarity"] >= 0.80
    assert result["previewSimilarity"] >= 0.70


def test_alignment_fails_with_bad_title_and_low_preview():
    official_preview = "少年站在山巅，望着远方的云海。"
    candidate_title = "第五十章 落日"
    candidate_content = "完全不同的内容，和预览没有任何关系。" * 10
    expected_title = "第一百二十八章 风起"

    result = align_candidate_chapter(
        official_preview=official_preview,
        candidate_title=candidate_title,
        candidate_content=candidate_content,
        expected_title=expected_title,
    )
    assert result["alignmentPassed"] is False
    assert result["titleSimilarity"] < 0.80
    assert result["previewSimilarity"] < 0.70


def test_alignment_high_preview_relaxes_title():
    """When preview similarity >= 0.88, title similarity requirement is relaxed."""
    official_preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来路还很长。"
    candidate_title = "第一百二十八章"  # partial title, not great match
    # Very high preview match — should pass even with imperfect title.
    candidate_content = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来路还很长。后续还有很多正文。" * 5
    expected_title = "第一百二十八章 风起"

    result = align_candidate_chapter(
        official_preview=official_preview,
        candidate_title=candidate_title,
        candidate_content=candidate_content,
        expected_title=expected_title,
    )
    assert result["previewSimilarity"] >= 0.88
    assert result["alignmentPassed"] is True


def test_alignment_fails_with_empty_preview():
    result = align_candidate_chapter(
        official_preview="",
        candidate_title="第一章 测试",
        candidate_content="一些内容" * 20,
        expected_title="第一章 测试",
    )
    assert result["alignmentPassed"] is False
    assert result["alignmentReason"] == "no_preview_available"


# ── build_source_alignment_json ──────────────────────────────────────────────


def test_build_alignment_json_for_official_full():
    result = build_source_alignment_json(
        selected_content_source="official",
        official_content_length=5000,
        candidate_content_length=0,
        title_similarity=1.0,
        preview_similarity=0.0,
        alignment_passed=True,
        alignment_reason="official_full_content",
    )
    assert result["selectedContentSource"] == "official"
    assert result["officialContentLength"] == 5000
    assert result["alignmentPassed"] is True
    assert result["alignmentReason"] == "official_full_content"
    # Must be JSON-serializable.
    json.dumps(result)


def test_build_alignment_json_for_candidate():
    result = build_source_alignment_json(
        selected_content_source="candidate",
        official_content_length=100,
        candidate_content_length=3500,
        title_similarity=0.94,
        preview_similarity=0.89,
        alignment_passed=True,
        alignment_reason="title_and_preview_matched",
    )
    assert result["selectedContentSource"] == "candidate"
    assert result["candidateContentLength"] == 3500
    assert result["titleSimilarity"] == 0.94


# ── deviation score ──────────────────────────────────────────────────────────


def test_deviation_score_identical_text():
    from app.services.aggregate_alignment import compute_deviation_score
    text = "少年站在山巅望着远方的云海心中涌起一股莫名的悸动"
    assert compute_deviation_score(text, text) >= 0.95


def test_deviation_score_similar_text():
    from app.services.aggregate_alignment import compute_deviation_score
    original = "少年站在山巅望着远方的云海心中涌起一股莫名的悸动他知道这一切才刚刚开始"
    # AI output with minor edits (removed a few chars).
    output = "少年站在山巅望着远方云海心中涌起莫名的悸动他知道这一切才刚刚开始"
    score = compute_deviation_score(original, output)
    assert 0.70 <= score <= 0.99


def test_deviation_score_completely_different():
    from app.services.aggregate_alignment import compute_deviation_score
    original = "少年站在山巅望着远方的云海"
    output = "这是一段完全不同的内容没有任何关联"
    score = compute_deviation_score(original, output)
    assert score < 0.30


def test_deviation_score_empty_input():
    from app.services.aggregate_alignment import compute_deviation_score
    assert compute_deviation_score("", "abc") == 0.0
    assert compute_deviation_score("abc", "") == 0.0
