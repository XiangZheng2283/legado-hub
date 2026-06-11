"""Tests for So Novel rule inspector."""

from pathlib import Path

from scripts.inspect_so_novel_rules import inspect_rules

SEED_DIR = Path(__file__).resolve().parents[3] / "plugins" / "seeds" / "so-novel"


def test_inspector_counts():
    result = inspect_rules(
        main_path=SEED_DIR / "main.json",
        proxy_required_path=SEED_DIR / "proxy-required.json",
        rate_limit_path=SEED_DIR / "rate-limit.json",
        cloudflare_path=SEED_DIR / "cloudflare.json",
    )
    assert result["totalRules"] > 0
    assert result["searchCapable"] >= 0
    assert isinstance(result["simpleCandidates"], list)
    assert isinstance(result["proxyRequiredIds"], list)
    assert isinstance(result["rateLimitIds"], list)
    assert isinstance(result["cloudflareIds"], list)


def test_inspector_excludes_cloudflare():
    result = inspect_rules(
        main_path=SEED_DIR / "main.json",
        cloudflare_path=SEED_DIR / "cloudflare.json",
    )
    cloudflare_ids = set(result["cloudflareIds"])
    simple_ids = {c["id"] for c in result["simpleCandidates"]}
    # Simple candidates should not include cloudflare entries
    assert simple_ids.isdisjoint(cloudflare_ids)


def test_inspector_deterministic():
    result1 = inspect_rules(
        main_path=SEED_DIR / "main.json",
        proxy_required_path=SEED_DIR / "proxy-required.json",
        rate_limit_path=SEED_DIR / "rate-limit.json",
        cloudflare_path=SEED_DIR / "cloudflare.json",
    )
    result2 = inspect_rules(
        main_path=SEED_DIR / "main.json",
        proxy_required_path=SEED_DIR / "proxy-required.json",
        rate_limit_path=SEED_DIR / "rate-limit.json",
        cloudflare_path=SEED_DIR / "cloudflare.json",
    )
    assert result1 == result2






