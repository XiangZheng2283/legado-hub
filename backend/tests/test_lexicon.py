"""Tests for sensitive lexicon scanning and blocked-word candidate detection."""

from app.ai.lexicon import BlockedWordCandidate, SensitiveLexiconScanner


# ── scanner construction ─────────────────────────────────────────────────────


def test_scanner_loads_from_word_list():
    scanner = SensitiveLexiconScanner.from_word_list(["暴力", "血腥", "色情"])
    assert scanner.word_count == 3


def test_scanner_empty_word_list():
    scanner = SensitiveLexiconScanner.from_word_list([])
    assert scanner.word_count == 0


# ── direct masked symbol detection ───────────────────────────────────────────


def test_detect_star_mask():
    scanner = SensitiveLexiconScanner.from_word_list(["杀意"])
    candidates = scanner.scan("他眼中闪过一丝杀*意，手中长剑出鞘")
    assert len(candidates) >= 1
    found = [c for c in candidates if "杀" in c.masked_text and c.offset >= 0]
    assert len(found) >= 1


def test_detect_square_mask():
    scanner = SensitiveLexiconScanner.from_word_list(["血腥"])
    candidates = scanner.scan("满地都是血□腥的画面")
    found = [c for c in candidates if "血" in c.masked_text]
    assert len(found) >= 1


def test_detect_x_mask():
    scanner = SensitiveLexiconScanner.from_word_list(["色情"])
    candidates = scanner.scan("这段色x情描写需要处理")
    found = [c for c in candidates if "色" in c.masked_text]
    assert len(found) >= 1


def test_no_candidates_for_clean_text():
    scanner = SensitiveLexiconScanner.from_word_list(["暴力"])
    candidates = scanner.scan("这是一段完全正常的文本，没有任何敏感词。")
    assert len(candidates) == 0


# ── context extraction ───────────────────────────────────────────────────────


def test_candidate_has_context_before_and_after():
    scanner = SensitiveLexiconScanner.from_word_list(["杀意"])
    text = "他眼中闪过一丝杀*意，手中长剑出鞘"
    candidates = scanner.scan(text)
    found = [c for c in candidates if c.masked_text]
    assert len(found) >= 1
    c = found[0]
    assert len(c.context_before) > 0
    assert len(c.context_after) > 0


# ── multiple occurrences ─────────────────────────────────────────────────────


def test_detects_multiple_blocked_words():
    scanner = SensitiveLexiconScanner.from_word_list(["杀意", "血腥"])
    text = "他带着杀*意冲了进去，看到满地血□腥的场面"
    candidates = scanner.scan(text)
    assert len(candidates) >= 2


# ── candidate structure ──────────────────────────────────────────────────────


def test_candidate_fields_are_correct():
    scanner = SensitiveLexiconScanner.from_word_list(["测试"])
    candidates = scanner.scan("这里有测*试文本")
    found = [c for c in candidates if c.masked_text]
    assert len(found) >= 1
    c = found[0]
    assert isinstance(c, BlockedWordCandidate)
    assert c.offset >= 0
    assert isinstance(c.masked_text, str)
    assert isinstance(c.context_before, str)
    assert isinstance(c.context_after, str)
    assert isinstance(c.candidates, list)
    assert c.confidence >= 0.0


# ── trie / dfa matching ─────────────────────────────────────────────────────


def test_scanner_uses_trie_for_multi_word_matching():
    words = ["色情", "色情描写", "暴力", "暴力血腥"]
    scanner = SensitiveLexiconScanner.from_word_list(words)
    # Text contains masked version: 暴力*血腥 → mask between 暴力 and 血腥
    candidates = scanner.scan("这段暴*力血腥的场面需要处理")
    found_texts = [c.masked_text for c in candidates]
    assert any("暴" in t for t in found_texts)


# ── whitespace-separated masked words ────────────────────────────────────────


def test_detect_space_separated_mask():
    scanner = SensitiveLexiconScanner.from_word_list(["测试"])
    candidates = scanner.scan("这里有测 试文本")
    found = [c for c in candidates if "测" in c.masked_text]
    assert len(found) >= 1


def test_no_false_positive_for_natural_spaces():
    """'这里有 暴力 内容' — spaces between normal words must NOT trigger a match."""
    scanner = SensitiveLexiconScanner.from_word_list(["暴力"])
    candidates = scanner.scan("这里有 暴力 内容")
    assert len(candidates) == 0


def test_mask_in_middle_still_works_with_space():
    """'暴 力' — a space INSIDE a word should still be detected as mask."""
    scanner = SensitiveLexiconScanner.from_word_list(["暴力"])
    candidates = scanner.scan("他带着暴 力行为冲了进去")
    found = [c for c in candidates if "暴" in c.masked_text]
    assert len(found) >= 1


# ── directory loading ────────────────────────────────────────────────────────


def test_from_path_loads_directory_of_word_files(tmp_path):
    """from_path() should recursively load .txt files from a directory."""
    lexicon_dir = tmp_path / "Sensitive-lexicon"
    lexicon_dir.mkdir()
    (lexicon_dir / "words1.txt").write_text("暴力\n血腥\n", encoding="utf-8")
    (lexicon_dir / "words2.txt").write_text("色情\n赌博\n", encoding="utf-8")
    # Non-txt extensions are skipped entirely.
    (lexicon_dir / "readme.md").write_text("# Lexicon\n", encoding="utf-8")
    (lexicon_dir / "data.bin").write_bytes(b"\x00\x01")

    scanner = SensitiveLexiconScanner.from_path(lexicon_dir)

    # .md is a text extension, so "# Lexicon" is loaded (not a comment,
    # starts with '# ' but after strip it starts with '#', so it IS skipped).
    assert scanner.word_count == 4


def test_from_path_loads_single_file(tmp_path):
    """from_path() with a single file should work like from_file()."""
    f = tmp_path / "words.txt"
    f.write_text("暴力\n血腥\n", encoding="utf-8")

    scanner = SensitiveLexiconScanner.from_path(f)

    assert scanner.word_count == 2


def test_from_path_nonexistent_returns_empty():
    scanner = SensitiveLexiconScanner.from_path("/nonexistent/path/to/lexicon")
    assert scanner.word_count == 0
