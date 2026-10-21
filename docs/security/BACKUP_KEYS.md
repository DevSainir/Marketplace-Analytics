# Backup keys: the scheme, its reasoning, its limits

Database backups are encrypted with `age` to two recipients, replacing an earlier symmetric
`gpg` passphrase. This document explains how the key scheme works and why it is built this way.
What the backup job itself does and which gates it runs is in `backend/scripts/backup/README.md`.
The wider set of security controls is in [SECURITY_DESIGN.md](SECURITY_DESIGN.md).

All key values below are placeholders. The real public keys are in
`backend/scripts/backup/recipients/`; no private key is in this repository.

## Why a key has two halves

The old scheme was symmetric: one passphrase both encrypted and decrypted. A lock with one key
for "close" and "open". The consequence: for the host to make backups, the key had to live on that
host — which means the host also held the way to read everything already accumulated.

An asymmetric pair separates the two actions:

* The **public key** (`age1<public-key>`) can only **en**crypt. The private key cannot be derived
  from it. It can be printed in git, in a chat, on a T-shirt. Whoever **writes** a backup needs it.
* The **private key** (`AGE-SECRET-KEY-1<private-key>`) can **de**crypt. Whoever **restores**
  needs it.

A self-latching lock: anyone can snap it shut, only the key holder can open it.

The public halves live in `backend/scripts/backup/recipients/`. That is not a leak, it is where
they belong — and precisely because they are not secret, they could be pinned by a test (see
"What the machine checks").

## What an artifact looks like inside

`age` does not encrypt the file twice for two recipients. It:

1. generates a random **file key** — single-use, for this archive only;
2. encrypts the whole archive symmetrically with it (symmetric is fast);
3. **wraps the file key separately for each recipient**, using that recipient's public key.

The result is two small envelopes holding the same key: the first opens only with the offline
key, the second only with the online one.

```
age-encryption.org/v1
-> X25519 <ephemeral-share-1>         ← envelope #1
<wrapped-file-key-1>
-> X25519 <ephemeral-share-2>         ← envelope #2
<wrapped-file-key-2>
--- <header-mac>                      ← header MAC
<ciphertext follows>
```

So a two-recipient file is not twice the size, only a couple of hundred bytes larger. And that is
what makes gate 5b possible: counting the `-> X25519` lines tells you how many keys can actually
open the artifact.

## Three pairs and who holds them

| Pair | Private half | Public half | Used by |
| --- | --- | --- | --- |
| online, database | `BACKUP_ENCRYPTION_IDENTITY` in `backend/.env` on the backup host | `recipients/database.txt` | the host itself — every night and every Sunday |
| offline, database | a password manager; never on a server | `recipients/database.txt` | a person, when the host is gone |
| offline, secrets | a password manager | `recipients/secrets.txt` | a person, when everything is rebuilt from scratch |

**At night** `backup.sh` reads only the **public** keys from `database.txt` — both of them — and
encrypts the dump to them. No private key is needed for this step at all: sealing the envelope
takes nothing secret.

The host needs the online private key for exactly two things, and both are checks:

* **gate 5a**, right after encryption: decrypt what was just written and confirm it unpacks into
  a valid gzip;
* **gate 6**, on Sundays: decrypt the whole artifact and load it into a clean PostgreSQL in an
  isolated container — proving that it restores.

Without a private key on the machine, both checks are impossible. **That is the only reason the
online key exists.**

The offline keys play no part in routine operation: no script reads them, and none could.

## Why two keys rather than one

They protect different things, and are kept apart for that reason.

The database archives contain WB tokens encrypted with Fernet. The Fernet key itself lives in
`.env`, that is, in the secrets bundle. While these are different keys, leaking one yields half:
leak the database key and the attacker gets archives in which the tokens are still ciphertext.
Collapse them into one and the same leak hands over everything at once: every customer's live
tokens, the Postgres password and the credentials for both buckets.

But the main argument is **different frequency of use**. The database key is a working key: it
comes out for a drill, it will come out for a restore, it may be handed to another person so they
can bring up a copy. Every use is a chance for it to end up in shell history, in a temporary file,
on someone else's laptop. The secrets key ideally never comes out at all. Putting what you touch
regularly and what you never touch behind one key drags the second up to the risk of the first.

A side benefit: with two keys, a person can be allowed to restore the database without being
given the deployment's passwords.

**Where this logic fails.** If both keys sit in one password manager under one master password,
the separation buys less than it seems: compromising the manager takes both. The gain is real
only if they are handled differently.

## What the machine checks, and what it does not

Asymmetry creates a gap the symmetric scheme did not have: **the correctness of the offline
recipient cannot be checked on the host**, because the key is not there. A one-character error
yields a year of archives nobody can open, discovered on the day that key is all that is left.

Two mechanisms close it, and neither of them is "being careful":

* **gate 5b** (`lib/dump.sh`) counts `-> X25519` in every artifact and refuses to upload a file
  carrying fewer envelopes than there are recipients in the list;
* `backend/tests/unit/core/test_backup_encryption_recipients.py` pins both public strings, so an
  accidental edit to `recipients/` fails CI.

**What nobody checks automatically:** that the private key in the password manager matches the
public key in the list. That is a manual drill, on a machine that is not the backup host:

```bash
backend/scripts/backup/restore.sh fetch cloudfare daily/<file>.sql.gz.age
```

```bash
age -d -i <file-with-offline-key> <downloaded>.sql.gz.age | gzip -t && echo OK
```

Repeat it after any rotation of an offline key.

## What this scheme buys

**Backups no longer depend on one box.** Before: the key in `.env` on the host, a copy with the
owner. Lose the copy and the host dies — both buckets become noise. Formally a copy existed; in
practice it was an agreement, not a mechanism. The offline key, by construction, has never been on
the host.

**Secrets get backed up at all** — arguably the most practical gain, and not a cryptographic one.
Before, losing the box meant losing `FERNET_SECRET_KEY`: a restored database would return a
`workspace_tokens` table full of ciphertext nothing could open. The database is there, but every
customer's WB tokens are dead and each customer has to reissue them.

**Verifiability.** The correctness of the recipients used to be a matter of trusting whoever
typed them in. Now it is a test and a gate.

## What it protects against, and what it does not

**Protected:**

* *bucket leak* — S3 keys leaked, the provider was breached, a bucket was made public by mistake:
  the attacker gets ciphertext. This held under gpg too; the new scheme changes nothing here;
* *total loss of the host* — previously fatal if the passphrase copy had gone missing;
* *loss of one of the keys* — previously there was one key, lost all at once;
* *partial compromise* — the offline database key leaks: the WB tokens in the archives are still
  behind Fernet, and the Fernet key is behind a different key.

**Not protected:**

* **root on the backup host.** To be honest: almost nothing changes. Whoever is in already has the
  live database, the live `.env` and the live tokens. The only extra thing the online key gives
  them is **history**: deleted rows, revoked tokens, data of departed customers. That is a real
  loss and a deliberate trade;
* **compromise of the password manager** — both offline keys are there;
* **write access to the repository.** Whoever can commit to `main` can add a third recipient to
  `database.txt`, and every later archive will open with their key. Gate 5b will not catch this:
  it checks the file against the list, and the list has already been replaced. The pin in the test
  catches it — that is, the protection is in CI, not in the backup.

## Trade-offs

**The online key on the host.** The alternative is to remove it and lose gate 6, the only check
that proves an archive actually restores, and the only one that catches what the other five
cannot see. The trade: confidentiality of history in exchange for confidence that the backup
works. Removing the online key is a one-line change to the recipient list, should the decision
ever be revisited; the rehearsal goes with it.

**One passphrase became two keys plus the old passphrase.** `BACKUP_ENCRYPTION_KEY` cannot be
deleted until the last symmetric `.gpg` archive has expired from `monthly/` (365-day retention).
A year during which you must not lose a key that no longer writes anything. `decrypt_archive`
picks the scheme from the file extension, so both eras restore with one command.

**The secrets bundle is manual.** It has one failure mode: a key in `.env` changed and nobody
re-ran the bundle. There is a watchman — the Sunday report says `secrets bundle: STALE`. That is a
warning, not a guarantee.

## What this migration gave up

Worth a section of its own, because it is the one regression and it is not obvious.

The symmetric scheme had a side property: **only someone holding the passphrase could forge an
archive.** Encryption and authentication were one act. The asymmetric scheme cannot do that: the
public key is in git, and anyone who reaches it can produce a file our key will open normally.

In practice: whoever gains write access to a bucket can replace a nightly archive with their own.
It will decrypt, pass `gzip -t`, and restore into PostgreSQL. You would restore from a dump they
wrote. Before, that required the passphrase.

The `sha256` in the object metadata does not help: the object and its metadata are written with
the same credentials, so it attests to the transfer, not to the origin. Two records outside that
blast radius do help, and both exist:

* **the local ledger** `state/artifact-sha256.log` — appended when the artifact is written, before
  upload. The secrets bundle goes into it alongside the archives, for a sharper reason: a forged
  archive costs a restore of the wrong data, a forged bundle is an `.env` written by someone else,
  on which a rebuilt host would come up. `restore.sh fetch` checks the download against it: a
  mismatch is a refusal, a missing entry is a warning (the normal case when restoring on a clean
  host). This covers the "only the S3 keys leaked" scenario;
* **the sha256 in the weekly report** sent through the optional Telegram alert channel — a channel
  neither the bucket keys nor the host itself can reach once the message is sent. This covers the
  "the whole host was taken" scenario.

Both records are pinned by `backend/tests/unit/core/test_backup_artifact_provenance.py`.

**What remains open:** daily archives go to the buckets without an out-of-band mark — only the
weekly one is reported. That is deliberate: a daily "all good" is noise that trains people not to
read failure messages. The local ledger covers the dailies; the report does not. The complete
answer is signing artifacts (`minisign`, `ssh-keygen -Y`), which means another key pair and
another ritual; it was judged disproportionate while writing to a bucket requires either root on
the host or a separate leak of the S3 keys.
