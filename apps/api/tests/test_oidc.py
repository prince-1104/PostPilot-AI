"""LinkedIn OIDC ID token validation."""

from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.integrations.linkedin import LinkedInOidcError, LinkedInOidcValidator
from tests.conftest import LINKEDIN_CLIENT_ID, StaticJwks


def test_valid_id_token(make_id_token, static_jwks: StaticJwks) -> None:
    validator = LinkedInOidcValidator(client_id=LINKEDIN_CLIENT_ID, jwks_client=static_jwks)
    claims = validator.validate_id_token(make_id_token(subject="sub-42"))
    assert claims.subject == "sub-42"
    assert claims.audience == LINKEDIN_CLIENT_ID


def test_invalid_signature_rejected(
    make_id_token, static_jwks: StaticJwks, rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]
) -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_id_token(key=other_key)
    validator = LinkedInOidcValidator(client_id=LINKEDIN_CLIENT_ID, jwks_client=static_jwks)
    with pytest.raises(LinkedInOidcError):
        validator.validate_id_token(token)


def test_wrong_issuer_rejected(make_id_token, static_jwks: StaticJwks) -> None:
    token = make_id_token(issuer="https://evil.example")
    validator = LinkedInOidcValidator(client_id=LINKEDIN_CLIENT_ID, jwks_client=static_jwks)
    with pytest.raises(LinkedInOidcError, match="issuer"):
        validator.validate_id_token(token)


def test_wrong_audience_rejected(make_id_token, static_jwks: StaticJwks) -> None:
    token = make_id_token(audience="someone-else")
    validator = LinkedInOidcValidator(client_id=LINKEDIN_CLIENT_ID, jwks_client=static_jwks)
    # PyJWT rejects the audience during decode; we wrap that as LinkedInOidcError.
    with pytest.raises(LinkedInOidcError, match="validation failed"):
        validator.validate_id_token(token)


def test_expired_token_rejected(make_id_token, static_jwks: StaticJwks) -> None:
    token = make_id_token(expires_delta=timedelta(minutes=-5))
    validator = LinkedInOidcValidator(client_id=LINKEDIN_CLIENT_ID, jwks_client=static_jwks)
    with pytest.raises(LinkedInOidcError):
        validator.validate_id_token(token)


def test_legacy_issuer_accepted(make_id_token, static_jwks: StaticJwks) -> None:
    token = make_id_token(issuer="https://www.linkedin.com")
    validator = LinkedInOidcValidator(client_id=LINKEDIN_CLIENT_ID, jwks_client=static_jwks)
    claims = validator.validate_id_token(token)
    assert claims.issuer == "https://www.linkedin.com"
