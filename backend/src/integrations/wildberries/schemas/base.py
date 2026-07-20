"""Shared base model for all raw WildBerries payload schemas.

The raw models mirror the *nested* shape WB returns on the wire. They are
deliberately permissive (``extra="ignore"``) because WB frequently adds fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RawBase(BaseModel):
    """Base config for all raw WB payload models."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)
