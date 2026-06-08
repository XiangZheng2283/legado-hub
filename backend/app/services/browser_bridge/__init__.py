"""Browser Bridge runtime services.

Browser Bridge is the LegadoHub-owned control layer for Browserless-backed
browser access. Source plugins describe which capability they need; they do not
own browser lifecycle, profile storage, proxy binding, or challenge sessions.
"""

from app.services.browser_bridge.config import BrowserBridgeConfig
from app.services.browser_bridge.profiles import BrowserProfileRef, make_profile_id

__all__ = [
    "BrowserBridgeConfig",
    "BrowserProfileRef",
    "make_profile_id",
]
