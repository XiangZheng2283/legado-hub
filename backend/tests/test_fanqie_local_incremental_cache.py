from __future__ import annotations
import importlib.util
import json
import time
from pathlib import Path

from app.config import PROJECT_ROOT

SOURCE_PATH = PROJECT_ROOT / "plugins" / "sources" / "official" / "fanqie_local" / "source.py"
SPEC = importlib.util.spec_from_file_location("fanqie_local_incr_test", SOURCE_PATH)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def _write(j, lines) -> None:
    with open(j, "a", encoding="utf-8") as f:
        for item in lines:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def test_incremental_journal_cache_only_reads_tail(tmp_path: Path) -> None:
    M._JOURNAL_CACHE.clear()
    book = "777"
    folder = tmp_path / book
    folder.mkdir(parents=True)
    journal = folder / "downloaded_chapters.jsonl"

    _write(journal, [{"id": "1", "title": "yi", "content": "<p>1</p>"}])
    titles = [t for _, _, t, _ in M._journal_entries(folder)]
    assert titles == ["yi"]
    cache = M._JOURNAL_CACHE[str(folder.resolve())]
    base_offset = cache.offset
    assert base_offset > 0

    # mtime/size 未变 → 命中缓存（重读同函数也不整体解析）
    assert [t for _, _, t, _ in M._journal_entries(folder)] == ["yi"]

    # 追加一章 → 只续读尾部
    time.sleep(0.02)
    _write(journal, [{"id": "2", "title": "er", "content": "<p>2</p>"}])
    assert [t for _, _, t, _ in M._journal_entries(folder)] == ["yi", "er"]
    assert M._JOURNAL_CACHE[str(folder.resolve())].offset > base_offset

    # 半行（未写完）被忽略，补全后才进入
    time.sleep(0.02)
    with open(journal, "ab") as f:
        f.write(b'{"id":"3","title":"san","conte')
    assert [t for _, _, t, _ in M._journal_entries(folder)] == ["yi", "er"]
    time.sleep(0.02)
    with open(journal, "ab") as f:
        f.write(b'nt":"<p>3</p>"}\n')
    assert [t for _, _, t, _ in M._journal_entries(folder)] == ["yi", "er", "san"]

    # 并发追加：索引不崩、末尾一致
    for k in range(4, 14):
        _write(journal, [{"id": str(k), "title": str(k), "content": "<p>x</p>"}])
    got = M._journal_entries(folder)
    assert got[-1][1] == "13"


def test_cache_resets_when_file_truncated(tmp_path: Path) -> None:
    M._JOURNAL_CACHE.clear()
    folder = tmp_path / "b2"
    folder.mkdir(parents=True)
    journal = folder / "downloaded_chapters.jsonl"
    _write(journal, [{"id": "1", "title": "one", "content": "<p>1</p>"}])
    assert [t for _, _, t, _ in M._journal_entries(folder)] == ["one"]
    time.sleep(0.02)
    # 下载器换号/重写：文件变小 → 全量重建
    journal.write_text(json.dumps({"id": "9", "title": "new", "content": "<p>9</p>"}) + "\n", encoding="utf-8")
    assert [t for _, _, t, _ in M._journal_entries(folder)] == ["new"]
