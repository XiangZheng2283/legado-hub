"""Challenge-page detection helpers for source runtime."""

from __future__ import annotations


CLOUDFLARE_MARKERS = (
    "Just a moment...",
    "Cloudflare",
    "cf_chl_",
    "cf-turnstile",
    "onloadTurnstileCallback",
    "challenges.cloudflare.com/turnstile",
    "turnstile/v0/api.js",
)

BROWSER_CHALLENGE_MARKERS = (
    "aegis_challenge",
    "aegis_challenge_verify",
)


def _sample(html: str, limit: int = 4000) -> str:
    return (html or "")[:limit]


def looks_like_cloudflare_challenge(html: str) -> bool:
    """Return true when a response looks like Cloudflare/Turnstile verification."""
    sample = _sample(html)
    return any(marker in sample for marker in CLOUDFLARE_MARKERS)


def looks_like_browser_challenge(html: str) -> bool:
    """Return true when a response looks like a non-Cloudflare browser challenge."""
    sample = _sample(html)
    return any(marker in sample for marker in BROWSER_CHALLENGE_MARKERS)


def looks_like_any_challenge(html: str) -> bool:
    """Return true when a response requires browser/manual verification."""
    return looks_like_cloudflare_challenge(html) or looks_like_browser_challenge(html)
