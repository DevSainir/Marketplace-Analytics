"""A/B-tests settings: where variant photos are kept.

The originals stay on disk rather than in Postgres (ten multi-megabyte images
per test would ride along with every query touching a variant) or in S3 (this
the precedent; a bind mount replaces the directory without a code change.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class AbTestsSettings(BaseSettings):
    """Where uploaded A/B variant images live."""

    # Relative paths resolve against the backend working directory. Every
    # variant is written as ``<root>/<test_id>/<sha256><suffix>``, so the tree
    # stays browsable when an upload has to be inspected by hand.
    ab_tests_media_dir: str = Field(default=".data/ab-tests")
