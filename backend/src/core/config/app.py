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

    app_name: str = Field(default="Marketplace Analytics")
    environment: Environment = Field(default="local")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    # One JSON object per line instead of the human column format (P2.2).
    # Structure carried by the encoder rather than by punctuation, which is what
    # makes a user-controlled value in a log line unable to pretend to be a
    # field or a line of its own. Off locally, where a person is reading a
    # terminal; `_enforce_production_hardening` turns it on for deployed
    # environments, where a shipper is reading instead.
    log_json: bool = Field(default=False)

    @property
    def is_production(self) -> bool:
        """Return ``True`` when running in the production environment."""
        return self.environment == "production"

    @property
    def api_docs_enabled(self) -> bool:
        """Return ``True`` where the interactive API documentation may be served.

        ``/docs``, ``/redoc`` and ``/openapi.json`` publish the complete route
        inventory with every schema and parameter — a free map of the attack
        surface, and of no use to the SPA, which is written against the API
        rather than discovering it.

        The boundary is ``local``, not :attr:`is_production`, for the reason
        ``_enforce_production_hardening`` uses the same one: staging is
        internet-reachable too, so it is hardened like production.
        """
        return self.environment == "local"
