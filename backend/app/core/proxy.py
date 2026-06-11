"""Proxy decision helpers for the plugin runtime."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProxyConfig:
    enabled: bool = False
    url: str = ""
    retry_on_failure: bool = True
    failure_status_codes: list[int] = field(default_factory=lambda: [403, 429, 451, 502, 503, 504])
    failure_error_keywords: list[str] = field(
        default_factory=lambda: ["timeout", "connection", "reset", "forbidden", "captcha", "blocked"]
    )

    @classmethod
    def from_dict(cls, data: dict) -> "ProxyConfig":
        return cls(
            enabled=data.get("enabled", False),
            url=data.get("url", ""),
            retry_on_failure=data.get("retry_on_failure", True),
            failure_status_codes=data.get("failure_status_codes", [403, 429, 451, 502, 503, 504]),
            failure_error_keywords=data.get(
                "failure_error_keywords",
                ["timeout", "connection", "reset", "forbidden", "captcha", "blocked"],
            ),
        )


@dataclass
class FetchResult:
    text: str = ""
    final_url: str = ""
    proxy_used: bool = False
    attempts: int = 0
    direct_error: str = ""
    proxy_error: str = ""
    success: bool = False


def should_retry_with_proxy(error: Exception, proxy_config: ProxyConfig) -> bool:
    """Determine whether a failed request should be retried through proxy."""
    if not proxy_config.enabled or not proxy_config.url or not proxy_config.retry_on_failure:
        return False

    error_text = str(error).lower()
    if any(str(code) in error_text for code in proxy_config.failure_status_codes):
        return True
    return any(keyword.lower() in error_text for keyword in proxy_config.failure_error_keywords)


def decide_proxy_mode(proxy_mode: str, proxy_config: ProxyConfig) -> tuple[bool, bool]:
    """Return (try_direct, try_proxy) booleans."""
    if proxy_mode == "never":
        return True, False
    if proxy_mode == "always":
        return False, proxy_config.enabled and bool(proxy_config.url)
    return True, proxy_config.enabled and bool(proxy_config.url)


