#!/usr/bin/env python3
"""Turn a release's Conventional Commits into a Russian Telegram announcement.

Reads commit subjects on stdin (one per line), asks Gemini to translate and
regroup them for a non-English-speaking audience, and prints Telegram-flavoured
HTML on stdout. Pipe it into `telegram_notify.py --audience all --parse-mode HTML`.

Two decisions worth keeping:

* **The verb tense change is the point.** `feat(finreports): add Balance table`
  is written for the person who wrote it; «Новая функция (модуль финотчётов):
  была добавлена таблица Баланс» is written for the person who now has it. The
  prompt asks for the perfective past specifically, not a literal translation.

* **Gemini is allowed to fail.** If the key is missing, the API is down, or the
  answer comes back empty, we fall back to a mechanically-built English list
  rather than announcing nothing. A release notification that arrives in the
  wrong language beats one that never arrives.
"""

from __future__ import annotations

import contextlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any

BASE = "https://generativelanguage.googleapis.com/v1beta"

# Last-resort names, used only when the model listing itself is unreachable.
# They are a guess by definition — which is the whole reason discover_models()
# exists. The first live release proved the point: this list's first entry
# answered 404 (retired for this key's API version) and its second was rate
# limited, so a release that had a perfectly good translator available got
# announced in English.
FALLBACK_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash")

# Model families that cannot do what we need: embeddings, media generation,
# audio/vision-only surfaces, and the non-Gemini research models.
_NOT_A_TRANSLATOR = (
    "embedding",
    "aqa",
    "imagen",
    "veo",
    "tts",
    "audio",
    "image",
    "vision",
    "live",
    "gemma",
    "learnlm",
    "robotics",
    "computer-use",
)

# How many discovered candidates to actually try before giving up and falling
# back to English. Three is enough to survive one retirement and one quota
# block without turning a release into a five-minute retry storm.
MAX_CANDIDATES = 3

# The scopes this repo actually uses. Handing the glossary to the model is what
# keeps «финотчёты» from drifting into «финансовые отчеты» between releases.
SCOPES = """\
finreports — модуль финотчётов
monitoring — модуль мониторинга
users — модуль пользователей
workspaces — модуль рабочих пространств
auth — авторизация
frontend — интерфейс
backend — бэкенд
deps — зависимости
ops — эксплуатация
docker — Docker
ci — CI/CD
release — релиз"""

PROMPT = """\
Ты — технический писатель. Переведи список Git-коммитов для продуктового отчёта \
о релизе {version}. Читатели — менеджеры и сотрудники поддержки, они не программисты.

Исходные коммиты:
{commits}

Словарь областей (scope) из скобок:
{scopes}

Правила:
1. Переведи на русский язык.
2. Измени глаголы с Present Simple (add, fix, update) на совершенный вид \
прошедшего времени: «была добавлена», «было исправлено», «была оптимизирована».
3. Формат строки: «• <b>Область</b>: описание.» Например, коммит \
«feat(finreports): add Balance table» → «• <b>Модуль финотчётов</b>: была \
добавлена таблица Баланс.» Если области нет — начинай сразу с описания.
4. Сгруппируй по категориям, каждая категория — заголовок <b>…</b> с новой строки:
<b>Новые функции</b> (feat), <b>Исправления</b> (fix), <b>Прочее</b> (всё остальное).
Пустые категории пропусти полностью.
5. Объедини дубликаты, убери служебный шум (например, коммиты релизного бота).
6. Пиши по существу, одна строка — один пункт, без маркетинга и без эмодзи.
7. Верни ТОЛЬКО чистый HTML для Telegram. Разрешены строго теги <b>, <i>, <code>, <a>.
Списки оформляй символом «•» в начале строки — теги <ul>, <ol>, <li>, <p> Telegram НЕ \
поддерживает. Не оборачивай ответ в ```html."""


def _redact(text: str, api_key: str) -> str:
    """Never let a key reach a log line, however the API chose to echo it."""
    return text.replace(api_key, "***") if api_key else text


def _reason(status: int, body: str, api_key: str) -> str:
    """The API's own explanation, which is the whole point of logging at all.

    The key travels in the `x-goog-api-key` header rather than the URL, so the
    response body is safe to surface — and it is the difference between "HTTP
    404" and "models/gemini-2.5-flash is not found for API version v1beta".
    The first live release was diagnosed from a screenshot because this was
    missing.
    """
    detail = body
    with contextlib.suppress(ValueError, AttributeError):
        detail = json.loads(body).get("error", {}).get("message", body)
    return f"HTTP {status}: {_redact(str(detail), api_key)[:300]}"


def _call(url: str, api_key: str, payload: dict[str, Any] | None = None) -> tuple[int, str]:
    """One request. Returns (status, body) instead of raising on 4xx/5xx."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"x-goog-api-key": api_key}
    if data is not None:
        headers["Content-Type"] = "application/json"
    # S310: a literal https base; only the path is composed here.
    req = urllib.request.Request(  # noqa: S310
        url, data=data, headers=headers, method="POST" if data else "GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310
            return int(resp.status), resp.read().decode()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode(errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # "Unreachable" is not only DNS and refused connections: a socket that
        # accepts the request and then stops answering raises TimeoutError out
        # of ssl.read, which is NOT an HTTPError and used to escape this
        # function entirely. The whole script then died, printed nothing, and
        # telegram_notify refused an empty body — so the v0.5.4 release went
        # out with no announcement at all, which is precisely the outcome the
        # English fallback exists to prevent. Reported as a synthetic 000 so
        # the caller treats it like any other failed candidate and moves on to
        # the next model.
        return 0, f"transport error: {type(exc).__name__}: {str(exc)[:200]}"


def rank_model(name: str) -> tuple[int, int, int, int, str]:
    """Sort key for candidate models: cheapest capable and newest, stable first.

    `flash` before `pro` because this is a dozen commit subjects, not an essay;
    non-`lite` before `lite`; a released model before a preview; and a higher
    version before a lower one. Names with no version sort last — `-latest`
    aliases move under you between releases, and a release note should be
    reproducible.
    """
    version = 0
    if m := re.search(r"(\d+)\.(\d+)", name):
        version = -(int(m.group(1)) * 100 + int(m.group(2)))
    return (
        0 if "flash" in name else 1,
        1 if "lite" in name else 0,
        1 if ("preview" in name or "-exp" in name) else 0,
        version,
        name,
    )


def discover_models(api_key: str) -> tuple[str, ...]:
    """Ask the API which models this key may actually use for generateContent.

    Hardcoding a model name is a slow-motion outage: it works until Google
    retires it, and then the failure is a 404 nobody sees because the fallback
    quietly ships English. Listing costs one request per release and is right
    by construction.
    """
    status, body = _call(f"{BASE}/models?pageSize=1000", api_key)
    if status != 200:
        sys.stderr.write(f"Gemini: could not list models ({_reason(status, body, api_key)}).\n")
        return ()
    try:
        models = json.loads(body).get("models", [])
    except ValueError:
        return ()

    usable = [
        name
        for entry in models
        if "generateContent" in entry.get("supportedGenerationMethods", [])
        and not any(
            word in (name := str(entry.get("name", "")).removeprefix("models/"))
            for word in _NOT_A_TRANSLATOR
        )
    ]
    return tuple(sorted(usable, key=rank_model))


def gemini(prompt: str, api_key: str, models: tuple[str, ...]) -> str:
    """Ask the first model that answers. Returns "" when all of them fail."""
    for model in models:
        # Plain request FIRST, thinking disabled second. thinkingBudget=0 is a
        # remedy for one specific failure — a reasoning model spending its whole
        # output budget before writing a word, which shows up as an empty
        # completion — and not every model accepts the field: gemini-3.6-flash
        # answers 400 to it. Leading with it spent one guaranteed-failed request
        # and a 400 in the log on every single release.
        for config in (
            {"temperature": 0.2, "maxOutputTokens": 4096},
            {"temperature": 0.2, "maxOutputTokens": 4096, "thinkingConfig": {"thinkingBudget": 0}},
        ):
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": config}
            for attempt in range(3):
                status, body = _call(f"{BASE}/models/{model}:generateContent", api_key, payload)

                if status == 200:
                    try:
                        parts = json.loads(body)["candidates"][0]["content"]["parts"]
                    except (ValueError, KeyError, IndexError):
                        sys.stderr.write(f"Gemini {model}: unreadable 200 response.\n")
                        break
                    if text := "".join(p.get("text", "") for p in parts).strip():
                        sys.stderr.write(f"Gemini: translated with {model}.\n")
                        return text
                    sys.stderr.write(f"Gemini {model}: empty completion.\n")
                    break

                if status == 400:
                    # This config, not this model — drop thinkingConfig and retry.
                    sys.stderr.write(f"Gemini {model}: {_reason(status, body, api_key)}\n")
                    break

                if status in (429, 500, 502, 503, 504) and attempt < 2:
                    # Retries used to be silent, which is how a rate-limited
                    # model burned 36 seconds and left no trace in the log.
                    sys.stderr.write(
                        f"Gemini {model}: {_reason(status, body, api_key)} "
                        f"— retry {attempt + 1}/2.\n"
                    )
                    time.sleep(3 * (attempt + 1))
                    continue

                sys.stderr.write(f"Gemini {model}: {_reason(status, body, api_key)}\n")
                break
    return ""


# `[a-z-]` and not `[a-z]`: `feat-minor` is a type here (see docs/RELEASES.md),
# and with the tighter class it matched nothing and every small feature landed
# under «Прочее».
CONVENTIONAL = re.compile(r"^(?P<type>[a-z][a-z-]*)(?:\((?P<scope>[^)]*)\))?!?:\s*(?P<subject>.+)$")

# Release Please's own merge commit, in every shape it writes one. Its title
# depends on config in ways that are not obvious — a single-package manifest
# still runs the Merge plugin, which discards the configured title pattern and
# writes `chore: release main` — so this matches the family rather than one
# literal. The commit announcing the release is not news inside the release.
RELEASE_BOT = re.compile(r"^chore(\([^)]*\))?:\s*(release\b|v?\d+\.\d+\.\d+)", re.IGNORECASE)

SECTIONS = (
    ("feat", "Новые функции"),
    ("feat-minor", "Мелкие функции"),
    ("fix", "Исправления"),
    (None, "Прочее"),
)


def fallback(commits: list[str]) -> str:
    """Grouped, untranslated notes — used only when Gemini is unavailable."""
    # Keyed off SECTIONS so a new section needs one edit, not two: the previous
    # shape hard-coded the type list here as well, which is how «Мелкие функции»
    # would have arrived with its own heading and nothing under it.
    buckets: dict[str, list[str]] = {key or "other": [] for key, _ in SECTIONS}
    for line in commits:
        m = CONVENTIONAL.match(line)
        if not m:
            buckets["other"].append(html.escape(line))
            continue
        scope = m.group("scope")
        subject = html.escape(m.group("subject"))
        entry = f"• <b>{html.escape(scope)}</b>: {subject}" if scope else f"• {subject}"
        kind = m.group("type")
        buckets[kind if kind in buckets else "other"].append(entry)

    out = ["<i>(перевод недоступен, список на английском)</i>"]
    for key, title in SECTIONS:
        entries = buckets[key or "other"]
        if entries:
            out.append(f"\n<b>{title}</b>\n" + "\n".join(entries))
    return "\n".join(out)


def main() -> int:
    version = os.environ.get("VERSION", "").strip() or "?"
    tag = os.environ.get("TAG", "").strip()

    commits = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    # The release bot's own commit is never news to anyone.
    commits = [c for c in commits if not RELEASE_BOT.match(c)]

    if not commits:
        sys.stderr.write("No commits to announce.\n")
        return 0

    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()

    body = ""
    if api_key:
        candidates = discover_models(api_key)[:MAX_CANDIDATES] or FALLBACK_MODELS
        # An explicit GEMINI_MODEL is prepended rather than substituted, so a
        # stale repository variable degrades to "tried first" instead of
        # disabling translation outright.
        if override := (os.environ.get("GEMINI_MODEL") or "").strip():
            candidates = (override, *(m for m in candidates if m != override))
        sys.stderr.write(f"Gemini: candidates {', '.join(candidates)}\n")

        body = gemini(
            PROMPT.format(version=version, commits="\n".join(commits), scopes=SCOPES),
            api_key,
            candidates,
        )
    else:
        sys.stderr.write("GEMINI_API_KEY is not set; falling back to English notes.\n")

    if not body:
        body = fallback(commits)

    # Deliberately just the version. The repository is private, so its name and
    # a GitHub link are noise to every recipient who cannot open them — and the
    # people who can already know where it lives.
    header = f"<b>Релиз {html.escape(tag or 'v' + version)}</b>"

    print(f"{header}\n\n{body}".strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
