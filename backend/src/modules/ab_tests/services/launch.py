"""Starting a test: what has to happen, in what order, before it is "Running".

Its own module because starting is the one operation in this module with a
sequence rather than a body — decide which variant opens the rotation, install
it, open its exposure, mark the test running — and because every step of it can
fail in a way that must leave the test exactly as it was. :mod:`.catalog` is the
request-scoped surface; this is the transaction that surface delegates the start
to.

The order is the invariant. WB is called **before** anything about the test is
written, so a rejected upload leaves a draft rather than a test that believes it
is running over a card showing the old picture.
"""

from __future__ import annotations

from datetime import datetime

from src.core.exceptions import ConflictError
from src.modules.ab_tests.models import AbTest, AbTestStatus
from src.modules.ab_tests.repos import AbTestRepository, ExposureRepository
from src.modules.ab_tests.services.photos import VariantInstaller


class Launcher:
    """Takes a draft or paused test to ``RUNNING``.

    Not ``TestLauncher``: pytest collects anything named ``Test*`` and then warns
    that it cannot, because this one has a constructor.
    """

    def __init__(
        self,
        *,
        tests: AbTestRepository,
        exposures: ExposureRepository,
    ) -> None:
        """Wire the launcher to the two tables a start writes.

        Args:
            tests: Where the status and the live variant are recorded.
            exposures: The audit trail of which photo was live when.
        """
        self._tests = tests
        self._exposures = exposures

    async def launch(
        self,
        *,
        test: AbTest,
        installer: VariantInstaller,
        now: datetime,
    ) -> None:
        """Put the first photo up and mark the test running.

        The rotation opens on whichever variant sorts first — "Main photo" when the
        seller marked one, since it takes position 0. It is installed like every
        other photo. That is the difference from how this worked until the
        baseline was captured off WB's CDN: back then the first turn skipped the
        upload because the picture was already on the card. A photo the seller
        chose is not, and a start that skipped it would credit the first turn to
        an image WB never showed.

        A paused test resumes on whatever photo is already installed rather than
        restarting the rotation.

        Args:
            test: The test to start, with its variants loaded.
            installer: Puts a variant's image on the card.
            now: The moment of the start, stamped on the exposure.

        Raises:
            ConflictError: If the test is already running, has finished, or
                carries no photo to install.
            IntegrationError: If WB refuses the first upload.
        """
        if test.status == AbTestStatus.RUNNING.value:
            raise ConflictError("The test is already running.")
        if test.status in {AbTestStatus.COMPLETED.value, AbTestStatus.CANCELLED.value}:
            raise ConflictError("A finished test can't be restarted.")
        if not any(not variant.is_excluded for variant in test.variants):
            raise ConflictError("Upload at least one photo before starting the test.")

        if test.active_variant_id is None:
            first = next(v for v in test.variants if not v.is_excluded)
            await installer.install(nm_id=test.nm_id, variant=first)
            await self._exposures.open(
                test_id=test.id, variant_id=first.id, activated_at=now, round_number=1
            )
            await self._tests.set_active_variant(test=test, variant_id=first.id)

        await self._tests.set_status(
            test=test,
            status=AbTestStatus.RUNNING,
            started_at=test.started_at or now,
        )


__all__ = ["Launcher"]
