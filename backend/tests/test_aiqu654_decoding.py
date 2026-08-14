from __future__ import annotations

import importlib.util
from pathlib import Path


SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "sources"
    / "thirdparty"
    / "aiqu654_com"
    / "source.py"
)
SPEC = importlib.util.spec_from_file_location("test_aiqu654_decoding_source", SOURCE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class _Context:
    @staticmethod
    def clean_text(value: str) -> str:
        return " ".join(value.split())

    @staticmethod
    def decode_text(value: bytes, charset: str | None = None) -> str:
        encodings = [charset] if charset else ["utf-8-sig", "utf-8", "gb18030", "gbk"]
        for encoding in encodings:
            try:
                return value.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
        return value.decode("utf-8", errors="replace")


def test_gbk_txt_with_numeric_content_decodes_without_mojibake() -> None:
    raw = "第1章 数字123：天启预报\n这是中文正文，包含数字2026和拉丁ABC。\n第2章 继续\n下一章正文。\n".encode("gb18030")
    source = MODULE.Source()
    ctx = _Context()

    records = source._chapter_records(ctx, raw)
    content = source._chapter_text(ctx, raw[records[0]["start"] : records[0]["end"]])

    assert records[0]["title"] == "第1章 数字123：天启预报"
    assert "中文正文" in content
    assert "数字2026" in content
    assert "�" not in content
