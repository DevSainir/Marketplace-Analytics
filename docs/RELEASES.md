# Versioning and releases

The project is versioned with [Semantic Versioning](https://semver.org), starting at **0.1.0**.
Nobody types a version number: it is derived from the Conventional Commits already enforced at
commit time by the `commitizen` hook in `.pre-commit-config.yaml`.

## How a release happens

1. You push conventional commits to `main` as usual (this repo is trunk-based).
2. `.github/workflows/release.yml` runs [Release Please](https://github.com/googleapis/release-please),
   which opens a pull request titled `chore(release): vX.Y.Z` describing the version it would
   produce and the changelog it would write, and keeps that PR current on every push.
3. **The PR is merged once a week** — Sunday 17:00 UTC, on the workflow's `schedule`.
   That merge **is** the release. Release Please then:
   * writes `CHANGELOG.md`,
   * bumps `version.txt`, `backend/pyproject.toml` and `frontend/package.json` to the same number,
   * tags `vX.Y.Z` and publishes a GitHub Release.
4. The merge lands on `main` like any other commit, so the `tests` pipeline runs on it in full.

The weekly cadence batches the **version**, not the work: every push to `main` is still tested
as it lands. What a version number means is "a week of work", not "somebody pushed".

### Why weekly

The merge used to run on every push, which made the version number a push counter — dozens of
releases in a few days, several of them cut by a `chore:` that changed no behaviour. A changelog
of one-commit releases carries nothing `git log` does not. `backend/tests/unit/core/test_release_cadence.py`
fails if the merge step loses its schedule gate, because removing it would fail nothing: versions
would simply start climbing again.

### Cutting one early

Dispatch `release.yml` by hand — `workflow_dispatch` passes the same gate the schedule does and
merges the open PR immediately. That is the path for a fix that must carry a version before Sunday.

### Holding a release

Label the open PR **`hold-release`**: the merge step skips it and the PR stays open until the label
comes off, at which point the next scheduled run or dispatch merges it.

The merge is deliberately not gated on the PR's own checks — they never run. GitHub holds workflow
runs for Actions-opened PRs at `action_required`, so waiting for green there would wait forever.
The gate is the merge commit on `main`, which runs the full pipeline. (`tests` does not run on
`pull_request` at all, so the release PR carries no checks — see
[Known wrinkle](#known-wrinkle) for why.)

### Which number you get

| Commit | Effect while < 1.0 |
| --- | --- |
| `fix:` | patch — `0.1.0` → `0.1.1` |
| `feat-minor:` | patch — `0.1.0` → `0.1.1` |
| `feat:` | minor — `0.1.0` → `0.2.0` |
| `feat!:` / `BREAKING CHANGE:` | minor — `0.1.0` → `0.2.0` |
| `chore:`, `docs:`, `ci:`, … | patch, and appears in the changelog under its own section |

`feat-minor:` is ours, not part of the Conventional Commits spec, and it exists because most
features here are not worth a minor bump — see the `git-workflow` skill for which one to reach for.
Nothing configures it as "patch": Release Please bumps **minor only for the literal type `feat`**
and major only for a breaking change, and everything else falls through to patch. So the type
needed no bump rule, only two registrations — and if you add another such type and forget one of
them, the failure mode is silence rather than an error for the first:

* `release-please-config.json` → a `changelog-sections` entry, or it is absent from the changelog
  (an explicit sections list hides every type it does not name);
* `.cz.toml` → the `schema_pattern`, or the commit-msg hook rejects the commit outright — the one
  registration that fails loudly.

The last row of that table is the reason for `"bump-minor-pre-major": true` in
`release-please-config.json`: without it a single `!` commit would declare the project 1.0.0 long
before anyone decided it was. Delete that line when the API is actually stable, and the normal
SemVer rules take over.

To force a specific number once, put `Release-As: 1.0.0` in a commit body.

### Why `separate-pull-requests` is true for a single package

It reads like a contradiction and is not. There is one package, so it changes nothing about how
many PRs get opened — what it does is keep the **Merge plugin** out of the way. With it `false`,
Merge runs even for a single package, discards `pull-request-title-pattern`, and hardcodes
`chore: release main`. That title then lands on `main` as a commit subject. The PR is easier to
read, and so is `git log`, when its title says which version it releases.

## Where the version lives

`version.txt` at the repo root is the source of truth; `backend/pyproject.toml` and
`frontend/package.json` are kept in step by Release Please and should never be edited by hand.
The `# x-release-please-version` comment in `pyproject.toml` is what marks the line to update —
do not remove it.

There is a fourth file nobody thinks of: **`backend/uv.lock` records the project's own version**,
not just its dependencies. A version bump therefore leaves the committed lock one line stale, and
`uv sync --locked` fails — which takes out `lint + types + fast tiers` and everything gated on
them. An early release was tagged and published with exactly that one stale line.

The release workflow now runs `uv lock` on the release branch and commits the result, so the
commit that lands on `main` is self-consistent. `--locked` stays: it is what stops CI installing a
dependency set the lock does not describe, and the right response to a stale lock is to update it,
not to stop checking. If you ever bump a version by hand, run `uv lock` in the same commit.

The `v0.1.0` tag is the baseline: the state of the project when versioning was introduced.
Everything before it predates the changelog. It exists so that Release Please has something to
diff the first release against — without it, the first changelog would be the entire history of
the repository.

## Known wrinkle

The release PR is opened by `GITHUB_TOKEN`, and GitHub holds workflow runs for PRs that Actions
opened at **`action_required`** until a human approves them. Nothing waits on it: the merge commit
lands on `main`, where the full pipeline runs.

A held run is not held indefinitely, though. GitHub **expires** it as soon as something supersedes
it or the PR closes, and an expired run's conclusion is `failure`. This workflow causes both within
seconds — Release Please pushes twice (the bump, then the `uv.lock` sync), and then the merge step
closes the PR. So every release used to leave two red ✗ on `tests`, each a few seconds long, with
**zero jobs executed** and the banner:

> This run likely failed because of a workflow file issue.

That banner is misleading — it sends you to the YAML, which is fine and passes on `main` minutes
later. The annotation below it is the true one:

> This workflow run required approval but was not approved before it expired.

Nothing was ever broken by this, but every release trained people to read a red check as noise.

**The fix**: `tests` no longer triggers on `pull_request` at all. In a trunk-based repository the
release PR is the only PR there is, its contents reach `main` in the merge commit seconds later,
and they are tested there in full. The head branch could not be filtered out instead —
`pull_request.branches` matches the *base* branch, and the approval is held at run level, so no
job-level `if:` is ever reached. To run the pipeline against a branch by hand, dispatch `tests` at
it; that also offers `run_slow_tiers`, which a PR run never did.
`backend/tests/unit/core/test_no_workflow_runs_on_pull_request.py` fails if the trigger comes back.

The same rule has a sharper edge on the automatic merge, and it is the reason that step does more
than call `gh pr merge`. **A merge performed with `GITHUB_TOKEN` pushes to `main` without
triggering any workflow** — the property the `uv.lock` push relies on to avoid looping. Two things
a human merge would have started go missing with it:

* `tests`, so the bump commit would sit on `main` untested.
* `release` itself, which is what sees the merged PR and creates the tag and the GitHub Release.
  Without it the PR merges and no release is ever cut.

`workflow_dispatch` is the documented exception, so the merge step starts both explicitly. A
dispatched `tests` on `main` runs the same tiers a push does — `end-to-end` keys off the branch and
`performance` is opt-in either way. The test pipeline's concurrency key carries the event name, so
that dispatch does not cancel the push run already in progress (also pinned by
`test_release_cadence.py`).

If you ever move the merge onto a PAT, remove those explicit dispatches: with a real user token the
push triggers everything by itself, and each would fire twice.

### «Base branch was modified» on the automatic merge

The merge step can fail with
`GraphQL: Base branch was modified. Review and try the merge again.`, leaving the release PR open
and `main` on the previous version numbers.

It is a **race, not a conflict**. The step before it pushes `uv.lock` to the release branch, and a
merge issued while GitHub is still recomputing the PR's mergeability is refused with that message.
The step therefore retries five times with a growing pause and treats "already merged" (a
concurrent run won) as success. If all five are refused it fails loudly rather than skipping
quietly; the next scheduled run or a dispatch merges the PR.
