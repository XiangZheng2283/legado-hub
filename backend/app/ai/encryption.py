"""API Key encryption at rest using Fernet symmetric encryption."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_FERNET = None


def _get_fernet():
    """Lazy-initialize Fernet from environment variable or auto-generated key."""
    global _FERNET
    if _FERNET is not None:
        return _FERNET

    from cryptography.fernet import Fernet

    key = os.environ.get("LEGADOHUB_AI_ENCRYPTION_KEY", "").strip()
    if not key:
        # Auto-generate and persist to a local key file.
        key_file = Path(__file__).resolve().parent.parent.parent / "data" / ".ai_encryption_key"
        if key_file.exists():
            key = key_file.read_text(encoding="utf-8").strip()
        if not key:
            key = Fernet.generate_key().decode("utf-8")
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_text(key, encoding="utf-8")
            logger.warning("Auto-generated AI encryption key at %s", key_file)

    if isinstance(key, str):
        key = key.encode("utf-8")
    _FERNET = Fernet(key)
    return _FERNET


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt an API key for storage. Returns a Fernet token string."""
    if not plaintext:
        return ""
    try:
        return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")
    except Exception:
        return plaintext  # Fallback: store as-is if encryption fails.


def decrypt_api_key(ciphertext: str) -> str:
    """Decrypt an API key from storage. Returns the original plaintext."""
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception:
        # Not encrypted (legacy plaintext) or corrupted — return as-is.
        return ciphertext


def is_encrypted(value: str) -> bool:
    """Heuristic check: Fernet tokens start with 'gAAAAA'."""
    return bool(value) and value.startswith("gAAAAA")
