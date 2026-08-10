# Versioning and releases

The project is versioned with [Semantic Versioning](https://semver.org), starting at **0.1.0**.
Nobody types a version number: it is derived from the Conventional Commits already enforced at
commit time by the `commitizen` hook in `.pre-commit-config.yaml`.

## How a release happens

1. You push conventional commits to `main` as usual (this repo is trunk-based).
2. `.github/workflows/release.yml` runs [Release Please](https://github.com/googleapis/release-please),
   which keeps **one open pull request** titled `chore(release): vX.Y.Z`. That PR is a live preview
   of the next release: the version it would produce and the changelog entries it would write.
3. Merging that PR **is** the release. Release Please then:
   * writes `CHANGELOG.md`,
   * bumps `version.txt`, `backend/pyproject.toml` and `frontend/package.json` to the same number,
   * tags `vX.Y.Z` and publishes a GitHub Release.
4. The merge lands on `main` like any other commit, so `tests` runs and the VPS auto-deploys on green.
5. The release announcement goes out to Telegram (below).

Nothing is released until you merge that PR. To hold a release, leave it open.

### Which number you get

| Commit | Effect while < 1.0 |
| --- | --- |
| `fix:` | patch — `0.1.0` → `0.1.1` |
| `feat:` | minor — `0.1.0` → `0.2.0` |
| `feat!:` / `BREAKING CHANGE:` | minor — `0.1.0` → `0.2.0` |
| `chore:`, `docs:`, `ci:`, … | patch, and appears in the changelog under its own section |

The last row of that table is the reason for `"bump-minor-pre-major": true` in
`release-please-config.json`: without it a single `!` commit would declare the project 1.0.0 long
before anyone decided it was. Delete that line when the API is actually stable, and the normal
SemVer rules take over.

To force a specific number once, put `Release-As: 1.0.0` in a commit body.

### Why `separate-pull-requests` is true for a single package

It reads like a contradiction and is not. There is one package, so it changes nothing about how
many PRs get opened — what it does is keep the **Merge plugin** out of the way. With it `false`,
Merge runs even for a single package, discards `pull-request-title-pattern`, and hardcodes
`chore: release main`. That title then lands on `main` as a commit subject, where the release
announcement has to recognise and drop it. `release_notes_ru.py` filters the whole family of
release-bot subjects anyway — belt and braces — but the PR is easier to read when its title says
which version it releases.

## Where the version lives

`version.txt` at the repo root is the source of truth; `backend/pyproject.toml` and
`frontend/package.json` are kept in step by Release Please and should never be edited by hand.
The `# x-release-please-version` comment in `pyproject.toml` is what marks the line to update —
do not remove it.

The `v0.1.0` tag is the baseline: the state of the project when versioning was introduced.
Everything before it predates the changelog. It exists so that Release Please and the
announcement both have something to diff the first release against — without it, the first
changelog would be the entire history of the repository.

## Notifications

All of it goes through `.github/scripts/telegram_notify.py`, which exists so that one rule cannot
be forgotten: **every message is sent silently** (`disable_notification`). Deploys are unattended
and backups run at 03:00; the requirement is that the message is waiting in the morning, not that
it wakes anyone. There is deliberately no flag to turn this off, and
`backend/tests/unit/core/test_release_notifications.py` fails if someone adds one.

| What | Audience | Language |
| --- | --- | --- |
| Deploy succeeded / failed | `TELEGRAM_MAIN_CHAT_ID` | English |
| Backup failed (VPS cron) | `BACKUP_ALERT_TELEGRAM_CHAT_ID` in the server `.env` | English |
| Release published | `TELEGRAM_MAIN_CHAT_ID` + `WORKERS_TELEGRAM_CHAT_IDS` | Russian |

Operational news is for whoever fixes it. Release news is for whoever uses the product — which is
why it is translated.

### The translation

`.github/scripts/release_notes_ru.py` sends the release's commit subjects to Gemini and asks for
two things: Russian, and a change of verb form out of the imperative.

```
feat(finreports): add Balance table
→ • Модуль финотчётов: была добавлена таблица Баланс.
```

The first is obvious; the second is the part that makes the note readable. `add Balance table` is
written for the person who wrote the code. «была добавлена таблица Баланс» is written for the
person who now has the table.

Two details that are not decoration:

* **The scope glossary is in the prompt.** `finreports` becomes «модуль финотчётов» in every
  release, instead of drifting between three plausible translations.
* **Telegram's HTML is not HTML.** It has `<b>`, `<i>`, `<code>` and `<a>`, and no `<ul>`/`<li>` —
  a list the model emits anyway is a 400 and a lost announcement. `telegram_notify.py` degrades
  list markup to bullets and escapes anything else before sending, and falls back to plain text
  if Telegram rejects the message regardless.

If Gemini is unreachable or the key is missing, the announcement still goes out, in grouped
English, with a note saying the translation was unavailable. A release nobody hears about is a
worse failure than one announced in the wrong language.

Override the model with a `GEMINI_MODEL` repository **variable** if the default is retired; the
script tries the override first and still falls back through its own list.

## Secrets

| Name | Used by |
| --- | --- |
| `GEMINI_API_KEY` | release announcement translation |
| `TELEGRAM_BOT_TOKEN` | every notification |
| `TELEGRAM_MAIN_CHAT_ID` | deploy + release notifications |
| `WORKERS_TELEGRAM_CHAT_IDS` | release notifications — comma, space or semicolon separated |

`TELEGRAM_CHAT_ID` is no longer read by anything and can be deleted.

## Known wrinkle

The release PR is opened by `GITHUB_TOKEN`, and GitHub does not run workflows for PRs it opens
itself, so that PR shows no checks. It only touches `CHANGELOG.md` and the version files; the
merge commit lands on `main` and does run the full pipeline, which is what gates the deploy.
