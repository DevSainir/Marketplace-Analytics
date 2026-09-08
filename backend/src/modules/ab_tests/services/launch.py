"""Starting a test: what has to happen, in what order, before it is «Запущен».

Its own module because starting is the one operation in this module with a
sequence rather than a body — capture the card's photo, decide which variant
opens the rotation, install it if it is not already up, open its exposure, mark
the test running — and because every step of it can fail in a way that must
leave the test exactly as it was. :mod:`.catalog` is the request-scoped surface;
this is the transaction that surface delegates the start to.

The order is the invariant. WB is called **before** anything about the test is
written, so a rejected upload leaves a draft rather than a test that believes it
is running over a card showing the old picture.
"""

from __future__ import annotations

from datetime import datetime

from src.core.exceptions import ConflictError
from src.modules.ab_tests.models import AbTest, AbTestStatus
from src.modules.ab_tests.repos import AbTestRepository, ExposureRepository, VariantRepository
from src.modules.ab_tests.services.original import PhotoEnroller
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
        variants: VariantRepository,
        exposures: ExposureRepository,
    ) -> None:
        """Wire the launcher to the three tables a start writes.

        Args:
            tests: Where the status and the live variant are recorded.
            variants: Where the captured original is filed.
            exposures: The audit trail of which photo was live when.
        """
        self._tests = tests
        self._variants = variants
        self._exposures = exposures

    async def launch(
        self,
        *,
        test: AbTest,
        installer: VariantInstaller,
        capture: PhotoEnroller,
        now: datetime,
    ) -> None:
        """Put the first photo up and mark the test running.

        The rotation opens on the card's **existing** main photo, captured here
        rather than uploaded, so the uploads are measured against the thing they
        would replace instead of only against each other. That first turn needs
        no upload at all: the photo is already on the card, and re-sending WB's
        own transcoded rendition back to WB would spend a moderation pass to
        arrive at the picture that is already there.

        When the capture comes back empty — no images on the card, or WB out of
        reach — the rotation opens on the first upload, which is what it did
        before the capture existed.

        The photo is normally already enrolled — creating the test does it, so
        the seller can see it in the list before uploading anything. Enrolling
        again here is the retry for the test whose creation ran while WB was out
        of reach; :meth:`OriginalPhotoCapture.enrol` is idempotent.

        A paused test resumes on whatever photo is already installed rather than
        restarting the rotation, and never re-captures: by then the card is
        showing a variant, not its original.

        Args:
            test: The test to start, with its variants loaded.
            installer: Puts a variant's image on the card.
            capture: Reads the card's current main photo into the rotation.
            now: The moment of the start, stamped on the exposure.

        Raises:
            ConflictError: If the test is already running, has finished, or
                carries no uploaded photo to compare against.
            IntegrationError: If WB refuses the first upload.
        """
        if test.status == AbTestStatus.RUNNING.value:
            raise ConflictError("Тест уже запущен.")
        if test.status in {AbTestStatus.COMPLETED.value, AbTestStatus.CANCELLED.value}:
            raise ConflictError("Завершённый тест нельзя запустить повторно.")
        # The card's own photo does not count towards this: a test rotating
        # nothing but the image already on the card compares it to itself.
        if not any(
            not variant.is_original and not variant.is_excluded for variant in test.variants
        ):
            raise ConflictError("Загрузите хотя бы одно фото, прежде чем запускать тест.")

        if test.active_variant_id is None:
            original = await capture.enrol(test=test, variants=self._variants)
            first = original or next(v for v in test.variants if not v.is_excluded)
            if original is None:
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
