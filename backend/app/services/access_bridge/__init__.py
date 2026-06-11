"""Source Access Bridge runtime services.

Source Access Bridge is the LegadoHub-owned control layer for browser access. Source
plugins describe which capability they need; they do not own browser lifecycle,
profile storage, proxy binding, or challenge handling policy.
"""

from app.services.access_bridge.config import AccessBridgeConfig
from app.services.access_bridge.facade import SourceAccessBridge
from app.services.access_bridge.models import AccessFetchRequest, AccessFetchResult, SearchProviderHit
from app.services.access_bridge.profiles import BrowserProfileRef, make_profile_id

__all__ = [
    "AccessBridgeConfig",
    "AccessFetchRequest",
    "AccessFetchResult",
    "BrowserProfileRef",
    "SearchProviderHit",
    "SourceAccessBridge",
    "make_profile_id",
]





