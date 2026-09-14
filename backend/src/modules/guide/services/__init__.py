"""Service layer for the reference capture.

:mod:`capture` is the orchestrator — locking, tenancy, pacing and the per-source
failure policy. :mod:`fetch` holds one walk per feed and knows nothing about
either. The name below is the whole public surface.
"""

from __future__ import annotations

from src.modules.guide.services.capture import capture_cadence

__all__ = ["capture_cadence"]
