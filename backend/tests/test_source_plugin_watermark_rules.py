from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from app.services.content_purify import compile_ad_patterns, purify_content


PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "sources" / "thirdparty"

CASES = {
    "69shuba_com": [
        "无错版本在读",
        "6＝9+ 书_吧",
        "正确内容在",
    ],
    "shuhaige_net": [
        "喜欢高武大明：从小太监到九千岁请大家收藏：(m.shuhaige.net)高武大明：从小太监到九千岁书海阁小说网更新速度全网最快。",
        "《神级插班生》无错的章节将持续在书海阁小说网小说网更新,站内无任何广告,还请大家收藏和推荐书海阁小说网！",
    ],
    "sto_com": [
        "sto9.co🎊m提醒您查看最新内容",
        "🎺sto9.com最新最快的章节更新",
        "𝘀𝘁𝗼𝟵.𝗰𝗼𝗺为您提供最快的小说更新",
        "𝖘𝖙𝖔9.𝖈𝖔𝖒为您带来最新章节",
    ],
    "lingdiankanshu_com": [
        "》零点看书全文字更新,牢记网址:www.23txti.com",
    ],
    "shumilou_top": [
        "[www.69kanbao.com]",
    ],
    "hjwzw_com": [
        "由中华百科研究会（China Encyclopedia Research Society）维护运行",
        "相关：“中文百科在线”“中文词典在线”于2008年12月28日创办",
        "供求产品价格招标知识标准信息贴吧证书",
        "本文来源：www.小shuo8.cc",
        "本站未签约的小说版权属于作者，其上传行为属网友自发上传，本条款的最终解释权属于晨曦www.小shuo8.cc。",
        "古籍群：81875285",
    ],
    "czbooks_net": [
        "哦豁，小伙伴们如果觉得52书库不错，记得收藏网址 https://www.52shuku.net/ 或推荐给朋友哦~拜托啦。",
    ],
    "twkan_com": [
        "GOOGLE搜索TWKAN",
        "【写到这里我希望读者记一下我们域名台湾小说网→𝘁𝘄𝗸𝗮𝗻.𝗰𝗼𝗺】",
    ],
}

SAFE_LINES = {
    "69shuba_com": "这本书有六九章，书吧就在街角。",
    "shuhaige_net": "她喜欢这本书，也请大家收藏这份来自朋友的礼物。",
    "sto_com": "系统提醒您查看最新内容后再回复。",
    "lingdiankanshu_com": "他在零点看书时，忽然想起了昨天的约定。",
    "shumilou_top": "https://example.com 是角色写在纸上的地址。",
    "hjwzw_com": "本文来源于作者多年的亲身经历。",
    "czbooks_net": "她说如果觉得不错，就推荐给朋友。",
    "twkan_com": "他用 Google 搜索资料，也在正文里提到 TWKAN。",
}


def _patterns(source_id: str) -> list[str]:
    metadata = yaml.safe_load(
        (PLUGIN_ROOT / source_id / "metadata.yaml").read_text(encoding="utf-8")
    )
    return metadata["adPatterns"]


@pytest.mark.parametrize("source_id", CASES)
def test_approved_watermark_rules_match_samples_without_matching_counterexamples(
    source_id: str,
) -> None:
    patterns = _patterns(source_id)
    matcher = compile_ad_patterns(patterns)

    assert all(".*" not in pattern for pattern in patterns)
    assert all(matcher.fullmatch(sample) for sample in CASES[source_id])
    assert matcher.search(SAFE_LINES[source_id]) is None

    body = f"{'正常正文。' * 20}\n{CASES[source_id][0]}\n{'后续正文。' * 20}"
    cleaned = purify_content(body, ad_patterns=patterns)
    assert CASES[source_id][0] not in cleaned
    assert "正常正文" in cleaned and "后续正文" in cleaned


def test_dxtxt_inline_watermarks_are_removed_without_dropping_host_sentences() -> None:
    source_path = PLUGIN_ROOT / "dxtxt_cc" / "source.py"
    spec = importlib.util.spec_from_file_location("_test_dxtxt_source", source_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = module.Source()

    samples = [
        (
            "会嫌弃他⊠([(ｄｘｔｘｔ．ｃｃ)])✼来⊠独行txt小？♧说站⊠？♧"
            "看最新章节？♧完整章节⊠(ｄｘｔｘｔ)•(cc)，可是在理智上他却很忐忑。",
            "会嫌弃他，可是在理智上他却很忐忑。",
        ),
        (
            "快十二点的时候卐([独行tx♂♤t小说站])卐½来卐独行tx♂♤t小说站卐"
            "♂♤看最新章节♂♤完整章节卐，金栈抵达酒店。",
            "快十二点的时候，金栈抵达酒店。",
        ),
        ("(ｄｘｔｘｔ)•(ｃｃ)", ""),
    ]

    for content, expected in samples:
        assert source._strip_injected_watermarks(content) == expected

    safe = "他打开最新章节，看完整章节后才来说明情况。"
    assert source._strip_injected_watermarks(safe) == safe
