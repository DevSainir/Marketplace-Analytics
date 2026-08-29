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
