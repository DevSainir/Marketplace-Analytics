"""A/B-tests settings: where variant photos are kept.

Object storage, not the container filesystem. The upload lands in the **api**
container and the rotation reads the same bytes back in the **worker**, so a
local directory means the poller cannot find what the user uploaded — the first
photo would go up (the api installs it synchronously) and every rotation after
it would fail. A named volume would fix that and still lose everything on a host
rebuild, while the photos have to outlive a multi-day test.

Not Postgres either: ten multi-megabyte originals per test would ride along with
every query that touches a variant.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class AbTestsSettings(BaseSettings):
    """Where uploaded A/B variant images live."""

    # Key prefix inside the bucket. Object storage has no directories — the
    # prefix materialises on the first PUT — so nothing has to be created in
    # advance. Every variant is stored as
    # ``<prefix>/<test_id>/<sha256><suffix>``, which keeps the listing
    # browsable when an upload has to be inspected by hand.
    ab_tests_media_prefix: str = Field(default="ab-tests")
    # Bucket and endpoint. Defaults point at the Hoster bucket already
    # configured for this deployment: same provider as the VPS, so a rotation
    # reading a photo back does not cross a border on every swap.
    # Each falls back to the S3_HOSTER_* variables this deployment already
    # carries, so the bucket needs no new environment entry — and can still be
    # pointed elsewhere with the AB_TESTS_* name when the photos should not
    # share a bucket with whatever else uses that one.
    ab_tests_s3_bucket: str = Field(
        default="", validation_alias=AliasChoices("AB_TESTS_S3_BUCKET", "S3_HOSTER_BUCKET")
    )
    ab_tests_s3_endpoint_url: str = Field(
        default="",
        validation_alias=AliasChoices("AB_TESTS_S3_ENDPOINT_URL", "S3_HOSTER_URL"),
    )
    ab_tests_s3_region: str = Field(
        default="ru-1",
        validation_alias=AliasChoices("AB_TESTS_S3_REGION", "HOSTER_DEFAULT_REGION_NAME"),
    )
    ab_tests_s3_access_key: str = Field(
        default="",
        validation_alias=AliasChoices("AB_TESTS_S3_ACCESS_KEY", "S3_HOSTER_ACCESS_KEY"),
    )
    ab_tests_s3_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("AB_TESTS_S3_SECRET_KEY", "S3_HOSTER_SECRET_ACCESS_KEY"),
    )
    # How many cabinets one polling pass reads at the same time.
    #
    # The pass used to walk them one at a time, and that turned independent
    # waits into a queue: WB's rate bucket is per SELLER TOKEN, so two cabinets
    # never compete, but a sequential loop still sleeps through one cabinet's
    # twenty seconds before starting the next one's. Twenty cabinets needing one
    # extra batch each cost four hundred seconds of a three-hundred-second pass
    # for no reason WB imposed.
    #
    # Sixteen because the ceiling is the database, not WB: a cabinet holds at
    # most one session at a time and only briefly — the token read is closed
    # before the WB calls begin — so sixteen sits inside this process's pool of
    # ten plus twenty overflow with room to spare, and four prefork workers
    # cannot together outrun Postgres's hundred connections.
    ab_tests_poll_concurrency: int = Field(default=16, ge=1, le=64)

    # Local fallback for tests and for a developer with no bucket: when the
    # bucket is unset the store writes to this directory instead. It is NOT a
    # deployment option — a deployed api and worker do not share one.
    ab_tests_media_dir: str = Field(default=".data/ab-tests")
