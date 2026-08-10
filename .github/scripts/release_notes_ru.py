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

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Ordered fallback: the first model that answers wins. Overridable with
# GEMINI_MODEL, which is prepended to the list rather than replacing it, so a
# typo in a repository variable cannot silently disable translation.
DEFAULT_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash")

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


def gemini(prompt: str, api_key: str, models: tuple[str, ...]) -> str:
    """Ask the first model that answers. Returns "" when all of them fail."""
    for model in models:
        # thinkingBudget=0 keeps a reasoning model from spending the whole
        # output budget before it writes a word; older models reject the field,
        # hence the second, plainer attempt.
        for config in (
            {"temperature": 0.2, "maxOutputTokens": 4096, "thinkingConfig": {"thinkingBudget": 0}},
            {"temperature": 0.2, "maxOutputTokens": 4096},
        ):
            body = json.dumps(
                {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": config}
            ).encode()
            # S310: a literal https endpoint; only the model name is interpolated.
            req = urllib.request.Request(  # noqa: S310
                ENDPOINT.format(model=model),
                data=body,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                method="POST",
            )
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310
                        payload = json.loads(resp.read().decode())
                    parts = payload["candidates"][0]["content"]["parts"]
                    text = "".join(p.get("text", "") for p in parts).strip()
                    if text:
                        return text
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code == 400:
                        break  # bad request for THIS config — try the next one
                    if exc.code in (429, 500, 502, 503, 504):
                        time.sleep(3 * (attempt + 1))
                        continue
                    sys.stderr.write(f"Gemini {model}: HTTP {exc.code}.\n")
                    break
                except Exception as exc:  # translation must never fail the release
                    sys.stderr.write(f"Gemini {model}: {type(exc).__name__}: {exc}\n")
                    time.sleep(3 * (attempt + 1))
    return ""


CONVENTIONAL = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?!?:\s*(?P<subject>.+)$")

# Release Please's own merge commit, in every shape it writes one. Its title
# depends on config in ways that are not obvious — a single-package manifest
# still runs the Merge plugin, which discards the configured title pattern and
# writes `chore: release main` — so this matches the family rather than one
# literal. The commit announcing the release is not news inside the release.
RELEASE_BOT = re.compile(r"^chore(\([^)]*\))?:\s*(release\b|v?\d+\.\d+\.\d+)", re.IGNORECASE)

SECTIONS = (
    ("feat", "Новые функции"),
    ("fix", "Исправления"),
    (None, "Прочее"),
)


def fallback(commits: list[str]) -> str:
    """Grouped, untranslated notes — used only when Gemini is unavailable."""
    buckets: dict[str, list[str]] = {"feat": [], "fix": [], "other": []}
    for line in commits:
        m = CONVENTIONAL.match(line)
        if not m:
            buckets["other"].append(html.escape(line))
            continue
        scope = m.group("scope")
        subject = html.escape(m.group("subject"))
        entry = f"• <b>{html.escape(scope)}</b>: {subject}" if scope else f"• {subject}"
        buckets[m.group("type") if m.group("type") in ("feat", "fix") else "other"].append(entry)

    out = ["<i>(перевод недоступен, список на английском)</i>"]
    for key, title in SECTIONS:
        entries = buckets[key or "other"]
        if entries:
            out.append(f"\n<b>{title}</b>\n" + "\n".join(entries))
    return "\n".join(out)


def main() -> int:
    version = os.environ.get("VERSION", "").strip() or "?"
    tag = os.environ.get("TAG", "").strip()
    repo = os.environ.get("REPO", "").strip()
    url = os.environ.get("RELEASE_URL", "").strip()

    commits = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    # The release bot's own commit is never news to anyone.
    commits = [c for c in commits if not RELEASE_BOT.match(c)]

    if not commits:
        sys.stderr.write("No commits to announce.\n")
        return 0

    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    models: tuple[str, ...] = DEFAULT_MODELS
    if override := (os.environ.get("GEMINI_MODEL") or "").strip():
        models = (override, *(m for m in DEFAULT_MODELS if m != override))

    body = ""
    if api_key:
        body = gemini(
            PROMPT.format(version=version, commits="\n".join(commits), scopes=SCOPES),
            api_key,
            models,
        )
    else:
        sys.stderr.write("GEMINI_API_KEY is not set; falling back to English notes.\n")

    if not body:
        body = fallback(commits)

    header = f"🚀 <b>Релиз {html.escape(tag or 'v' + version)}</b>"
    if repo:
        header += f"\n<code>{html.escape(repo)}</code>"

    footer = ""
    if url:
        footer = f'\n<a href="{html.escape(url, quote=True)}">Полный список изменений</a>'

    print(f"{header}\n\n{body}\n{footer}".strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
