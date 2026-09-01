"""Pydantic DTOs for the Users module presentation boundary.

These schemas define the *only* shapes crossing the HTTP layer. ORM models
never leak outward; services return these validated DTOs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.core.security import PASSWORD_MAX_BYTES


class UserRegisterRequest(BaseModel):
    """Payload to register a new user account."""

    email: EmailStr = Field(description="Unique account email / login.")
    password: str = Field(min_length=8, max_length=128, description="Plaintext password.")

    @field_validator("password")
    @classmethod
    def _password_within_bcrypt_limit(cls, value: str) -> str:
        """Reject passwords bcrypt would silently truncate.

        bcrypt only reads the first 72 bytes; accepting longer input would give
        users a false sense of extra entropy (multi-byte alphabets hit the
        limit well below 72 *characters*, hence a byte-level check).
        """
        if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
            raise ValueError(f"Password must not exceed {PASSWORD_MAX_BYTES} bytes (UTF-8).")
        return value


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

    @field_validator("new_password")
    @classmethod
    def _password_within_bcrypt_limit(cls, value: str) -> str:
        """Reject passwords bcrypt would silently truncate.

        The same rule registration enforces, applied here because this is the
        other door a password comes through — and a rule enforced on one of two
        doors is not enforced.
        """
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Пароль слишком длинный (максимум 72 байта).")
        return value


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
