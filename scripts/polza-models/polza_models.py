#!/usr/bin/env python3
"""Каталог моделей Polza.ai, отсортированный от дешёвых к дорогим.

Зачем: выбирать модель по цене, а не по названию. Один и тот же класс задач
различается в цене на три порядка (1,63 ₽ против 17 713 ₽ за миллион токенов),
поэтому «дорогая модель» — не синоним «лучшая»: для черновой работы и для
аудита нужны разные.

Источник: GET /api/v1/models, поле top_provider.pricing.
  prompt_per_million       — вход, ₽ за 1 млн токенов
  completion_per_million   — выход, ₽ за 1 млн токенов
  input_cache_read_per_million — чтение из кэша, ₽ за 1 млн (в 10–15 раз дешевле входа)
  currency                 — в каталоге указан RUB; значения уже в рублях

ВАЖНО про бюджет вывода: плагин получает от shell.exec только ХВОСТ stdout
(4000 символов). Поэтому список печатается от самого дешёвого, длина ограничена,
а в конце идёт строка-сводка. Иначе обрезка съела бы именно дешёвые модели —
самое ценное в этом списке.

Формат: одна строка JSON
  {"ok":true,"n":308,"min":1.63,"max":17713.20,"cur":"RUB","m":[
     "qwen/qwen3.5-9b\\x1fQwen: Qwen3.5 9B\\x1f1.63\\x1f4.89\\x1f0.33", ...]}
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://polza.ai/api/v1"
ENV_PATHS = [r"%LOCALAPPDATA%\hermes\.env"]
ENV_KEY = "HERMES_CUSTOM_POLZA_AI_API_KEY"

# Хвост stdout у плагина — 4000 символов. Оставляем запас на служебные поля.
MAX_ROWS = 40


def read_key() -> str:
    key = (os.environ.get("POLZA_AI_API_KEY") or os.environ.get(ENV_KEY) or "").strip()
    if key:
        return key
    for raw in ENV_PATHS:
        path = raw.replace("%LOCALAPPDATA%", os.environ.get("LOCALAPPDATA", ""))
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                m = re.search(rf"^{ENV_KEY}=(.+)$", fh.read(), re.M)
            if m:
                return m.group(1).strip().strip('"').strip("'")
        except OSError:
            continue
    sys.exit("Не найден ключ Polza.ai в .env")


def fetch(key: str, timeout: int = 30) -> list:
    req = urllib.request.Request(API + "/models", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8")).get("data") or []


def num(p: dict, field: str) -> float:
    try:
        return float(p.get(field) or 0)
    except (TypeError, ValueError):
        return 0.0


def collect(items: list) -> tuple[list, str]:
    """Только чат-модели с ценой входа. Сортировка по входу, затем по выходу."""
    rows, currency = [], "RUB"
    for x in items:
        if x.get("type") != "chat":
            continue
        p = ((x.get("top_provider") or {}).get("pricing") or {})
        pin = num(p, "prompt_per_million")
        if pin <= 0:
            continue
        currency = p.get("currency") or currency
        rows.append((
            pin,
            num(p, "completion_per_million"),
            num(p, "input_cache_read_per_million"),
            x.get("id") or "?",
            x.get("name") or x.get("id") or "?",
        ))
    rows.sort(key=lambda r: (r[0], r[1], r[3]))
    return rows, currency


def fmt(rows: list, currency: str, limit: int) -> str:
    head = rows[:limit]
    out = [
        f"{r[3]}\x1f{r[4]}\x1f{r[0]:.2f}\x1f{r[1]:.2f}\x1f{r[2]:.2f}"
        for r in head
    ]
    payload = {
        "ok": True,
        "n": len(rows),
        "shown": len(head),
        "min": round(rows[0][0], 2) if rows else 0.0,
        "max": round(rows[-1][0], 2) if rows else 0.0,
        "cur": currency,
        "m": out,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Модели Polza.ai по возрастанию цены")
    ap.add_argument("--limit", type=int, default=MAX_ROWS, help="сколько моделей показать")
    ap.add_argument("--pretty", action="store_true", help="таблица для чтения глазами")
    ap.add_argument("--budget", type=int, default=3900, help="предел длины вывода")
    args = ap.parse_args()

    rows, currency = collect(fetch(read_key()))
    if not rows:
        print(json.dumps({"ok": False, "err": "каталог пуст"}, ensure_ascii=False))
        return 1

    if not args.pretty:
        limit = args.limit
        line = fmt(rows, currency, limit)
        # ужимаем, пока не влезет: плагин видит только хвост stdout
        while len(line) > args.budget and limit > 5:
            limit -= 5
            line = fmt(rows, currency, limit)
        print(line)
        return 0

    print(f"чат-моделей с ценой: {len(rows)} · валюта {currency} · "
          f"от {rows[0][0]:.2f} до {rows[-1][0]:.2f} ₽ за 1 млн токенов\n")
    print(f"{'модель':<44}{'вход':>10}{'выход':>10}{'кэш':>9}  id")
    for r in rows[:args.limit]:
        print(f"{r[4][:44]:<44}{r[0]:>10.2f}{r[1]:>10.2f}{r[2]:>9.2f}  {r[3]}")
    if len(rows) > args.limit:
        print(f"... ещё {len(rows) - args.limit} моделей дороже")
    return 0


if __name__ == "__main__":
    sys.exit(main())
