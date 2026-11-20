"""Hashing helpers for opaque tokens that must never be stored in plaintext."""

import hashlib
import hmac
import secrets


def generate_opaque_token(nbytes: int = 32) -> str:
    """Return a URL-safe random token with high entropy."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """SHA-256 hex digest of a high-entropy opaque token.

    Tokens are 256-bit random values, so a single unsalted SHA-256 is appropriate:
    they cannot be brute-forced, and we never store the plaintext.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(token: str, token_hash: str) -> bool:
    """Constant-time comparison of a presented token against a stored hash."""
    return hmac.compare_digest(hash_token(token), token_hash)
