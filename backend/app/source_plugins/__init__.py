"""LegadoHub Python source plugin runtime."""

from app.source_plugins.models import (
    PluginMetadata,
    LoadedPlugin,
    PluginHealth,
    SearchResult,
    BookDetail,
    ChapterItem,
    ChapterContent,
    PluginFailure,
)
from app.source_plugins.errors import (
    PluginValidationError,
    PluginExecutionError,
    PluginTimeout,
    FetchNetworkError,
    FetchHttp4xx,
    FetchHttp5xx,
    ParseEmpty,
    ParseError,
    AuthRequired,
    LoginRequired,
    PaidContentRequired,
    BrowserRequired,
    CloudflareRequired,
    RateLimited,
    UnsupportedSource,
)

__all__ = [
    "PluginMetadata",
    "LoadedPlugin",
    "PluginHealth",
    "SearchResult",
    "BookDetail",
    "ChapterItem",
    "ChapterContent",
    "PluginFailure",
    "PluginValidationError",
    "PluginExecutionError",
    "PluginTimeout",
    "FetchNetworkError",
    "FetchHttp4xx",
    "FetchHttp5xx",
    "ParseEmpty",
    "ParseError",
    "AuthRequired",
    "LoginRequired",
    "PaidContentRequired",
    "BrowserRequired",
    "CloudflareRequired",
    "RateLimited",
    "UnsupportedSource",
]




