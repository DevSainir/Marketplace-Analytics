# Database backups

Nightly encrypted dump of the production PostgreSQL, pushed to two independent
object storages, with a weekly rehearsal that proves the artifact actually
restores.

Runs on the VPS at **03:00 Europe/Moscow** (`00:00` UTC — the host clock is UTC
and Moscow is a fixed UTC+3), from `/etc/cron.d/marketplace-backup`.

## What one run does

```
pg_dump ──▶ gzip ──▶ [gates 1-4] ──▶ gpg AES256 ──▶ [gate 5]
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
| 5 | the encrypted artifact decrypts back to a valid archive | encrypting correctly and decrypting correctly are two different claims |
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

`gpg --symmetric --cipher-algo AES256` with the passphrase in
`BACKUP_ENCRYPTION_KEY`. The dump contains password hashes, session token
families and the Fernet-encrypted WB tokens, so it does not sit in a bucket in
the clear.

> **The passphrase is not in the backups.** It lives in `backend/.env` on the
> VPS and nowhere else unless you put it somewhere else. Keep a copy in a
> password manager — losing it means every archive in both buckets is
> unrecoverable noise.

## Restoring

```bash
backend/scripts/backup/restore.sh list cloudfare daily
backend/scripts/backup/restore.sh fetch cloudfare daily/marketplace-20260808T030000msk.sql.gz.gpg
backend/scripts/backup/restore.sh load /var/backups/marketplace/artifacts/marketplace-...gpg <container>
```

`list` and `fetch` are read-only. `load` drops and recreates the target
database, asks for the database name as confirmation, and refuses the live
`marketplace-service-postgres-1` unless the stack is stopped and
`BACKUP_ALLOW_PRODUCTION_RESTORE=1` is set.

The dump is `--no-owner --no-privileges` and does **not** carry roles: the
`marketplace` role is created by the compose stack from `POSTGRES_USER` /
`POSTGRES_PASSWORD`, so a bare-metal recovery is *bring the stack up, then
restore into it*.

## Configuration

All of it lives in `backend/.env` (see `.env.example` for the annotated list).
Required: `BACKUP_ENCRYPTION_KEY`, the Postgres credentials, and for each
storage a URL, bucket, access key and secret. Everything else has a working
default in `lib/config.sh`.

Optional Telegram alerting: set `BACKUP_ALERT_TELEGRAM_BOT_TOKEN` and
`BACKUP_ALERT_TELEGRAM_CHAT_ID` and failures — plus the weekly deep-check
result — reach a human. Unset, the job is silent but still exits non-zero.

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
| `lib/dump.sh` | pg_dump, the archive gates, gpg |
| `lib/verify_restore.sh` | the weekly rehearsal |
| `lib/upload.sh` | dockerised aws-cli, upload + read-back verification |
| `lib/log.sh` | logging and alerting |
| `cron/marketplace-backup` | the `/etc/cron.d` entry |
