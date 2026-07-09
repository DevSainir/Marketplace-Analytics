"""Pydantic DTOs for the Users module presentation boundary.

These schemas define the *only* shapes crossing the HTTP layer. ORM models
never leak outward; services return these validated DTOs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegisterRequest(BaseModel):
    """Payload to register a new user account."""

    email: EmailStr = Field(description="Unique account email / login.")
    password: str = Field(min_length=8, max_length=128, description="Plaintext password.")


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
