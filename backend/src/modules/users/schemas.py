"""Pydantic DTOs for the Users module presentation boundary.

These schemas define the *only* shapes crossing the HTTP layer. ORM models
never leak outward; services return these validated DTOs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.core.exceptions import UserInputError
from src.core.security import PASSWORD_MAX_BYTES


def _validate_password(value: str) -> str:
    """Apply every rule a new password must satisfy.

    One function rather than one per schema, because registration and password
    reset are two doors into the same thing and a rule enforced on one of them
    is not enforced. `PasswordRules.vue` states these to the user; the two must
    be changed together or the form starts promising something the API refuses.

    What is deliberately NOT here: a digit or a punctuation requirement, and any
    maximum on repeated characters. Length plus the breach check
    (:mod:`src.integrations.pwned`) is what actually keeps a password out of a
    wordlist — composition rules mostly produce `Parol1!`.

    Args:
        value: The submitted plaintext password.

    Returns:
        The password unchanged.

    Raises:
        ValueError: Rendered to the client by the 422 handler, in Russian.
    """
    # bcrypt reads only the first 72 BYTES and silently ignores the rest, so a
    # longer password would give a false sense of extra entropy. Bytes, not
    # characters: Cyrillic is two bytes apiece and reaches the limit at ~36.
    if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise UserInputError(f"Пароль слишком длинный (максимум {PASSWORD_MAX_BYTES} байт).")
    # `str.islower`/`isupper` are Unicode-aware, so «пароль» and «ПАРОЛЬ» count
    # exactly as their Latin equivalents do. An all-Cyrillic password is a
    # first-class one here and must not be refused for being Cyrillic.
    if not any(char.islower() for char in value):
        raise UserInputError("Пароль должен содержать хотя бы одну строчную букву.")
    if not any(char.isupper() for char in value):
        raise UserInputError("Пароль должен содержать хотя бы одну заглавную букву.")
    return value


class UserRegisterRequest(BaseModel):
    """Payload to register a new user account."""

    email: EmailStr = Field(description="Unique account email / login.")
    password: str = Field(min_length=8, max_length=128, description="Plaintext password.")

    _check_password = field_validator("password")(staticmethod(_validate_password))


class UserLoginRequest(BaseModel):
    """Payload to authenticate with email + password."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserRead(BaseModel):
    """Public representation of a user account."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    is_active: bool
    role: str
    created_at: datetime


class TokenPairResponse(BaseModel):
    """Access-token response body.

    The refresh token itself is delivered out-of-band via an HttpOnly cookie and
    is therefore intentionally absent from this JSON body.
    """

    access_token: str = Field(description="Short-lived bearer access token.")
    token_type: str = Field(default="bearer")
    expires_at: datetime = Field(description="Access-token absolute expiry (UTC).")


class IssuedTokens(BaseModel):
    """Internal service result carrying both tokens plus cookie metadata.

    Returned by the auth service to the router, which sets the refresh cookie
    and strips the raw secret out of the JSON response.
    """

    access_token: str
    access_expires_at: datetime
    refresh_secret: str
    refresh_expires_at: datetime


class SessionsRevokedResponse(BaseModel):
    """Result of ending every session of one account."""

    revoked: int = Field(
        description=(
            "Refresh rows revoked. Zero is a normal answer — an account with no "
            "live session — not a failure, and deliberately does not say whether "
            "the account exists."
        )
    )


class SessionRead(BaseModel):
    """One live login lineage, as its owner sees it.

    Carries no token, no hash and no id of anything but the lineage itself —
    ending a session needs the family id and nothing else, and a response DTO is
    where a secret would escape if one ever could.

    ``user_agent`` travels raw. Turning it into «Chrome на macOS» is the SPA's
    job: it is presentation, it changes with every browser release, and a string
    the parser does not recognise should be shown as nothing rather than as a
    confident guess about a device somebody is deciding whether to trust.
    """

    model_config = ConfigDict(from_attributes=True)

    #: The refresh-token family — what "a session" actually is here.
    family_id: uuid.UUID
    user_agent: str | None = None
    ip_address: str | None = None
    #: When the login happened.
    started_at: datetime
    #: When this lineage last rotated — a sign of life within one access TTL.
    last_seen_at: datetime
    #: Whether this is the session asking. ``False`` for every row when the
    #: caller's token predates the ``fam`` claim: unknown is not "yes".
    is_current: bool = False


class PasswordChangeRequest(BaseModel):
    """Payload for a signed-in account changing its own password.

    The current password is part of the payload, not decoration: without it
    anyone holding a live session could lock the owner out of their own account.
    No mailed code — see :mod:`src.modules.users.services.password_change` for
    why one would prove nothing here.
    """

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128, description="The replacement.")

    _check_password = field_validator("new_password")(staticmethod(_validate_password))


class PasswordChangedResponse(BaseModel):
    """What changed, once the password did."""

    other_sessions_ended: int = Field(
        description=(
            "How many other sessions were signed out. Zero is normal for an "
            "account used on one device."
        )
    )


class EmailConfirmRequest(BaseModel):
    """Payload proving control of an address with a mailed code."""

    email: EmailStr = Field(description="The address being confirmed.")
    code: str = Field(min_length=6, max_length=10, description="The code from the message.")


class EmailResendRequest(BaseModel):
    """Payload asking for a fresh confirmation code."""

    email: EmailStr = Field(description="The address to send a new code to.")


class PasswordResetRequest(BaseModel):
    """Payload asking for a password-reset code."""

    email: EmailStr = Field(description="The account's address.")


class PasswordResetConfirmRequest(BaseModel):
    """Payload setting a new password against a mailed code."""

    email: EmailStr = Field(description="The account's address.")
    code: str = Field(min_length=6, max_length=10, description="The code from the message.")
    new_password: str = Field(min_length=8, max_length=128, description="The replacement password.")

    _check_password = field_validator("new_password")(staticmethod(_validate_password))


class AcceptedResponse(BaseModel):
    """The uniform answer of an endpoint that must not disclose anything.

    Both recovery request endpoints return this, always, whatever they found.
    A response that varied — a 404 for an unknown address, a different message
    for a disabled account — would turn the recovery form into the account
    enumeration oracle ``/login`` is carefully not.
    """

    detail: str = Field(
        default="Если такой адрес зарегистрирован, письмо с кодом отправлено.",
        description="Deliberately says nothing about whether the address exists.",
    )
