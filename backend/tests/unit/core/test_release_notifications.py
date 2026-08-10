"""The release/deploy notification scripts under ``.github/scripts/``.

These are not part of ``src.``, but they are the only thing standing between a
production deploy and a human finding out about it, and they run exactly once
per release — the worst possible place to discover a typo. They are pure Python
with no dependencies, so they belong in the unit tier.

Two properties are pinned harder than the rest, because both were explicit
product requirements rather than incidental behaviour:

* every message is sent silently (``disable_notification``), and
* operational news reaches the maintainer only, while release news reaches
  everyone.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[4] / ".github" / "scripts"


def _load(name: str) -> types.ModuleType:
    """Import a CI script by path; it is not on the package path."""
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


notify = _load("telegram_notify")
notes = _load("release_notes_ru")


class FakeTelegram:
    """Records what would have been POSTed, and answers like a happy Telegram.

    Hand-written rather than mocked on purpose: a rename of the payload keys
    this project depends on should break the test, not slide past it.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def __call__(self, request: Any, timeout: int | None = None) -> Any:
        self.calls.append(dict(urllib.parse.parse_qsl(request.data.decode())))
        body = io.BytesIO(json.dumps({"ok": True, "result": {}}).encode())
        return _closing(body)


def _closing(body: io.BytesIO) -> Any:
    class _Ctx:
        def __enter__(self) -> io.BytesIO:
            return body

        def __exit__(self, *exc: object) -> bool:
            return False

    return _Ctx()


@pytest.fixture
def telegram(monkeypatch: pytest.MonkeyPatch) -> FakeTelegram:
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    monkeypatch.setenv("TELEGRAM_MAIN_CHAT_ID", "-100111")
    monkeypatch.setenv("WORKERS_TELEGRAM_CHAT_IDS", "-100222, -100333")
    return fake


def _run(argv: list[str], stdin: str, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["telegram_notify.py", *argv])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    return notify.main()


# --------------------------------------------------------------- the invariant


def test_every_message_is_sent_silently(
    telegram: FakeTelegram, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No notification this project sends may ring a phone.

    Backups run at 03:00 and deploys are unattended; the requirement is that
    the message is waiting in the morning, not that it wakes anyone. There is
    deliberately no flag to turn this off.
    """
    _run(["--audience", "all"], "anything", monkeypatch)

    assert telegram.calls
    assert all(call["disable_notification"] == "true" for call in telegram.calls)


def test_a_long_message_is_split_into_deliverable_pieces() -> None:
    """Telegram rejects anything over 4096 characters with a 400.

    A release with a hundred commits is exactly when the announcement matters
    most, so the length limit must never be the thing that swallows it.
    """
    pieces = notify.chunk("a line of release notes\n" * 500)

    assert len(pieces) > 1
    assert all(len(piece) < 4096 for piece in pieces)
    assert "(1/" in pieces[0]


# ------------------------------------------------------------------- audience


def test_operational_news_reaches_the_maintainer_only(
    telegram: FakeTelegram, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deploy and backup outcomes are noise to everyone but the maintainer."""
    _run(["--audience", "main"], "Deploy succeeded", monkeypatch)

    assert [call["chat_id"] for call in telegram.calls] == ["-100111"]


def test_release_news_reaches_everyone_exactly_once(
    telegram: FakeTelegram, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Releases go to the whole team — and to nobody twice.

    The maintainer's own id appearing in WORKERS_TELEGRAM_CHAT_IDS is a likely
    configuration slip, and duplicate release announcements are the kind of
    noise that trains people to ignore the channel.
    """
    monkeypatch.setenv("WORKERS_TELEGRAM_CHAT_IDS", "-100222 -100333;-100111")

    _run(["--audience", "all"], "Релиз", monkeypatch)

    assert [call["chat_id"] for call in telegram.calls] == ["-100111", "-100222", "-100333"]


def test_a_missing_bot_token_is_not_a_failed_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unannounced release is still a release; the workflow stays green."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    assert _run(["--audience", "all"], "Релиз", monkeypatch) == 0


# ------------------------------------------------------- HTML that Telegram eats


def test_list_markup_becomes_bullets_instead_of_a_400() -> None:
    """Telegram's HTML mode has no <ul>/<li>, and rejects the whole message.

    The notes are written by a language model asked for "HTML", which emits
    list tags however firmly the prompt asks it not to. Degrading them to
    bullets keeps the announcement; passing them through loses it entirely.
    """
    cleaned = notify.sanitize_html("<ul><li>Была добавлена таблица</li></ul>")

    assert "<li>" not in cleaned
    assert "<ul>" not in cleaned
    assert "• Была добавлена таблица" in cleaned


def test_unsupported_tags_are_dropped_and_stray_markup_escaped() -> None:
    """Anything Telegram cannot parse is neutralised, not forwarded.

    Two different neutralisations, both required: a recognisable-but-unsupported
    tag is removed outright, while loose angle brackets and ampersands in prose
    are escaped — either one reaching the API unhandled is a 400 and a lost
    announcement.
    """
    cleaned = notify.sanitize_html("```html\n<b>Итог</b>: <script>x</script> при a < b & c\n```")

    assert cleaned.startswith("<b>Итог</b>")
    assert "<script>" not in cleaned
    assert "a &lt; b &amp; c" in cleaned
    assert "```" not in cleaned


def test_allowed_formatting_survives() -> None:
    """Bold, code and links are the whole point of using HTML mode at all."""
    source = '<b>x</b> <code>y</code> <a href="https://example.com">z</a>'

    assert notify.sanitize_html(source) == source


# ---------------------------------------------------- notes without the network


def test_notes_fall_back_to_grouped_english_when_gemini_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A translation outage must not silence the release announcement.

    Wrong language beats no message: the team can still see that 0.2.0 shipped
    and what is in it.
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VERSION", "0.2.0")
    monkeypatch.setenv("TAG", "v0.2.0")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            "feat(finreports): add Balance table\n"
            "fix(monitoring): correct the buyout window\n"
            "chore(deps): bump nanoid\n"
        ),
    )

    notes.main()

    out = capsys.readouterr().out
    assert "Релиз v0.2.0" in out
    assert "<b>Новые функции</b>\n• <b>finreports</b>: add Balance table" in out
    assert "<b>Исправления</b>\n• <b>monitoring</b>: correct the buyout window" in out
    assert "<b>Прочее</b>\n• <b>deps</b>: bump nanoid" in out


@pytest.mark.parametrize(
    "subject",
    [
        "chore(release): v0.2.0",
        # What Release Please actually wrote on the first run: a single-package
        # manifest still invokes the Merge plugin, which throws away the
        # configured title pattern. The filter must match the family, not one
        # literal, or the bot announces itself.
        "chore: release main",
        "chore(main): release 0.2.0",
    ],
)
def test_the_release_bots_own_commit_is_not_announced(
    subject: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The release bot's own commit is the announcement, not news inside it."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VERSION", "0.2.0")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(f"{subject}\nfeat(users): add invite codes\n"),
    )

    notes.main()

    out = capsys.readouterr().out
    assert "release" not in out
    assert "add invite codes" in out


def test_an_ordinary_chore_is_still_announced(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The release-bot filter must not swallow real work.

    It matches on `chore: release …`, which is close enough to an ordinary
    `chore(deps)` subject that a careless pattern would drop dependency bumps —
    the one kind of chore the team most needs to see.
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VERSION", "0.2.0")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            "chore(deps): bump cryptography to 50.0.0\n"
            # `release\b` and not `release`: the word boundary is what keeps
            # this line from reading as the release bot.
            "chore: released the storage backfill behind a flag\n"
        ),
    )

    notes.main()

    out = capsys.readouterr().out
    assert "bump cryptography to 50.0.0" in out
    assert "released the storage backfill behind a flag" in out


# ------------------------------------------------- choosing a translator model


def test_the_newest_stable_flash_model_is_preferred() -> None:
    """Model choice is derived from the live listing, not a hardcoded guess.

    The first real release announced in English because both hardcoded names
    failed — one retired for this key's API version, one rate limited. Ranking
    what the API says it has removes that entire class of failure: flash before
    pro (this is a dozen commit subjects, not an essay), released before
    preview, and a pinned version before a `-latest` alias that moves between
    releases.
    """
    available = [
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
        "gemini-3.0-flash-preview",
        "gemini-2.0-flash",
        "gemini-flash-latest",
        "gemini-3.0-flash",
    ]

    ranked = sorted(available, key=notes.rank_model)

    assert ranked[0] == "gemini-3.0-flash"
    assert ranked.index("gemini-2.5-flash-lite") > ranked.index("gemini-2.0-flash")
    assert ranked[-1] == "gemini-2.5-pro"


def test_models_that_cannot_write_text_are_never_candidates() -> None:
    """An embedding or image model answering generateContent is still useless."""
    rejected = ["text-embedding-004", "imagen-3.0-generate", "gemini-2.5-flash-image", "gemma-3"]

    for name in rejected:
        assert any(word in name for word in notes._NOT_A_TRANSLATOR), name


# ----------------------------------------------------------- failure diagnosis


def test_an_api_failure_reports_the_reason_and_never_the_key() -> None:
    """The log must say *why*, and must not leak the credential saying it.

    Both halves were learned the hard way: a bare "HTTP 404" cost a live
    release its diagnosis, and the obvious fix — print the response body — is
    only safe because the key travels in a header and is scrubbed here anyway.
    """
    body = (
        '{"error":{"code":404,"message":"models/gemini-2.5-flash is not found '
        'for API version v1beta. key=SUPERSECRET","status":"NOT_FOUND"}}'
    )

    reason = notes._reason(404, body, "SUPERSECRET")

    assert "is not found for API version v1beta" in reason
    assert "SUPERSECRET" not in reason


def test_telegram_failures_name_the_actual_problem() -> None:
    """ "chat not found" and a markup error are both HTTP 400 and need different fixes.

    A chat the bot has never been started by cannot be fixed by re-sending, and
    a broken tag cannot be fixed by adding the recipient. The description is
    the only thing that tells them apart, and it carries no bot token.
    """
    assert notify.describe({"ok": False, "description": "Bad Request: chat not found"}) == (
        "Bad Request: chat not found"
    )


# ------------------------------------------------------------- message shape


def test_the_announcement_carries_no_repository_identity() -> None:
    """The repo is private, so its name and a GitHub link are noise to readers.

    Anyone who could open the link already knows where the code lives; everyone
    else gets a URL that 404s at them.
    """
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("VERSION", "0.2.0")
        monkeypatch.setenv("TAG", "v0.2.0")
        monkeypatch.setattr(sys, "stdin", io.StringIO("feat(users): add invite codes\n"))
        buffer = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buffer)
        notes.main()
    finally:
        monkeypatch.undo()

    out = buffer.getvalue()
    assert out.startswith("<b>Релиз v0.2.0</b>")
    assert "github.com" not in out
    assert "🚀" not in out
