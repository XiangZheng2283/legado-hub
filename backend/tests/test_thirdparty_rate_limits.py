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


def test_all_thirdparty_plugins_use_global_concurrency_three() -> None:
    root = Path(__file__).resolve().parents[2] / "plugins" / "sources" / "thirdparty"
    mismatched = []
    for metadata_path in sorted(root.glob("*/metadata.yaml")):
        data = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        if (data.get("rateLimit") or {}).get("perHostConcurrency") != 3:
            mismatched.append(metadata_path.parent.name)

    assert mismatched == []
