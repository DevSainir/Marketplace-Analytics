"""Finishing a test: which photo the card keeps, and only then «Завершён».

The mirror of :mod:`.launch`. A test ends with *some* photo on the live card —
whichever the rotation last dealt — and that is rarely the one the seller wants
to keep: the table has just told them which picture earned the clicks. So the
finish takes that choice as its argument and puts the chosen photo up before
the test is closed.

The order is the same invariant as the start's. WB is called **before** anything
about the test is written, so a rejected upload leaves the test paused or running
exactly as it was, and the seller can try again, rather than a finished test
over a card that still shows a photo nobody chose.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from src.core.exceptions import ConflictError, NotFoundError
from src.modules.ab_tests.models import AbTest, AbTestStatus
from src.modules.ab_tests.repos import AbTestRepository, ExposureRepository
from src.modules.ab_tests.services.photos import VariantInstaller

#: The statuses a test can be finished from. A draft has never touched the card
#: and is deleted rather than finished; a finished one has nothing left to end.
FINISHABLE_STATUSES: frozenset[str] = frozenset(
    {AbTestStatus.RUNNING.value, AbTestStatus.PAUSED.value}
)


class Finisher:
    """Takes a running or paused test to ``CANCELLED``, leaving a chosen photo up.

    ``CANCELLED`` is the status because it is the only way a test ends now (see
    :class:`~..models.AbTestStatus`); the page calls it «Завершён».
    """

    def __init__(
        self,
        *,
        tests: AbTestRepository,
        exposures: ExposureRepository,
    ) -> None:
        """Wire the finisher to the two tables a finish writes.

        Args:
            tests: Where the status and the live variant are recorded.
            exposures: The audit trail of which photo was live when.
        """
        self._tests = tests
        self._exposures = exposures

    async def finish(
        self,
        *,
        workspace_id: uuid.UUID,
        test_id: uuid.UUID,
        keep_variant_id: uuid.UUID,
        installer: VariantInstaller,
        now: datetime,
    ) -> AbTest:
        """Put the chosen photo on the card and close the test.

        The upload is skipped only when the chosen photo is the one the rotation
        installed **and** nothing has replaced it since. A test the poller
        paused over a photo conflict has an active variant that is no longer on
        the card — somebody edited it by hand — and keeping «the current one»
        there means putting it back, not trusting the record.

        Any photo of the test may be kept, an excluded one included: exclusion
        takes a photo out of the rotation, and a finished test has no rotation.

        Args:
            workspace_id: Tenancy guard — a foreign test reads as absent.
            test_id: The test to finish.
            keep_variant_id: The photo the card should be left with.
            installer: Puts that photo on the card.
            now: The moment of the finish, stamped on the test and the exposure.

        Returns:
            The finished test.

        Raises:
            NotFoundError: If the test is not in this workspace, or the photo is
                not one of its own.
            ConflictError: If the test is not running or paused.
            IntegrationError: If WB refuses the upload — nothing is written.
        """
        test = await self._tests.get(workspace_id=workspace_id, test_id=test_id)
        if test is None:
            raise NotFoundError("Тест не найден.")
        if test.status not in FINISHABLE_STATUSES:
            raise ConflictError("Завершить можно только запущенный тест или тест на паузе.")
        keep = next((v for v in test.variants if v.id == keep_variant_id), None)
        if keep is None:
            raise NotFoundError("Фото не найдено.")

        already_up = test.active_variant_id == keep.id and test.photo_conflict_at is None
        if not already_up:
            await installer.install(nm_id=test.nm_id, variant=keep)

        await self._exposures.close_open(test_id=test.id, deactivated_at=now)
        await self._tests.set_active_variant(test=test, variant_id=keep.id)
        await self._tests.set_status(
            test=test, status=AbTestStatus.CANCELLED, finished_at=now, stopped_at=now
        )
        return test


__all__ = ["FINISHABLE_STATUSES", "Finisher"]
