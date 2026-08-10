#!/usr/bin/env python3
"""Send a CI notification to Telegram — the single place that talks to the API.

Every notification this project sends (deploy, release, and anything added
later) goes through here for one reason: `disable_notification` is a project
invariant, not a per-call decision. Notifications are SILENT. Spread across
three hand-written `curl` calls that invariant lasts until the next person
copies the wrong one; concentrated here it is a single line that cannot be
forgotten.

Audience is the other thing this file owns:

  --audience main   TELEGRAM_MAIN_CHAT_ID only. Operational noise — deploys,
                    backups — that only the maintainer needs.
  --audience all    main + WORKERS_TELEGRAM_CHAT_IDS (comma/whitespace
                    separated). Product-level news, i.e. releases.

Usage:
    printf '%s' "$text" | telegram_notify.py --audience main
    release_notes_ru.py | telegram_notify.py --audience all --parse-mode HTML

Exit status is 0 unless *every* delivery failed: a release that shipped but
could not be announced is still a release, and failing the workflow after the
tag exists would only produce a red run nobody can fix by re-running.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

API = "https://api.telegram.org"

# Telegram rejects a sendMessage over 4096 UTF-16 code units. Leave headroom
# for the "(1/3)" continuation marker we add when splitting.
MAX_LEN = 3900

# Tags Telegram's HTML parse mode actually understands. `<ul>`/`<li>` are NOT
# among them — an LLM asked for "HTML" will happily emit them, and Telegram
# answers 400 rather than ignoring them.
ALLOWED_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ins",
    "s",
    "strike",
    "del",
    "code",
    "pre",
    "a",
    "blockquote",
    "tg-spoiler",
    "span",
}

_TAG_RE = re.compile(r"</?([a-zA-Z0-9-]+)(\s[^<>]*)?/?>")
_ENTITY_RE = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#\d{1,7}|#[xX][0-9a-fA-F]{1,6});")


def sanitize_html(text: str) -> str:
    """Make model-authored HTML safe for Telegram's parse_mode=HTML.

    Unsupported tags are dropped (list items become bullets, paragraphs and
    line breaks become newlines) and any remaining stray `<`, `>` or `&` is
    escaped, so a malformed generation degrades into readable plain text
    instead of a 400 from the API.
    """
    text = re.sub(r"^\s*```(?:html)?\s*|\s*```\s*$", "", text.strip())
    text = re.sub(r"(?i)<\s*br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|li|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "• ", text)
    text = re.sub(r"(?i)</?\s*(ul|ol|p|div|h[1-6])[^>]*>", "", text)

    # Escape bare ampersands, keeping real entities (&amp;, &#8212;) intact.
    text = "".join(
        part if _ENTITY_RE.fullmatch(part) else part.replace("&", "&amp;")
        for part in re.split(r"(" + _ENTITY_RE.pattern + r")", text)
    )

    out, pos = [], 0
    for m in _TAG_RE.finditer(text):
        out.append(text[pos : m.start()].replace("<", "&lt;").replace(">", "&gt;"))
        out.append(m.group(0) if m.group(1).lower() in ALLOWED_TAGS else "")
        pos = m.end()
    out.append(text[pos:].replace("<", "&lt;").replace(">", "&gt;"))

    text = "".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def to_plain_text(html: str) -> str:
    """Last-resort rendering: drop every tag and unescape, keeping the words."""
    return unescape(_TAG_RE.sub("", sanitize_html(html)))


def chunk(text: str) -> list[str]:
    """Split on paragraph, then line, then hard boundaries — never mid-tag."""
    if len(text) <= MAX_LEN:
        return [text]

    parts: list[str] = []
    rest = text
    while len(rest) > MAX_LEN:
        window = rest[:MAX_LEN]
        cut = max(window.rfind("\n\n"), window.rfind("\n"))
        if cut <= 0:
            cut = MAX_LEN
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip("\n")
    if rest.strip():
        parts.append(rest)

    total = len(parts)
    return [f"{p}\n\n<i>({i}/{total})</i>" for i, p in enumerate(parts, 1)]


def chat_ids(audience: str) -> list[str]:
    """Resolve an audience to chat ids, maintainer first and each one once.

    Duplicates are a realistic configuration slip — the maintainer's own id
    listed among the workers' — and a doubled release announcement is the kind
    of noise that teaches people to mute the channel.
    """
    main = (os.environ.get("TELEGRAM_MAIN_CHAT_ID") or "").strip()
    ids = [main] if main else []

    if audience == "all":
        raw = os.environ.get("WORKERS_TELEGRAM_CHAT_IDS") or ""
        ids += [c for c in re.split(r"[,\s;]+", raw) if c]

    unique: list[str] = []
    for chat_id in ids:
        if chat_id not in unique:
            unique.append(chat_id)
    return unique


def post(token: str, chat_id: str, text: str, parse_mode: str | None) -> None:
    payload = {
        "chat_id": chat_id,
        "text": text,
        # The invariant. Do not make this configurable.
        "disable_notification": "true",
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    # S310 is about attacker-controlled schemes; this URL is a literal https
    # constant with only the bot token interpolated into the path.
    req = urllib.request.Request(  # noqa: S310
        f"{API}/bot{token}/sendMessage",
        data=urllib.parse.urlencode(payload).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        body = json.loads(resp.read().decode())
    if not body.get("ok"):
        raise RuntimeError(f"Telegram did not confirm delivery: {body}")


def send(token: str, chat_id: str, text: str, parse_mode: str | None) -> bool:
    """Deliver one message, retrying transient failures and degrading on 400.

    A 400 is almost always the markup: falling back to plain text costs the
    formatting but keeps the message, which is the part that matters.
    """
    for attempt in range(3):
        try:
            post(token, chat_id, text, parse_mode)
            return True
        except urllib.error.HTTPError as exc:
            if exc.code == 400 and parse_mode:
                sys.stderr.write(
                    f"chat {chat_id}: HTTP 400 with parse_mode={parse_mode}; "
                    "retrying as plain text.\n"
                )
                text, parse_mode = to_plain_text(text), None
                continue
            if exc.code == 429 or exc.code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            # Never echo the response: the URL it came from carries the token.
            sys.stderr.write(f"chat {chat_id}: Telegram returned HTTP {exc.code}.\n")
            return False
        except Exception as exc:  # alerting must never raise into the workflow
            sys.stderr.write(f"chat {chat_id}: {type(exc).__name__}: {exc}\n")
            time.sleep(2 * (attempt + 1))
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audience", choices=("main", "all"), default="main")
    ap.add_argument("--parse-mode", choices=("HTML", "none"), default="none")
    ap.add_argument("--text", help="message body; read from stdin when omitted")
    args = ap.parse_args()

    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        sys.stderr.write("TELEGRAM_BOT_TOKEN is not set; nothing sent.\n")
        return 0

    text = args.text if args.text is not None else sys.stdin.read()
    parse_mode = None if args.parse_mode == "none" else args.parse_mode
    if parse_mode == "HTML":
        text = sanitize_html(text)
    text = text.strip()
    if not text:
        sys.stderr.write("Empty message body; nothing sent.\n")
        return 0

    targets = chat_ids(args.audience)
    if not targets:
        sys.stderr.write(
            f"No chat ids for audience={args.audience} "
            "(TELEGRAM_MAIN_CHAT_ID / WORKERS_TELEGRAM_CHAT_IDS); nothing sent.\n"
        )
        return 0

    pieces = chunk(text)
    delivered = 0
    for chat_id in targets:
        if all(send(token, chat_id, piece, parse_mode) for piece in pieces):
            delivered += 1

    sys.stderr.write(f"Delivered to {delivered}/{len(targets)} chat(s).\n")
    return 0 if delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())
