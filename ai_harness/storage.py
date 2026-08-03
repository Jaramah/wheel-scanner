"""SQLite-backed user store for the AI Harness.

Users are keyed by their OAuth subject (`sub`). Each user's Anthropic API key
is encrypted at rest with a Fernet key derived from the app secret.
"""

import base64
import hashlib
import os
import sqlite3
import threading

from cryptography.fernet import Fernet, InvalidToken

INSTANCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance")
DB_PATH = os.path.join(INSTANCE_DIR, "harness.db")
SECRET_PATH = os.path.join(INSTANCE_DIR, "secret.key")


def load_secret() -> str:
    """App secret: HARNESS_SECRET_KEY env, else a generated key persisted on disk."""
    env = os.environ.get("HARNESS_SECRET_KEY")
    if env:
        return env
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    if os.path.exists(SECRET_PATH):
        with open(SECRET_PATH) as f:
            return f.read().strip()
    secret = base64.urlsafe_b64encode(os.urandom(32)).decode()
    with open(SECRET_PATH, "w") as f:
        f.write(secret)
    os.chmod(SECRET_PATH, 0o600)
    return secret


class Storage:
    def __init__(self, secret: str, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._fernet = Fernet(
            base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        )
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS users (
                       sub         TEXT PRIMARY KEY,
                       email       TEXT,
                       name        TEXT,
                       picture     TEXT,
                       api_key_enc TEXT,
                       created_at  TEXT DEFAULT (datetime('now'))
                   )"""
            )
            self._conn.commit()

    def upsert_user(self, sub: str, email: str, name: str, picture: str) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO users (sub, email, name, picture) VALUES (?, ?, ?, ?)
                   ON CONFLICT(sub) DO UPDATE SET email=excluded.email,
                       name=excluded.name, picture=excluded.picture""",
                (sub, email, name, picture),
            )
            self._conn.commit()

    def get_user(self, sub: str):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE sub = ?", (sub,)
            ).fetchone()
        return dict(row) if row else None

    def set_api_key(self, sub: str, api_key: str | None) -> None:
        enc = self._fernet.encrypt(api_key.encode()).decode() if api_key else None
        with self._lock:
            self._conn.execute(
                "UPDATE users SET api_key_enc = ? WHERE sub = ?", (enc, sub)
            )
            self._conn.commit()

    def get_api_key(self, sub: str) -> str | None:
        user = self.get_user(sub)
        if not user or not user["api_key_enc"]:
            return None
        try:
            return self._fernet.decrypt(user["api_key_enc"].encode()).decode()
        except InvalidToken:
            # Secret changed since the key was stored; the user must re-enter it.
            return None
