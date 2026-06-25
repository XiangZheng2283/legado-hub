"""Private/plugin-side auth loader for official sources.

Discovers protocol entry files from either:
  plugins/sources/official/{source_id}/
  plugins/sources/official/{source_id}/private/

Preferred modern layout:
  manifest.json
  auth_api.py      (optional)
  cookie_auth.py   (optional)
  reviews.py       (optional)

Legacy fallback:
  private/
    manifest.json
    auth_api.py      (optional)
    cookie_auth.py   (optional)
    reviews.py       (optional)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from app.services.official_auth.contracts import (
    AuthApiContract,
    CookieAuthContract,
    PrivatePluginManifest,
    ReviewsContract,
)


class PrivatePluginLoader:
    """Load private plugin packages for official sources."""

    # Resolve relative to project root (parent of backend/)
    BASE_DIR = Path(__file__).resolve().parents[4] / "plugins" / "sources"

    def __init__(self):
        self._cache: dict[str, dict[str, Any]] = {}

    def _plugin_dir(self, plugin_id: str) -> Path | None:
        """Resolve plugin root directory for a plugin."""
        candidates = [
            self.BASE_DIR / "official" / plugin_id,
            self.BASE_DIR / plugin_id,
        ]
        for p in candidates:
            if p.exists() and p.is_dir():
                return p
        return None

    def _entry_dir(self, plugin_id: str) -> Path | None:
        """Resolve the directory containing auth/reviews entry files."""
        plugin_dir = self._plugin_dir(plugin_id)
        if not plugin_dir:
            return None
        preferred = plugin_dir
        legacy = plugin_dir / "private"
        if (preferred / "manifest.json").exists():
            return preferred
        if legacy.exists() and legacy.is_dir() and (legacy / "manifest.json").exists():
            return legacy
        return None

    def _load_module(self, entry_dir: Path, module_name: str) -> ModuleType | None:
        """Dynamically load a module from the entry directory."""
        file_path = entry_dir / f"{module_name}.py"
        if not file_path.exists():
            return None

        # Use unique module name to avoid conflicts
        unique_name = f"_private_{entry_dir.parent.name}_{entry_dir.name}_{module_name}"
        if unique_name in sys.modules:
            return sys.modules[unique_name]

        spec = __import__("importlib.util").util.spec_from_file_location(
            unique_name, str(file_path)
        )
        if not spec or not spec.loader:
            return None

        module = __import__("importlib.util").util.module_from_spec(spec)
        sys.modules[unique_name] = module
        spec.loader.exec_module(module)
        return module

    def load(self, plugin_id: str) -> dict[str, Any]:
        """Load private package for a plugin. Returns dict with capabilities."""
        if plugin_id in self._cache:
            return self._cache[plugin_id]

        result: dict[str, Any] = {
            "pluginId": plugin_id,
            "available": False,
            "manifest": None,
            "authApi": None,
            "cookieAuth": None,
            "reviews": None,
            "methods": [],
            "defaultMethod": "",
        }

        entry_dir = self._entry_dir(plugin_id)
        if not entry_dir:
            self._cache[plugin_id] = result
            return result

        # Load manifest
        manifest_path = entry_dir / "manifest.json"
        if not manifest_path.exists():
            self._cache[plugin_id] = result
            return result

        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = PrivatePluginManifest(manifest_data)
        except Exception:
            self._cache[plugin_id] = result
            return result

        result["available"] = True
        result["manifest"] = manifest
        result["methods"] = manifest.available_methods()
        result["defaultMethod"] = manifest.default_method()

        # Load optional modules
        if manifest.phone_auth:
            mod = self._load_module(entry_dir, "auth_api")
            if mod:
                # Look for a concrete class or module-level functions
                auth_api = self._resolve_contract(mod, AuthApiContract)
                result["authApi"] = auth_api

        if manifest.cookie_auth:
            mod = self._load_module(entry_dir, "cookie_auth")
            if mod:
                cookie_auth = self._resolve_contract(mod, CookieAuthContract)
                result["cookieAuth"] = cookie_auth

        if manifest.reviews:
            mod = self._load_module(entry_dir, "reviews")
            if mod:
                reviews = self._resolve_contract(mod, ReviewsContract)
                result["reviews"] = reviews

        self._cache[plugin_id] = result
        return result

    def _resolve_contract(self, module: ModuleType, contract_cls: type) -> Any:
        """Find an object in module that implements the contract.

        Priority:
        1. Class named after contract (e.g., AuthApi)
        2. Any class that subclasses the contract
        3. Module-level functions wrapped as an object
        """
        # Try exact naming convention
        expected_names = {
            AuthApiContract: ["AuthApi", "PhoneAuth", "AuthApiImpl"],
            CookieAuthContract: ["CookieAuth", "CookieAuthImpl"],
            ReviewsContract: ["Reviews", "ReviewsImpl"],
        }

        for name in expected_names.get(contract_cls, []):
            obj = getattr(module, name, None)
            if obj is not None:
                if isinstance(obj, type) and issubclass(obj, contract_cls):
                    return obj()
                # Could be pre-instantiated
                if isinstance(obj, contract_cls):
                    return obj

        # Try any class that subclasses the contract
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, contract_cls) and attr is not contract_cls:
                return attr()

        # Fallback: wrap module-level functions
        return _ModuleWrapper(module, contract_cls)

    def invalidate(self, plugin_id: str) -> None:
        self._cache.pop(plugin_id, None)

    def has_private(self, plugin_id: str) -> bool:
        return bool(self._entry_dir(plugin_id))


class _ModuleWrapper:
    """Wrap a module's top-level functions as a contract implementation."""

    def __init__(self, module: ModuleType, contract_cls: type):
        self._module = module
        self._contract = contract_cls

    def __getattr__(self, name: str):
        func = getattr(self._module, name, None)
        if func is None:
            raise AttributeError(f"{self._contract.__name__} has no attribute '{name}'")
        return func


# Global singleton
private_plugin_loader = PrivatePluginLoader()
