"""AES-GCM token encryption."""

import base64
import secrets

import pytest
from pydantic import ValidationError

from app.core.security import TokenEncryptionError, TokenEncryptor
from tests.conftest import SettingsFactory


def test_encrypt_decrypt_round_trip(token_encryptor: TokenEncryptor) -> None:
    blob = token_encryptor.encrypt("super-secret-access-token")
    assert blob.startswith("v1.1.")
    assert "super-secret-access-token" not in blob
    assert token_encryptor.decrypt(blob) == "super-secret-access-token"


def test_each_encryption_uses_a_fresh_nonce(token_encryptor: TokenEncryptor) -> None:
    first = token_encryptor.encrypt("same-plaintext")
    second = token_encryptor.encrypt("same-plaintext")
    assert first != second


def test_tampered_ciphertext_is_rejected(token_encryptor: TokenEncryptor) -> None:
    blob = token_encryptor.encrypt("token")
    parts = blob.split(".")
    parts[-1] = parts[-1][:-4] + "xxxx"
    with pytest.raises(TokenEncryptionError):
        token_encryptor.decrypt(".".join(parts))


def test_invalid_encryption_key_rejected_at_construction() -> None:
    with pytest.raises(TokenEncryptionError, match="base64"):
        TokenEncryptor.from_settings_value("not-base64!!")


def test_wrong_key_length_rejected() -> None:
    short = base64.b64encode(b"too-short").decode()
    with pytest.raises(TokenEncryptionError, match="32 bytes"):
        TokenEncryptor.from_settings_value(short)


def test_settings_reject_empty_encryption_key(settings_factory: SettingsFactory) -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        settings_factory(token_encryption_key="")


def test_unknown_key_id_rejected(token_encryptor: TokenEncryptor) -> None:
    blob = token_encryptor.encrypt("token")
    bad = blob.replace(".1.", ".9.", 1)
    with pytest.raises(TokenEncryptionError, match="unknown encryption key id"):
        token_encryptor.decrypt(bad)


def test_decrypted_value_never_appears_in_blob(token_encryptor: TokenEncryptor) -> None:
    secret = secrets.token_urlsafe(24)
    blob = token_encryptor.encrypt(secret)
    assert secret not in blob
