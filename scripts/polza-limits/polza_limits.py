#!/usr/bin/env python3
"""Суточный лимит Polza.ai по ключу владельца — компактный JSON для чипа.

Ключ (значение в вывод не попадает):

  * HERMES_CUSTOM_POLZA_AI_API_KEY из %LOCALAPPDATA%\\hermes\\.env

Порядок работы: сначала /key и /balance (полоса и кошелёк готовы, даже если
история не досчитается), затем генерации за местные сутки с жёстким дедлайном —
плагин получает от shell.exec только 30 с и хвост stdout в 4000 символов.

Формат: одна строка JSON
  {"ok":true,"day":"2026-10-14","k":[
     {"p":"мой ключ","limit":500.0,"used":174.63,"left":325.37,"reset":"daily",
      "amount":4829.57,"avail":325.37,
      "gen":45,"tin":4105847,"tout":52856,"tcache":3038816,
      "m":["DeepSeek: DeepSeek V4.1 Flash\\x1f30.25\\x1f45\\x1f4105847\\x1f52856\\x1f3038816", ...]}]}

Модели — плоские строки через \\x1f (имя, рубли, число запросов, вход, выход,
кэш): объекты с длинными ключами не влезают в бюджет вывода.

Токены берутся из usage каждой генерации. Важно, что prompt_tokens ВКЛЮЧАЕТ
cached_tokens — во входе доля кэша доходит до 90%, а кэш-чтение дешевле
примерно вчетверо. Поэтому вход отдаётся разбитым (tin — весь вход, tcache —
его кэшовая часть), иначе цифра входа не объясняет счёт.

Совместимость: поля tin/tout/tcache и хвост строки модели добавлены позже.
Плагин обязан переживать их отсутствие.
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://polza.ai/api/v1"
HERE = os.path.dirname(os.path.abspath(__file__))

# Метка, .env, имя переменной. Путь к корневому .env агента: у получателя
# установка кладёт персону, конфиг и ключ именно туда.
TARGETS = [
    ("мой ключ",
     os.path.expandvars(r"%LOCALAPPDATA%\hermes\.env"),
     "HERMES_CUSTOM_POLZA_AI_API_KEY"),
]

GROUP_SHARE = 0.001     # порог «мелочи»: доля от суточного расхода
GROUP_RUB = 0.05        # порог «мелочи»: абсолютная сумма
MAX_MODELS = 6          # на ключ; плюс «Другое»
OUT_BUDGET = 3400       # оставляем запас до 4000 символов shell.exec
GEN_DEADLINE_S = 18.0   # генерации не должны съесть 30-секундный потолок


def read_key(path: str, name: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return None
    m = re.search(rf"^{re.escape(name)}=(.+)$", text, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else None


def api_get(path: str, key: str, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_generations(key: str, start: datetime.datetime, end: datetime.datetime) -> list[dict]:
    """Все генерации за сутки, но не дольше GEN_DEADLINE_S суммарно."""
    items: list[dict] = []
    page = 1
    deadline = time.monotonic() + GEN_DEADLINE_S
    while page <= 20:
        if time.monotonic() > deadline:
            break
        query = urllib.parse.urlencode({
            "limit": 100,
            "page": page,
            "dateFrom": start.isoformat(),
            "dateTo": end.isoformat(),
            "sortBy": "createdAt",
            "sortOrder": "desc",
        })
        try:
            data = api_get("/history/generations?" + query, key)
        except Exception:
            break
        batch = data.get("items") or []
        items.extend(batch)
        meta = data.get("meta") or {}
        if page >= int(meta.get("totalPages") or 1) or not batch:
            break
        page += 1
    return items


def compact_models(rows: list[tuple], total: float, max_models: int) -> list[str]:
    """Строки моделей в бюджет вывода: имя␟рубли␟запросы␟вход␟выход␟кэш."""
    head, dropped = [], []
    for row in rows:
        cost = row[1]
        if (cost >= GROUP_RUB and (total <= 0 or cost / total >= GROUP_SHARE)
                and len(head) < max_models):
            head.append(row)
        else:
            dropped.append(row)
    out = [f"{r[0].replace(chr(31), ' ')}\x1f{r[1]:.2f}\x1f{r[2]}\x1f{r[3]}\x1f{r[4]}\x1f{r[5]}"
           for r in head]
    if dropped:
        tail = [sum(r[i] for r in dropped) for i in (1, 2, 3, 4, 5)]
        if tail[0] > 0.0 or tail[1]:
            out.append(f"Другое\x1f{tail[0]:.2f}\x1f{tail[1]}\x1f{tail[2]}\x1f{tail[3]}\x1f{tail[4]}")
    return out


def collect(label: str, env_path: str, env_name: str,
            start: datetime.datetime, end: datetime.datetime) -> dict:
    row: dict = {"p": label}
    key = read_key(env_path, env_name)
    if not key:
        row["err"] = f"ключ {env_name} не найден в .env"
        return row

    try:
        info = api_get("/key", key)
    except Exception as exc:
        row["err"] = f"{type(exc).__name__}: {exc}"
        return row

    row.update({
        "limit": float(info.get("limit") or 0),
        "used": float(info.get("usage_daily") or 0),
        "left": float(info.get("limit_remaining") or 0),
        "reset": info.get("limit_reset") or "",
        "week": float(info.get("usage_weekly") or 0),
    })

    try:
        bal = api_get("/balance", key)
        row["amount"] = float(bal.get("amount") or 0)
        row["avail"] = float(bal.get("available") or 0)
    except Exception:
        pass

    items = fetch_generations(key, start, end)
    # на модель: рубли, запросы, вход, выход, кэш
    per: dict[str, list] = collections.defaultdict(lambda: [0.0, 0, 0, 0, 0])
    for it in items:
        name = it.get("modelDisplayName") or it.get("model") or "—"
        usage = it.get("usage") or {}
        pdet = usage.get("prompt_tokens_details") or {}
        per[name][0] += float(it.get("cost") or 0)
        per[name][1] += 1
        per[name][2] += int(usage.get("prompt_tokens") or 0)
        per[name][3] += int(usage.get("completion_tokens") or 0)
        per[name][4] += int(pdet.get("cached_tokens") or 0)
    rows = sorted(((n, v[0], v[1], v[2], v[3], v[4]) for n, v in per.items()),
                  key=lambda r: -r[2])
    row["gen"] = sum(r[2] for r in rows)
    row["tin"] = sum(r[3] for r in rows)
    row["tout"] = sum(r[4] for r in rows)
    row["tcache"] = sum(r[5] for r in rows)
    row["_rows"] = rows
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pretty", action="store_true", help="человекочитаемый вывод")
    args = ap.parse_args()

    now = datetime.datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    rows = [collect(label, path, name, start, now) for label, path, name in TARGETS]

    # Модели укладываем в бюджет: пробуем 6 → 4 → 2 → 0 на ключ.
    keys_models = [(r, r.pop("_rows", [])) for r in rows]
    payload: dict = {}
    for cap in (MAX_MODELS, 4, 2, 0):
        for r, src in keys_models:
            total = sum(row[1] for row in src)
            r["m"] = compact_models(src, total, cap) if cap else []
        payload = {"ok": True, "day": start.strftime("%Y-%m-%d"), "k": rows}
        flat = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(flat) <= OUT_BUDGET:
            break

    if args.pretty:
        for r in rows:
            if r.get("err"):
                print(f"{r['p']}: ОШИБКА {r['err']}")
                continue
            pct = (r["used"] / r["limit"] * 100) if r["limit"] else 0.0
            print(f"{r['p']}: {r['used']:.2f} из {r['limit']:.2f} ₽ ({pct:.1f} %), "
                  f"остаток {r['left']:.2f} ₽, генераций {r.get('gen', 0)}, сброс {r['reset']}")
            print(f"    токены за сутки: вход {r.get('tin', 0):,} "
                  f"(из них из кэша {r.get('tcache', 0):,}) · выход {r.get('tout', 0):,}")
            print(f"    {'модель':<34}{'₽':>9}{'запр':>7}{'вход':>12}{'выход':>9}{'кэш':>12}")
            for m in r["m"]:
                n, c, k, tin, tout, cache = m.split("\x1f")
                print(f"    {n[:34]:<34}{float(c):>9.2f}{k:>7}{int(tin):>12,}{int(tout):>9,}{int(cache):>12,}")
        return 0

    json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
