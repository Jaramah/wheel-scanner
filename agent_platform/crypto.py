"""Encryption for stored agent credentials.

Credentials (subscription keys / API keys) are never stored in plaintext.
A local symmetric key is generated on first run and persisted to a
gitignored file. In production you would provide AGENT_PLATFORM_SECRET
via the environment instead so the key lives outside the filesystem.
"""

import base64
import hashlib
import os

try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAS_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover - fallback if dependency missing
    _HAS_CRYPTOGRAPHY = False


_KEY_FILE = os.path.join(os.path.dirname(__file__), ".secret.key")


def _load_or_create_key() -> bytes:
    env_secret = os.environ.get("AGENT_PLATFORM_SECRET")
    if env_secret:
        # Derive a stable 32-byte Fernet key from the provided secret.
        digest = hashlib.sha256(env_secret.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    if os.path.exists(_KEY_FILE):
        with open(_KEY_FILE, "rb") as fh:
            return fh.read().strip()

    if _HAS_CRYPTOGRAPHY:
        key = Fernet.generate_key()
    else:
        key = base64.urlsafe_b64encode(os.urandom(32))
    with open(_KEY_FILE, "wb") as fh:
        fh.write(key)
    os.chmod(_KEY_FILE, 0o600)
    return key


_KEY = _load_or_create_key()

if _HAS_CRYPTOGRAPHY:
    _FERNET = Fernet(_KEY)


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    if _HAS_CRYPTOGRAPHY:
        return _FERNET.encrypt(plaintext.encode("utf-8")).decode("utf-8")
    # Fallback: XOR obfuscation (only if cryptography is unavailable).
    raw = plaintext.encode("utf-8")
    key = _KEY
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return "xor$" + base64.urlsafe_b64encode(out).decode("utf-8")


def decrypt(token: str) -> str:
    if not token:
        return ""
    if token.startswith("xor$"):
        raw = base64.urlsafe_b64decode(token[4:].encode("utf-8"))
        key = _KEY
        out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
        return out.decode("utf-8")
    if _HAS_CRYPTOGRAPHY:
        try:
            return _FERNET.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            return ""
    return ""


def mask(plaintext: str) -> str:
    """Return a safe, non-reversible hint for display in the UI."""
    if not plaintext:
        return ""
    if len(plaintext) <= 8:
        return "•" * len(plaintext)
    return plaintext[:4] + "…" + plaintext[-4:]
