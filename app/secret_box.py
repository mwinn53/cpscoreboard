"""Encrypt small secrets (the X keys) before they go into the database.

The key is ``SECRETS_KEY``: a Fernet key (``Fernet.generate_key()``), kept in SSM as
a SecureString in production, so a copy of the database or a snapshot alone doesn't
reveal the secrets. Without a key, nothing can be saved (``available`` is False).
"""

from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)


class SecretBox:
    def __init__(self, key: str):
        self._fernet = None
        if key:
            try:
                self._fernet = Fernet(key.encode())
            except (ValueError, TypeError):
                log.error("SECRETS_KEY isn't a valid Fernet key; secrets can't be saved or read")

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise RuntimeError("SECRETS_KEY is not set")
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str | None:
        if self._fernet is None or not token:
            return None
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken:
            log.error("A stored secret can't be decrypted (was SECRETS_KEY changed?)")
            return None
