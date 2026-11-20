"""Application-level AES-256-GCM encryption for LinkedIn access tokens.

Wire format (versioned for future key rotation):

    v1.<key_id>.<base64url(nonce)>.<base64url(ciphertext || tag)>

Only key_id ``1`` is supported today. Decrypt rejects unknown versions and key IDs.
"""

from __future__ import annotations

import base64
import binascii
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

CURRENT_KEY_ID = "1"
_NONCE_SIZE = 12
_KEY_SIZE = 32
_PREFIX = "v1"


class TokenEncryptionError(Exception):
    """Raised when ciphertext cannot be decrypted or the key is unusable."""


class TokenEncryptor:
    """Encrypts and decrypts secrets with a single AES-256 key."""

    def __init__(self, key: bytes, *, key_id: str = CURRENT_KEY_ID) -> None:
        if len(key) != _KEY_SIZE:
            raise TokenEncryptionError(
                f"TOKEN_ENCRYPTION_KEY must decode to {_KEY_SIZE} bytes, got {len(key)}"
            )
        self._aesgcm = AESGCM(key)
        self._key_id = key_id

    @classmethod
    def from_settings_value(cls, raw: SecretStr | str) -> TokenEncryptor:
        value = raw.get_secret_value() if isinstance(raw, SecretStr) else raw
        try:
            key = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise TokenEncryptionError(
                "TOKEN_ENCRYPTION_KEY must be standard base64 encoding a 32-byte key"
            ) from exc
        return cls(key)

    def encrypt(self, plaintext: str) -> str:
        nonce = secrets.token_bytes(_NONCE_SIZE)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return f"{_PREFIX}.{self._key_id}.{_b64url(nonce)}.{_b64url(ciphertext)}"

    def decrypt(self, blob: str) -> str:
        try:
            version, key_id, nonce_b64, ciphertext_b64 = blob.split(".", 3)
        except ValueError as exc:
            raise TokenEncryptionError("encrypted token has an unexpected format") from exc
        if version != _PREFIX:
            raise TokenEncryptionError(f"unsupported encryption version {version!r}")
        if key_id != self._key_id:
            raise TokenEncryptionError(f"unknown encryption key id {key_id!r}")
        try:
            nonce = _b64url_decode(nonce_b64)
            ciphertext = _b64url_decode(ciphertext_b64)
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
        except (ValueError, binascii.Error, TokenEncryptionError) as exc:
            raise TokenEncryptionError("encrypted token could not be decrypted") from exc
        except Exception as exc:  # cryptography raises InvalidTag for tampering
            raise TokenEncryptionError("encrypted token could not be decrypted") from exc
        return plaintext.decode("utf-8")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
