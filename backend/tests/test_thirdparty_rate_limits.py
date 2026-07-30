from __future__ import annotations

from pathlib import Path

import yaml


def test_all_thirdparty_plugins_declare_rate_limits() -> None:
    root = Path(__file__).resolve().parents[2] / "plugins" / "sources" / "thirdparty"
    missing: list[str] = []
    for metadata_path in sorted(root.glob("*/metadata.yaml")):
        data = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        rate_limit = data.get("rateLimit") or {}
        if not isinstance(rate_limit.get("perHostConcurrency"), int) or not isinstance(rate_limit.get("minIntervalMs"), int):
            missing.append(metadata_path.parent.name)

    assert missing == []


def test_thirdparty_plugins_use_tiered_global_concurrency() -> None:
    root = Path(__file__).resolve().parents[2] / "plugins" / "sources" / "thirdparty"
    high_capacity = {
        "biquge365_net",
        "dongtanxs_com",
        "hjwzw_com",
        "mingzw_tw",
        "lingdiankanshu_com",
        "qianyezw_com",
        "quanben5_com",
        "quexs_org",
        "shumilou_top",
        "sto_com",
        "ttkan_co",
        "uuread_tw",
        "xiaoshuohu_com",
        "yeban360_com",
        "zhswx_tw",
    }
    mismatched = []
    for metadata_path in sorted(root.glob("*/metadata.yaml")):
        data = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        expected = 6 if data.get("id") in high_capacity else 3
        if (data.get("rateLimit") or {}).get("perHostConcurrency") != expected:
            mismatched.append(metadata_path.parent.name)

    assert mismatched == []
