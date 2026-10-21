"""Keeping secrets out of the two places that keep everything: logs and Sentry.

A log line and an error report are the same hazard wearing different clothes.
Both are written by code that is thinking about a failure rather than about
confidentiality; both are then *retained*, shipped off the box, and read by
more people than the database is. A WB token that reaches Loki has been copied
to a system with none of the controls that protect it in Postgres, where it is
Fernet-encrypted at rest — so one careless `%s` would quietly
undo that whole control.

**Two independent nets, because they fail differently.**

*By key* catches the structured case: a field literally called `password`,
`token`, `authorization`. Exhaustive over what it names, blind to what it does
not — a new field named `wb_secret` is caught by the substring rule, a field
named `x` holding the same value is not.

*By value* catches the unstructured case, which is the one that actually
happens here: nobody logs `{"token": ...}` on purpose, they log
`f"WB rejected {token}"` or let an exception's own message carry the tunnel URL
into a warning. Shape-matching a bcrypt digest or a JWT does not care what the
surrounding field is called, or whether there is one.

Neither net is sufficient. Together they cover "somebody named the field
badly" and "somebody never made a field at all", which are the two ways this
goes wrong.

**Never raises.** A scrubber that throws while redacting turns a log call into
an exception inside an exception handler, and the line it was protecting is
lost along with the one that would have explained why. Every entry point here
is wrapped so the worst case is an over-redacted line, never a lost one.

**What is deliberately NOT redacted.** Email addresses, workspace names, user
and organisation ids. They are the fields that make a line an answer rather
than a fact, the audit log already records addresses on purpose (register
P1.3), and redacting an identifier would defeat the entire point of binding
tenant context to every line. This module hides *credentials*, not *identity*.
"""

from __future__ import annotations

import re
from typing import Any, Final

#: What a redacted value becomes. A fixed marker rather than a truncation or a
#: hash: a prefix of a six-digit reset code is most of the code, and a hash of
#: a low-entropy secret is a lookup table away from the secret.
REDACTED: Final[str] = "[redacted]"

#: How deep the walker will follow nested structures before giving up and
#: redacting wholesale.
#:
#: Twelve, not the six a log payload would need. The binding constraint is
#: Sentry, which shares this scrubber: an error event nests
#: ``exception → values → [0] → stacktrace → frames → [i] → vars → name``,
#: which is eight levels before the walker reaches a local variable. Stopping
#: shallower would return ``[redacted]`` for whole stack traces — and stack
#: frame locals are the single most likely place for a token to be sitting,
#: so that is the depth this most needs to reach rather than the one it can
#: afford to skip.
_MAX_DEPTH: Final[int] = 12

#: Longest string the value patterns are run over. Beyond it the string is
#: truncated first — an upstream HTML error page should not cost a dozen regex
#: scans, and nothing legible lives past 16 KB of one log field anyway.
_MAX_SCAN_CHARS: Final[int] = 16_384

#: Field names whose value is a credential wherever it appears. Matched as a
#: **substring of the lowercased key**, so `wb_token`, `token`, `tokens` and
#: `x-auth-token` are all caught by one entry.
#:
#: `code` is absent on purpose, and the omission is the interesting one: this
#: codebase's `AppError.code` is a machine-readable error name that appears in
#: nearly every warning, and redacting it would blind the logs to *why*
#: requests fail in order to hide something that is not there. The verification
#: and activation codes that ARE secret carry their own names below.
_SENSITIVE_KEY_PARTS: Final[tuple[str, ...]] = (
    "activation_code",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "csrf",
    "fernet",
    "invite_code",
    "invitation_token",
    "jwt",
    "passwd",
    "password",
    "private_key",
    "pwd",
    "recovery_code",
    "refresh_token",
    "reset_code",
    "secret",
    "session_key",
    "set-cookie",
    "signature",
    "token",
    "verification_code",
    # Digests, not just their inputs: a stored hash is what an offline cracker
    # wants, and it is the thing a repository accidentally logs when it dumps a
    # user row.
    "hash",
    "salt",
    "digest",
    "fingerprint",
)

#: Value shapes that are a credential regardless of the field they sit in — or
#: of whether they sit in a field at all, which is the case this list exists
#: for. Ordered longest-match-first where two could overlap.
_SENSITIVE_VALUE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    # A JWT. WB's own seller tokens are JWTs, so this single pattern covers
    # both our access tokens and every credential the WB clients hold.
    re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}"),
    # A bcrypt digest, as `src.core.security` produces them.
    re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}"),
    # A Fernet token — how every workspace WB token is stored,
    # and therefore what a repository dump of that column would print.
    re.compile(r"\bgAAAAA[A-Za-z0-9_=-]{20,}"),
    # `Authorization: Bearer <...>` carried inside prose or a header dump.
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    # `user:password@host` in any DSN or proxy URL. The WB storefront clients
    # reach a credentialed forward proxy whose URL appears inside transport
    # errors; `scrub_credentials` in the WB base client covers that one path,
    # and this covers every path nobody thought about.
    re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^:/?#\s]+):[^@/?#\s]+@"),
    # 32+ unbroken hex characters: a SHA-256 or MD5 digest, or a
    # dashless UUID's worth of key material. Dashed UUIDs — every id this
    # service logs on purpose — do not match, and neither does the 12-character
    # request id.
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
)

#: Replacement for the DSN pattern, which keeps the scheme and host so a
#: connection failure is still diagnosable — the password is the only part
#: that had to go.
_DSN_REPLACEMENT: Final[str] = r"\1:" + REDACTED + "@"

#: Fields whose value is an identifier this service generated, exempt from the
#: **value** patterns (never from the key rules — no name here is sensitive).
#:
#: This list exists because the scrubber ate the correlation id the first time
#: it ran. ``trace_id`` is 32 hex characters, which is exactly what the digest
#: pattern below is looking for, so every line came out with
#: ``"trace_id": "[redacted]"`` — a redaction that hid nothing and destroyed
#: the one field the whole logging design is built to carry.
#:
#: Narrow on purpose, and safe for a specific reason: every value here is
#: minted by this service (a UUID from the database, an id from
#: :mod:`src.core.logcontext`, Celery's own task id). None is ever accepted
#: from a caller, so no attacker chooses what lands in an exempt field.
_IDENTITY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "trace_id",
        "request_id",
        "task_id",
        "user_id",
        "actor_user_id",
        "organization_id",
        "workspace_id",
    }
)


def is_sensitive_key(key: str) -> bool:
    """Whether a field name promises to hold a credential.

    Args:
        key: The field name, in whatever case the caller wrote it.

    Returns:
        ``True`` when any entry of :data:`_SENSITIVE_KEY_PARTS` appears in the
        lowercased name.
    """
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def scrub_text(text: str) -> str:
    """Redact every credential-shaped run inside one string.

    This is the half that catches interpolation — `f"token {token} rejected"`,
    an exception message carrying a proxy URL, an upstream body echoed into a
    warning. It runs over log *messages* as well as values, because the message
    is where a formatted secret most often ends up.

    Args:
        text: Any string bound for a log line or an error report.

    Returns:
        The string with each matched run replaced. Unmatched text is returned
        unchanged — this is a redactor, not a sanitiser, and mangling ordinary
        prose would make the logs worse for no gain.
    """
    if len(text) > _MAX_SCAN_CHARS:
        text = text[:_MAX_SCAN_CHARS] + "…[truncated]"
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        # The DSN pattern keeps its first group (scheme://user); every other
        # pattern replaces the whole match.
        replacement = _DSN_REPLACEMENT if pattern.groups else REDACTED
        text = pattern.sub(replacement, text)
    return text


def scrub_value(value: Any, *, depth: int = 0) -> Any:
    """Redact a value of any shape, recursing into containers.

    Args:
        value: A scalar, mapping, or sequence from a log event or Sentry payload.
        depth: Current recursion depth; callers leave it at zero.

    Returns:
        The value with credentials removed. Types are preserved where possible
        so a downstream JSON encoder still sees numbers as numbers — redaction
        should not be visible as a schema change to whatever reads the logs.
    """
    if depth > _MAX_DEPTH:
        return REDACTED
    if isinstance(value, str):
        return scrub_text(value)
    # bool before int: `isinstance(True, int)` is true, and a flag is not a
    # credential.
    if isinstance(value, (bool, int, float, type(None))):
        return value
    if isinstance(value, dict):
        return {key: _scrub_member(key, item, depth) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        scrubbed = [scrub_value(item, depth=depth + 1) for item in value]
        return type(value)(scrubbed) if isinstance(value, (list, tuple)) else scrubbed
    # Anything else — a UUID, a Decimal, an ORM instance, an exception — is
    # rendered by whatever encoder receives it. Scrub its string form now,
    # because that is the form it will be written in.
    return scrub_text(str(value))


def _scrub_member(key: Any, value: Any, depth: int) -> Any:
    """Redact one mapping entry, honouring both the key rules and the exemption.

    Args:
        key: The field name. Only a string key can be classified; anything else
            is treated as unknown and its value scrubbed normally.
        value: What the field holds.
        depth: The parent's recursion depth.

    Returns:
        ``REDACTED`` for a credential-shaped name, the value untouched for an
        identifier this service minted, and the recursively scrubbed value
        otherwise.
    """
    if isinstance(key, str):
        if is_sensitive_key(key):
            # A sensitive key is redacted whatever it holds — including a dict,
            # which is how a whole credentials block disappears in one step.
            return REDACTED
        # An identifier is exempt from the value patterns, but only as a
        # scalar: a container under one of these names is not something this
        # service produces, so it goes through the normal walk.
        if key in _IDENTITY_KEYS and isinstance(value, (str, int, float, type(None))):
            return value
    return scrub_value(value, depth=depth + 1)


def scrub_event(event: dict[str, Any]) -> dict[str, Any]:
    """Redact a whole log event or error payload in place of the original.

    The single entry point both sinks use: the structlog processor in
    :mod:`src.core.logging` and Sentry's ``before_send`` in
    :mod:`src.core.observability.sentry`. One function rather than two
    configurations, so a pattern added here cannot be added to the logs and
    forgotten in the error reports — which is the harder of the two to notice,
    since nobody greps Sentry for secrets that should not be in it.

    Args:
        event: The mapping about to be rendered or transmitted.

    Returns:
        A redacted copy. On any internal failure, a minimal event that says so
        — losing the line's detail is survivable, and emitting an unscrubbed
        line because the scrubber broke is not.
    """
    try:
        scrubbed = scrub_value(event)
    except Exception:
        return {"scrubbing_failed": True, "message": "log event withheld: redaction failed"}
    # `scrub_value` returns a dict for a dict input; the cast keeps mypy honest
    # about a function that is deliberately typed loosely everywhere else.
    return scrubbed if isinstance(scrubbed, dict) else {"message": REDACTED}


__all__ = [
    "REDACTED",
    "is_sensitive_key",
    "scrub_event",
    "scrub_text",
    "scrub_value",
]
