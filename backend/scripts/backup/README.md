# Database backups

Nightly encrypted dump of the production PostgreSQL, pushed to two independent
object storages, with a weekly rehearsal that proves the artifact actually
restores.

Runs on the VPS at **03:00 Europe/Moscow** (`00:00` UTC — the host clock is UTC
and Moscow is a fixed UTC+3), from `/etc/cron.d/marketplace-backup`.

## What one run does

```
pg_dump ──▶ gzip ──▶ [gates 1-4] ──▶ age (2 keys) ──▶ [gates 5a, 5b]
                                                       │
                                    Sunday only ◀──────┤ [gate 6: real restore]
                                                       │
                                                       ▼
                       Hoster S3  ─┐
                                    ├──▶ daily/  (+ weekly/ Sun, + monthly/ 1st)
                       Cloudflare R2 ┘        each object read back and verified
```

The dump is **plain SQL gzipped**, not pg_dump's custom format: any `psql` of
any version can restore it without a matching `pg_restore`, and it carries an
end-of-dump marker that proves completeness. At ~750 MB the single-threaded
restore costs minutes.

## The validity gates

A run uploads nothing until all of these pass. In order:

| # | Gate | Catches |
|---|------|---------|
| 1 | `pg_dump` **and** `gzip` both exited 0 (`PIPESTATUS`) | a dump that died mid-stream — the naive pipeline only reports gzip's status, and gzip is perfectly happy compressing half a database |
| 2 | `gzip -t` | corruption in the archive |
| 3 | `PostgreSQL database dump complete` marker in the tail | a stream that was cut short but still gzipped cleanly |
| 4 | size ≥ `BACKUP_MIN_BYTES`, and ≥ 50% of the previous run | an empty database; and the likelier case of a dump that lost most of its rows while staying far above any fixed floor |
| 5a | the encrypted artifact decrypts back to a valid archive | encrypting correctly and decrypting correctly are two different claims |
| 5b | it carries one recipient stanza per recipient | 5a can only ever test the *online* key. This is what proves the offline one — the key that survives losing this box — is really on the file |
| 6 | **Sunday:** it restores into a scratch PostgreSQL | everything the other five cannot see |

Gate 6 runs on the **encrypted** file — exactly the bytes that get uploaded —
in a container on `--network none`, capped at 768 MB and 1 CPU so it cannot
squeeze the live stack. It asserts the restored copy has the same tables the
source had, has rows in every table that had rows, and carries an
`alembic_version`. Then, and only then, does the run push.

After each upload the object is read back: `ContentLength` must match the local
size and the `sha256` user-metadata must match the local checksum.

## Tiers and retention

Every night → `daily/`. Sunday also → `weekly/`. The 1st also → `monthly/`
(so a Sunday-the-1st writes all three). Each is a full, independent copy,
uploaded separately from the local file rather than server-side-copied.

**Retention is not this script's job.** Lifecycle policies on the buckets
expire `daily/` after 7 days, `weekly/` after 30 and `monthly/` after 365.
A script that deletes plus a bucket that deletes is one deletion rule too many.

## Encryption

`age`, to the two public keys in `recipients/database.txt`. One file, openable
by either of them:

| Recipient | Private half lives | What it is for |
|-----------|--------------------|----------------|
| online | `BACKUP_ENCRYPTION_IDENTITY` in `backend/.env` on the VPS | so gate 6, the Sunday restore rehearsal, can still decrypt unattended |
| offline | the maintainer's password manager, never on a server | the real disaster: this box is gone, and so is its `.env` |

The dump holds password hashes, session token families and the Fernet-encrypted
WB tokens, so it does not sit in a bucket in the clear.

**Why two keys rather than one passphrase.** Until 2026-09-21 this was
`gpg --symmetric` with `BACKUP_ENCRYPTION_KEY`. That key both encrypted and
decrypted, so it had to be on the box — and a copy of it in a password manager
was the only thing standing between a lost VPS and a year of unreadable
archives. An asymmetric pair splits those two jobs: the box holds a key that
can *write* archives it is allowed to read back, and the key that matters in a
disaster has never been anywhere an attacker could reach it.

**Why the online key is there at all.** Removing it is the stricter design, and
it costs gate 6 — the only gate that proves the artifact restores, and the only
one that has ever caught anything the other five could not see. A box that
already holds the live database gains very little from being unable to read its
own backups, so the trade goes the other way: keep the rehearsal, accept that a
shell on the VPS can read the archives.

`docs/security/BACKUP_KEYS.md` is the long form of all of this — the key scheme,
what it defends against, and what it does not.

**The recipient list is public and it is in git on purpose.** It is the one part
of this that a machine can check, and the failure it protects against is silent:
a wrong character in the offline recipient yields archives nobody can ever open,
and nothing would notice until the day that key is all there is. So gate 5b
counts the recipient stanzas on every artifact, and
`tests/unit/core/test_backup_encryption_recipients.py` pins both keys.

> **No private key is in the backups, and no private key is in git.** The
> offline key exists in your password manager and nowhere else. Losing it while
> the VPS is also gone means every archive in both buckets is noise.

### The old symmetric key is not finished yet

`monthly/` keeps objects for 365 days, and the last symmetric artifact written
was `monthly/marketplace-20260901T030002msk.sql.gz.gpg` — so `.gpg` objects are
in the buckets until **2027-09-01**. `BACKUP_ENCRYPTION_KEY` must stay in
`backend/.env` and in the password manager until then — `restore.sh` picks the
scheme from the file extension, so an old object and a new one are restored by
the same command, but only if that key is still around to be used.

## The secrets bundle

`backup_secrets.sh` encrypts `backend/.env` to a **third** key — one recipient,
offline only, in `recipients/secrets.txt` — and pushes it to `secrets/` in both
buckets. This machine cannot decrypt what it just wrote, on purpose.

That separation is the whole design. The nightly archive holds every WB token
Fernet-encrypted; `.env` holds the Fernet key. Two artifacts, two keys, two
layers — and the layers only mean anything while they are apart. Putting `.env`
inside the nightly dump would collapse them: one decrypted archive would then
yield every customer's live WB token, both buckets' credentials and the database
password together.

```bash
backend/scripts/backup/backup_secrets.sh      # after any change to .env
```

It is deliberately not on cron. Secrets change a few times a year, and a nightly
job over unchanging input is a nightly opportunity to leak it. The failure this
job really has is an operator who rotates a key and never re-runs it — so the
nightly run fingerprints `.env` and the Sunday report says `secrets bundle:
STALE` when it has drifted.

Objects under `secrets/` are **not** expired by a lifecycle policy, and that is
intentional: restoring a database archive from March needs the Fernet key as it
was in March. They are ~2 KB each.

Nothing here can verify the bundle opens. Two claims are checkable and are
checked — the tar reads back before it is encrypted, and the artifact carries
exactly one recipient stanza — and the rest is a **human drill**: fetch a bundle
and decrypt it with the key from your password manager, on a machine that is not
this one. Do it once after any change to the offline key.

## Restoring

```bash
backend/scripts/backup/restore.sh list cloudfare daily
backend/scripts/backup/restore.sh fetch cloudfare daily/marketplace-20260921T030000msk.sql.gz.age
backend/scripts/backup/restore.sh load /var/backups/marketplace/artifacts/marketplace-...age <container>
```

`list` and `fetch` are read-only. `load` drops and recreates the target
database, asks for the database name as confirmation, and refuses the live
`marketplace-service-postgres-1` unless the stack is stopped and
`BACKUP_ALLOW_PRODUCTION_RESTORE=1` is set.

The dump is `--no-owner --no-privileges` and does **not** carry roles: the
`marketplace` role is created by the compose stack from `POSTGRES_USER` /
`POSTGRES_PASSWORD`, so a bare-metal recovery is *bring the stack up, then
restore into it*.

**A bare-metal recovery also needs `scripts/sql/least_privilege_role.sql` re-run
afterwards.** Checked against a real dump rather than reasoned about: the
row-level-security policies and their `ENABLE ROW LEVEL SECURITY` *do* survive
those two flags, but `marketplace_app` and every `GRANT` to it do not — the
flags exist to suppress exactly that. So a restored database comes back with
the tenancy policies intact and no role able to use them, and the API fails to
authenticate at all. That is the safe direction to be wrong in, and it is still
a step somebody has to know about at 03:00.

The dump itself runs as `POSTGRES_USER` — the owner — which is why the policies
do not filter it. Running the backup as `marketplace_app` would not quietly
produce a short dump: with no tenant bound, `current_setting` raises and
`pg_dump` fails. Loud either way, but the owner is the correct identity here and
`backend/docker/docker-compose.yml` keeps it that way (see
`tests/unit/core/test_only_the_api_uses_the_restricted_role.py`).

## Configuration

All of it lives in `backend/.env` (see `.env.example` for the annotated list).
Required: `BACKUP_ENCRYPTION_IDENTITY` (the online age private key), the
Postgres credentials, and for each storage a URL, bucket, access key and secret.
`BACKUP_ENCRYPTION_KEY` is still required in practice until the last `.gpg`
object expires — see above. Everything else has a working
default in `lib/config.sh`.

Optional Telegram alerting: set `BACKUP_ALERT_TELEGRAM_BOT_TOKEN` and
`BACKUP_ALERT_TELEGRAM_CHAT_ID` and failures — plus the weekly deep-check
result — reach a human. Unset, the job is silent but still exits non-zero.

The alert itself is sent with `disable_notification`, like every other message
this project sends (see `docs/RELEASES.md`): a 03:00 backup must not ring a
phone, and the alert is still there at 09:00, which is when it gets acted on.
`BACKUP_ALERT_TELEGRAM_CHAT_ID` is the maintainer's chat — backups are
operational news, not something the whole team needs.

## Running it by hand

```bash
backend/scripts/backup/backup.sh                          # exactly what cron does
backend/scripts/backup/backup.sh --force-deep-check       # rehearse the restore today
backend/scripts/backup/backup.sh --tiers daily,weekly,monthly
```

Logs: `/var/backups/marketplace/logs/backup-YYYYMMDD.log`, cron's own output in
`cron.log` beside it.

## Layout

| File | Responsibility |
|------|----------------|
| `backup.sh` | orchestration — tier selection, gate order, housekeeping |
| `restore.sh` | list / fetch / load, for the day you need it |
| `lib/config.sh` | `.env` parsing (parsed, never sourced), defaults, destination table |
| `lib/dump.sh` | pg_dump, the archive gates, age encryption, decrypting either era |
| `lib/verify_restore.sh` | the weekly rehearsal |
| `lib/upload.sh` | dockerised aws-cli, upload + read-back verification |
| `lib/log.sh` | logging and alerting |
| `backup_secrets.sh` | the manual `.env` bundle |
| `lib/secrets.sh` | bundling, its gates, the staleness fingerprint |
| `recipients/*.txt` | the public keys, in git so a test can pin them |
| `cron/marketplace-backup` | the `/etc/cron.d` entry |
