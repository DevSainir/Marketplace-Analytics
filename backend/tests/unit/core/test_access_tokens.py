"""Unit tests for access-token minting and validation.

The behaviour under test is the *acceptance policy*: which tokens
:func:`decode_token` lets through and which it refuses. Every refusal here is
one an attacker would otherwise use — a forged signature, an expired token
replayed later, a token minted for a different purpose, or a payload with the
claims stripped out.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from src.core.config import settings
from src.core.security import TokenType, create_access_token, decode_token


def test_minted_token_decodes_back_to_its_subject() -> None:
    """A freshly minted token yields the user id it was issued for."""
    user_id = uuid.uuid4()

    token, expires_at = create_access_token(user_id=user_id)
    payload = decode_token(token, expected_type=TokenType.ACCESS)

    assert payload is not None
    assert payload.subject == str(user_id)
    assert expires_at > datetime.now(UTC)


def test_explicit_jti_is_preserved_for_family_binding() -> None:
    """The caller-supplied ``jti`` survives the round-trip.

    The auth service reuses the refresh-token row id as the access token's
    ``jti``, which is what ties an access token to its rotation family.
    """
    token_id = uuid.uuid4()

    token, _ = create_access_token(user_id=uuid.uuid4(), jti=token_id)
    payload = decode_token(token, expected_type=TokenType.ACCESS)

    assert payload is not None
    assert payload.jti == str(token_id)


def test_expiry_matches_the_configured_ttl(settings_override) -> None:
    """The token's lifetime is the configured access TTL, not a hard-coded one."""
    with settings_override(access_token_ttl_seconds=60):
        _, expires_at = create_access_token(user_id=uuid.uuid4())

    assert timedelta(seconds=50) < expires_at - datetime.now(UTC) <= timedelta(seconds=60)


def test_expired_token_is_rejected() -> None:
    """A token past its ``exp`` is refused however valid its signature."""
    claims = {
        "sub": str(uuid.uuid4()),
        "type": TokenType.ACCESS.value,
        "jti": str(uuid.uuid4()),
        "iat": int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
        "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
    }
    expired = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    assert decode_token(expired, expected_type=TokenType.ACCESS) is None


def test_token_signed_with_another_key_is_rejected() -> None:
    """A forged token signed with the wrong secret must not validate."""
    claims = {
        "sub": str(uuid.uuid4()),
        "type": TokenType.ACCESS.value,
        "jti": str(uuid.uuid4()),
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
    }
    forged = jwt.encode(claims, "an-attackers-own-secret-of-ample-length", algorithm="HS256")

    assert decode_token(forged, expected_type=TokenType.ACCESS) is None


def test_token_of_the_wrong_type_is_rejected() -> None:
    """The ``type`` claim is enforced, so tokens cannot be repurposed."""
    claims = {
        "sub": str(uuid.uuid4()),
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
    }
    other_type = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    assert decode_token(other_type, expected_type=TokenType.ACCESS) is None


@pytest.mark.parametrize("missing_claim", ["sub", "jti", "iat", "exp"])
def test_token_missing_a_required_claim_is_rejected(missing_claim: str) -> None:
    """A correctly signed but incomplete payload is refused, not half-trusted.

    ``decode_token`` builds a frozen payload object; accepting a token with a
    missing ``sub`` or ``iat`` would hand downstream code a ``None`` where it
    expects an identity or a revocation timestamp.
    """
    claims: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "type": TokenType.ACCESS.value,
        "jti": str(uuid.uuid4()),
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
    }
    del claims[missing_claim]
    incomplete = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    assert decode_token(incomplete, expected_type=TokenType.ACCESS) is None


def test_garbage_string_is_rejected_without_raising() -> None:
    """Malformed input returns ``None`` — the primitive stays transport-neutral.

    Raising here would force every caller into a try/except and risk a 500 on
    a trivially malformed ``Authorization`` header.
    """
    assert decode_token("not.a.jwt", expected_type=TokenType.ACCESS) is None


def test_issued_at_is_timezone_aware_for_revocation_comparison() -> None:
    """``issued_at`` must be tz-aware; the revocation check compares it to UTC.

    A naive datetime would raise ``TypeError`` inside ``get_current_user_id``
    the moment a user's sessions were revoked — i.e. exactly when the security
    control is needed.
    """
    token, _ = create_access_token(user_id=uuid.uuid4())

    payload = decode_token(token, expected_type=TokenType.ACCESS)

    assert payload is not None
    assert payload.issued_at.tzinfo is not None
    assert payload.expires_at.tzinfo is not None


def test_the_family_claim_survives_the_round_trip() -> None:
    """The lineage has to be readable from the token, or it cannot be revoked.

    ``fam`` is what lets a logout end the access tokens of *this* browser
    without touching the account's other devices (register P1.12).
    """
    family_id = uuid.uuid4()

    token, _ = create_access_token(user_id=uuid.uuid4(), family_id=family_id)
    payload = decode_token(token, expected_type=TokenType.ACCESS)

    assert payload is not None
    assert payload.family_id == str(family_id)


def test_a_token_minted_without_a_family_still_decodes() -> None:
    """Tokens issued before the claim existed must survive the deploy.

    Refusing them would sign every logged-in user out at rollout, to close a
    window that closes itself within the access TTL anyway. ``None`` is the
    signal to skip the per-family check, not to reject.
    """
    token, _ = create_access_token(user_id=uuid.uuid4())

    payload = decode_token(token, expected_type=TokenType.ACCESS)

    assert payload is not None
    assert payload.family_id is None
