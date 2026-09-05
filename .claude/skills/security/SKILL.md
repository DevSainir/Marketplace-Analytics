---
name: security
description: Threat-model this repo's code before writing it — tenancy scoping, access guards, resource bounds, fail-closed defaults, and what must never reach a response. Use whenever you add or change an API route, a database query, a Celery task, an upload handler, a migration, auth or session logic, an error message, or anything touching WB tokens, activation codes or invitations — and whenever asked to review, audit or harden. Names the exact guard and scoping helper to use, so a new route inherits the controls instead of reinventing them.
---

# Security

This service holds **other companies' money data** — settlement reports, cost prices,
margins, and the WB API tokens that authenticate against their live seller accounts. A
tenancy bug here is not a defect, it is a disclosure of one customer's commercial position
to another.

Work offensively before you work defensively: ask how the thing you are writing gets
abused, then write it so the abuse is structurally impossible rather than merely unhandled.

## The 30-second pre-flight

Before writing any route, query, task or handler, answer four questions. If any answer is
"I'm not sure", stop and check — do not write it and hope.

1. **Whose data is this?** → every query needs a tenant, not just an id.
2. **Who may call this?** → pick a guard from the ladder below, never "authenticated" alone.
3. **What if it's called 10 000 times, twice at once, or with a 2 GB body?** → bound it, and
   decide single-use races in the database.
4. **What does the failure path return?** → 404 over 403 for existence, never an internal
   string, and never the value that was rejected.

## What is machine-enforced, and what still needs you

Two invariants no longer depend on anyone remembering them. Both walk the real
app and resolve each route's dependency tree, so a new route is covered the
moment it exists rather than when someone adds it to a list:

* `tests/unit/core/test_every_covered_route_binds_a_tenant.py` — every route in a
  module owning a policy-covered table resolves a workspace binder.
* `tests/unit/core/test_every_writing_route_is_guarded.py` — every POST/PATCH/
  PUT/DELETE resolves a guard at least as strong as `WritingAccess`. Added after
  `PATCH /ab-tests/{test_id}` shipped without one and a read-only manager could
  retune a running test.

Both keep an **exemption list with a reason per entry**, and both assert the
exemptions still name live routes — a stale entry would silently pre-approve
whatever later takes that path.

**What they cannot decide for you.** They prove a guard is *present*, never that
it is the *right* one: a route that should be owner-only passes with a writer
guard. A GET that writes passes too, because the verb is the trigger. Choosing
the guard is still this checklist's job — the tests only make "nobody remembered
any guard" impossible to ship.

## Use the controls that already exist

Do not invent a new check. This repo has exactly one of each, and a route that reinvents one
is a route that will disagree with the others.

**Access ladder** — from `src.modules.organizations.contract`, each narrower than the last:

| Guard | Requires | Use for |
| --- | --- | --- |
| `CurrentAccess` | a valid token only | activation, own invitations — the only surfaces a bare account may reach |
| `MemberAccess` | belongs to an organisation | **every data router** |
| `WritingAccess` | + subscription not past grace | any write, any WB call, any Celery enqueue |
| `OwnerAccess` | owner (or dev) | workspaces, WB tokens, members, billing |
| `DevAccess` | platform `dev` role | activation codes |

`resolve_access()` is the ONE place platform role, membership role and subscription state
combine. Never read `user.role` directly in a route — it answers only a third of the question.

**Tenant scoping**:

* Workspace-level: `CurrentWorkspaceId` (validates `X-Workspace-Id` against the caller's own
  organisation) and `WorkspaceSku` (proves a path `nm_id` belongs to it). For a route that
  takes the workspace from its **URL path** instead of the header, use `PathWorkspaceId` —
  same validation, and it is the only other place the tenant gets bound (below).
* Query-level: `workspace_sku_select(workspace_id)` — the semijoin through `product_card`
  that every cross-SKU aggregate must go through.
* Never `SELECT ... WHERE id = :id` on tenant data. Always `AND <tenant column> = :tenant`.

**Both of those dependencies also bind the tenant for the database** (`set_workspace_context`,
register P2.5), and that has a consequence worth knowing before it bites: once
`row_level_security.sql` is applied, a route that reaches a policy-covered table *without*
going through one of them makes its queries **raise**, not return fewer rows. So:

* Adding a tenant-scoped route? Resolve the workspace through `CurrentWorkspaceId` or
  `PathWorkspaceId`. Taking a raw `workspace_id` parameter and passing it to a service scopes
  the query correctly but binds nothing.
* Adding a table to the policy list? Walk every router that reaches it first and check each
  one binds. That check is what caught `workspace_tokens`, whose owner-only routes address a
  workspace by path — the policy would have made every token screen raise.

**Secrets**: `hash_opaque_secret` / `generate_opaque_secret` for anything we hand out
(codes, invitation tokens, refresh secrets); `encrypt_secret` / `decrypt_secret` (Fernet) for
third-party credentials at rest; bcrypt only for human-chosen passwords.

**Single use**: `RefreshTokenRepository.consume`, `ActivationCodeRepository.claim`,
`InvitationRepository.claim` — all conditional `UPDATE ... WHERE <still unused>` returning
`rowcount == 1`. Copy that shape; never check-then-write.

## Invariants

**Fail closed.** Every unknown resolves toward less access. A missing subscription row is
read-only, not full access. A cache miss on an authorization fact denies. If Redis is down
and a limiter fails open, that is a deliberate, documented availability trade — say so in a
comment or do not do it.

**A control that fails open must report it.** Call
`src.core.degradation.report_degraded(...)` on the failure path and `report_healthy(...)`
on the success path, with a `CONTROL_*` constant; add a new constant if yours is a new
control. Do **not** log the outage from inside the control — that is one record per
request, which is a flood rather than an alert, and it cannot see that a *second* control
went down in the same instant. The ledger raises
`SECURITY_CONTROLS_DEGRADED_TOGETHER` when two do, which is the failure mode that made
this a register item (P1.2) rather than an accepted trade. The `detail` string reaches the
log verbatim, so it carries an exception class, never a token or a key.

**Decide races in the database (TOCTOU).** Any "only once" rule — redeem a code, accept an
invitation, consume a token, claim a slot — is a read-then-write, and two requests in the
same millisecond both pass the read. Use a conditional `UPDATE` (or a unique index) and let
the database pick the winner. **Claim before you build**, so the loser creates nothing.

**Validate at the boundary.** HTTP bodies, query params, headers, WB API responses, Celery
task arguments and uploaded files are all outside the trust boundary. Bound them with types
(`Literal` beats a free string), `max_length`, `ge`/`le`, and `max_items` on every list.

**Scope, don't filter afterwards.** Fetching everything and discarding the wrong rows in
Python is a leak waiting for the day someone forgets the discard — and it is also the
expensive way. Put the tenant in the `WHERE`.

**Least privilege, including our own.** A route gets the narrowest guard that still works.
A token gets the narrowest WB scope. A container gets the narrowest mount.

**404 over 403 for existence.** "You may not touch workspace X" confirms workspace X exists.
Foreign resources are reported as missing. Say *why* in the docstring, or someone will
"fix" it back to 403 as more informative.

**Make secrets structurally unreturnable.** Response DTOs carry booleans and status, never
token values. A secret travels outbound exactly once, in the response that creates it.

**Never echo the input back.** A validation error says which field and why, never what was
submitted — FastAPI's default 422 handler returns the offending value, which put rejected
passwords in clear in the response body until `main.py` overrode it.

## Self-audit before you finish

1. **Access control** — is there a guard, and is it the narrowest that works? Does every
   query carry the tenant?
2. **Data exposure** — could this response contain another tenant's row, an internal path, a
   stack trace, an upstream error body, or a secret?
3. **Execution safety** — dynamic evaluation, pickle/YAML deserialization, a subprocess
   built from user input, a path joined from user input?
4. **Resource bounds** — body size, list length, page size, row count, task time limit,
   rate limit. Is the size check *before* the read into memory?
5. **Concurrency** — is there a single-use or quota rule here that two simultaneous requests
   could both satisfy?
6. **Traceability** — if this action is later disputed, does anything record who did it? For
   a security-relevant action, does that record survive the row being deleted?

Uncertain on any of them → say so explicitly to the user rather than shipping it quietly.

## Say something when it's out of scope

If you find a real weakness while doing unrelated work, do not silently widen the task and
do not silently ignore it. State it in one sentence, note it in
`docs/security/HARDENING.md`, and carry on with what was asked.

## Deeper references

Read these when the work actually calls for them, not by default:

* `references/codebase-controls.md` — where every control lives in this repo, which tests
  enforce it, and the grep commands that prove a new route is wired correctly.
* `references/attack-classes.md` — per class (BOLA, BFLA, resource exhaustion, injection,
  SSRF, supply chain…): the question to ask, how it has shown up *here*, and how to verify.

Standing context: the live weakness register is `docs/security/HARDENING.md`; the tenancy
model is in the `backend-architecture` skill; anything WB-facing also needs
`wildberries-api`.
