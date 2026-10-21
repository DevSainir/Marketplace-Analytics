"""Encrypting to a public key means anyone can write an artifact we would accept.

This is the one property the move from `gpg --symmetric` to age gave up, and it
is worth stating plainly because nothing about the new scheme looks weaker. The
passphrase could not be used to *make* an archive without also being the thing
that opened one — encrypting and authenticating were the same act. An age
recipient is public, and ours is in git, so anyone who can write into a bucket
can leave an artifact there that decrypts cleanly, passes `gzip -t`, and
restores into PostgreSQL without complaint.

The S3 user-metadata checksum does not help: the object and its metadata are
written with the same credentials, so it attests to the transfer and not to who
made the file. Two records outside that blast radius do help, and this file
pins both — a ledger on the server, which the bucket's credentials cannot reach,
and the checksum in the weekly Telegram report, which not even the server can
reach once it has been sent.
"""

from __future__ import annotations

import pathlib
import re

_BACKUP = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "backup"


def _source(relative: str) -> str:
    return (_BACKUP / relative).read_text(encoding="utf-8")


def _summary_body() -> str:
    """The multi-line `SUMMARY="…"` assignment, read line by line.

    Not a regex: the body interpolates `$(human_bytes "…")`, so anything
    matching up to the next double quote stops one line in and would pass this
    file while the checksum was missing.
    """
    lines = _source("backup.sh").splitlines()
    for index, line in enumerate(lines):
        if not line.startswith('SUMMARY="'):
            continue
        body = [line]
        for following in lines[index + 1 :]:
            body.append(following)
            if following.endswith('"'):
                return "\n".join(body)
    raise AssertionError("the report body is no longer a SUMMARY assignment")


def test_the_scripts_are_there_to_read() -> None:
    """Guards the guard: a moved file would pass every assertion below."""
    for relative in ("backup.sh", "restore.sh", "lib/dump.sh"):
        assert (_BACKUP / relative).is_file(), f"{relative} is missing"


def test_every_artifact_is_recorded_when_it_is_written() -> None:
    """The ledger is only a record of provenance if nothing skips it."""
    backup = _source("backup.sh")

    assert "record_artifact_sha" in backup, (
        "artifacts are uploaded without the box recording what it wrote"
    )
    # Recorded before the upload, not after: a push that fails halfway still
    # has to leave evidence of what the artifact was.
    recorded_at = backup.index("record_artifact_sha")
    uploaded_at = backup.index("upload_all")
    assert recorded_at < uploaded_at, "the checksum is recorded after the upload, not before"


def test_the_secrets_bundle_is_recorded_too() -> None:
    """A forged bundle is worse than a forged archive, not better.

    It cannot be read back here — that is the design — but being unreadable to
    us does nothing about being forgeable by anyone with the public key. What
    gets restored from a bundle is the `.env` a rebuilt server will run on.
    """
    bundle = _source("backup_secrets.sh")

    assert "record_artifact_sha" in bundle, (
        "the secrets bundle is uploaded with no record of what was written"
    )
    assert bundle.index("record_artifact_sha") < bundle.index("upload_all"), (
        "the bundle checksum is recorded after the upload, not before"
    )


def test_the_weekly_report_carries_the_checksum() -> None:
    """A checksum that never leaves the server cannot outlive the server.

    The Sunday message is the only copy that survives an attacker who owns the
    server, because it is already in somebody else's chat by then.
    """
    summary = _summary_body()
    assert "${ENCRYPTED_SHA}" in summary, (
        "the weekly report no longer carries the artifact checksum, so a "
        "swapped object in a bucket would restore unnoticed"
    )


def test_a_download_is_checked_against_what_this_box_wrote() -> None:
    """`fetch` must compare against the ledger, not only the object's metadata."""
    fetch = re.search(r"cmd_fetch\(\) \{.*?\n\}", _source("restore.sh"), re.S)
    assert fetch, "cmd_fetch is no longer a function of that name"

    body = fetch.group(0)
    assert "recorded_artifact_sha" in body, (
        "a fetched artifact is trusted on the strength of metadata written by "
        "the same credentials that wrote the object"
    )
    assert "die " in body, "a mismatch against the local record no longer stops the restore"


def test_an_unknown_artifact_warns_rather_than_passing_quietly() -> None:
    """Restoring onto a fresh server is the normal case, and it has no ledger.

    It must not fail — that would make the disaster worse — and it must not
    stay silent either, or the check quietly becomes optional exactly when it
    matters most.
    """
    fetch = re.search(r"cmd_fetch\(\) \{.*?\n\}", _source("restore.sh"), re.S)
    assert fetch
    body = fetch.group(0)

    unknown = re.search(r'if \[ -z "\$\{recorded\}" \]; then\n(.*?)\n    elif', body, re.S)
    assert unknown, "the no-local-record branch has gone"
    assert "warn " in unknown.group(1), "an unrecorded artifact is accepted without a word"


def test_the_ledger_is_append_only_in_shape() -> None:
    """`>>`, never `>`. A rewritten ledger is not a record of anything."""
    record = re.search(r"record_artifact_sha\(\) \{.*?\n\}", _source("lib/dump.sh"), re.S)
    assert record, "record_artifact_sha is no longer a function of that name"

    body = record.group(0)
    assert ">>" in body, "the ledger is not appended to"
    assert not re.search(r"[^>]>\s*\"\$\{ledger\}\"", body), "the ledger is truncated on write"
