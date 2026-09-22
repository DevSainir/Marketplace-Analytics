"""The recipient list is the one part of the backup encryption a machine can check.

Since 2026-09-21 the nightly archive is age-encrypted to two public keys: an
*online* one whose private half sits in `BACKUP_ENCRYPTION_IDENTITY` on the VPS
so the Sunday restore rehearsal can still run unattended, and an *offline* one
whose private half has only ever been in a password manager. The offline key is
the one that survives losing the box.

Which creates a hole nothing else closes. Gate 5a decrypts the artifact before
upload — but it can only ever do that with the online key, because the offline
key is, by construction, not here. A wrong character in the offline recipient
would therefore produce a year of archives that nobody can open, discovered on
the single day that key is all there is.

Public keys are not secrets, so the list lives in git and this file pins it.
Paired with gate 5b in `lib/dump.sh` — which counts the recipient stanzas in
every artifact before it is uploaded — that turns "we typed the right key" from
a belief into two checks: the list is what we chose, and the file was really
encrypted to all of it.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

_BACKEND = pathlib.Path(__file__).resolve().parents[3]
_BACKUP = _BACKEND / "scripts" / "backup"
_RECIPIENTS = _BACKUP / "recipients"

#: An age X25519 recipient: bech32, `age1` and 58 more characters.
_AGE_RECIPIENT = re.compile(r"^age1[02-9ac-hj-np-z]{58}$")

#: A real age private key — the full 58-character body, not the truncated
#: `AGE-SECRET-KEY-…` that documentation and comments are allowed to write.
_AGE_IDENTITY = re.compile(rb"AGE-SECRET-KEY-1[02-9AC-HJ-NP-Z]{58}")

#: The keys chosen on 2026-09-21. Changing either of these is a deliberate key
#: rotation — and a rotation that does not also keep the old key available
#: makes every archive still in the buckets unreadable, so it belongs in a
#: commit that says so, not in a passing edit.
_ONLINE_DB = "age1sjqf6h5graeeeex7ervydu284rxqfxhpydcfskh788la77n9fx4s72pdhf"
_OFFLINE_DB = "age15feryxhrdz9m6y09mr8wrerwzgj6f8ntxvhxyrdlm5aahn0t09nl4ujy86"
_OFFLINE_SECRETS = "age124fl6zy54klay937yrnujckpak28lrdjg0eel92ue3gm36kcwf9tfwwqlt"


def _recipients(name: str) -> list[str]:
    """Every line age would treat as a recipient — comments and blanks dropped."""
    text = (_RECIPIENTS / name).read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _source(relative: str) -> str:
    return (_BACKUP / relative).read_text(encoding="utf-8")


def test_the_files_are_there_to_read() -> None:
    """Guards the guard: a moved file would pass every assertion below."""
    for name in ("database.txt", "secrets.txt"):
        assert (_RECIPIENTS / name).is_file(), f"{_RECIPIENTS / name} is missing"


def test_the_database_archive_has_an_offline_reader() -> None:
    """Two recipients, and the offline one is the key from the password manager.

    One recipient would be the old symmetric scheme wearing a new name: lose
    the box, lose every archive.
    """
    recipients = _recipients("database.txt")

    assert len(recipients) == 2, f"expected exactly two recipients, got {recipients}"
    assert _ONLINE_DB in recipients, "the online key the Sunday rehearsal decrypts with is gone"
    assert _OFFLINE_DB in recipients, (
        "the offline recipient has changed — every archive already in the "
        "buckets was encrypted to the old one and this is not a passing edit"
    )


def test_the_secrets_bundle_cannot_be_read_on_the_box() -> None:
    """One recipient, offline, and none that the VPS holds the private half of.

    The bundle carries the Fernet key that unlocks every WB token inside the
    nightly archives. A machine able to decrypt both holds the whole estate,
    which is precisely what splitting them was for.
    """
    secrets = _recipients("secrets.txt")

    assert secrets == [_OFFLINE_SECRETS], f"unexpected secrets recipients: {secrets}"
    assert not set(secrets) & set(_recipients("database.txt")), (
        "a secrets recipient is also a database recipient — the online key "
        "would then open the bundle from the very box it protects against"
    )


def test_every_recipient_is_a_well_formed_age_key() -> None:
    """A truncated key is the silent failure this whole file exists to prevent."""
    for name in ("database.txt", "secrets.txt"):
        for recipient in _recipients(name):
            assert _AGE_RECIPIENT.match(recipient), f"{name}: malformed recipient {recipient}"


def test_the_archive_is_encrypted_to_the_list_and_not_to_a_passphrase() -> None:
    """Writing must go through age; the symmetric passphrase is read-only history."""
    dump = _source("lib/dump.sh")
    encrypt = re.search(r"\nencrypt_archive\(\) \{.*?\n\}", dump, re.S)
    assert encrypt, "encrypt_archive is no longer a function of that name"

    body = encrypt.group(0)
    assert "--recipients-file" in body, "the artifact is no longer encrypted to the recipient list"
    assert "--symmetric" not in body, (
        "a symmetric passphrase is back in the write path — that is the scheme "
        "with no offline reader that age replaced"
    )


def test_both_gates_run_before_anything_is_uploaded() -> None:
    """5a proves it opens here; 5b proves it also opens for the key that is not here."""
    body = re.search(r"\nencrypt_archive\(\) \{.*?\n\}", _source("lib/dump.sh"), re.S)
    assert body
    text = body.group(0)

    # 5a: the artifact is opened once before it is uploaded.
    assert "decrypt_archive" in text, "the artifact is uploaded without being opened once"
    assert "gzip -t" in text, "gate 5a no longer checks what came back out"

    # 5b: and it opens for as many keys as the list names.
    assert "count_recipient_stanzas" in text, "nothing counts the recipients on the file any more"
    assert "recipient_count" in text, (
        "the stanza count is no longer compared against the recipient list, so "
        "an artifact never encrypted to the offline key would upload clean"
    )


def test_pre_age_archives_can_still_be_opened() -> None:
    """The monthly tier keeps symmetric .gpg artifacts until 2027-09-21.

    Restoring one has to work without anybody first working out which era the
    file in their hand is from, so the dispatch is on the extension.
    """
    decrypt = re.search(r"\ndecrypt_archive\(\) \{.*?\n\}", _source("lib/dump.sh"), re.S)
    assert decrypt, "decrypt_archive is no longer a function of that name"

    body = decrypt.group(0)
    assert "*.age)" in body, "age artifacts cannot be opened"
    assert "*.gpg)" in body, (
        "the symmetric path is gone while .gpg archives are still in the buckets"
    )
    assert "BACKUP_ENCRYPTION_KEY" in body, "the .gpg arm no longer uses the old passphrase"


def test_housekeeping_sweeps_both_eras() -> None:
    """A glob matching only one suffix leaks ~100 MB a night onto a 48 GB disk.

    This VPS has gone read-only from a slow disk leak before, taking the site
    with it, which is why the sweep is asserted rather than eyeballed.
    """
    sweep = re.search(r"ls -1t [^|]*\|", _source("backup.sh"), re.S)
    assert sweep, "the local-artifact sweep has gone"

    text = sweep.group(0)
    assert "sql.gz.age" in text, "the sweep does not see age artifacts"
    assert "sql.gz.gpg" in text, "the sweep no longer removes pre-age artifacts"


def test_no_private_key_is_committed() -> None:
    """The private halves belong in .env and a password manager, never in git."""
    git = shutil.which("git")
    assert git, "git is required to know which files are tracked"
    # S603: the executable comes from `shutil.which` and the arguments are two
    # literals. Asking git is the point — "what would be published" is a
    # question only git can answer.
    tracked = subprocess.run(  # noqa: S603
        [git, "ls-files", "-z"],
        cwd=_BACKEND.parent,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")

    for path in tracked:
        if not path:
            continue
        blob = (_BACKEND.parent / path.decode()).read_bytes()
        assert not _AGE_IDENTITY.search(blob), f"an age private key is committed in {path.decode()}"
