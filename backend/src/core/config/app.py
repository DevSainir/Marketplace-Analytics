"""Application identity and runtime mode.

The handful of values every process reads before anything else: what the
service calls itself, which deployment it is running as, and how loudly it
logs. ``environment`` is also the switch the production-hardening guard in
:mod:`src.core.config.assembly` turns on — only ``local`` is exempt from it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings

Environment = Literal["local", "staging", "production"]


class AppSettings(BaseSettings):
    """Application identity, deployment environment and logging."""

    app_name: str = Field(default="Marketplace Service")
    environment: Environment = Field(default="local")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    @property
    def is_production(self) -> bool:
        """Return ``True`` when running in the production environment."""
        return self.environment == "production"
