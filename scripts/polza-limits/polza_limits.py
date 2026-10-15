#!/usr/bin/env python3
"""Суточные лимиты Polza.ai по ДВУМ ключам профилей — компактный JSON для чипа.

Ключи (значения в вывод не попадают):

  * default + local → CUSTOM_PROVIDER_POLZA_AI_KEY  из %LOCALAPPDATA%\\hermes\\.env
  * ai-si           → HERMES_CUSTOM_POLZA_AI_API_KEY из %LOCALAPPDATA%\\hermes\\profiles\\ai-si\\.env

Порядок работы: сначала /key и /balance на каждый ключ (полосы готовы даже если
история не досчитается), затем генерации за местные сутки с жёстким дедлайном —
плагин получает от shell.exec только 30 с и хвост stdout в 4000 символов.

Формат: одна строка JSON
  {"ok":true,"day":"2026-10-14","k":[
     {"p":"default + local","limit":500.0,"used":174.63,"left":325.37,"reset":"daily",
      "amount":4829.57,"avail":325.37,
      "m":["DeepSeek: DeepSeek V4.1 Flash\\x1f169.80\\x1f518", ...]},
     {"p":"ai-si","limit":1500.0,...,"m":[...]}]}

Модели — плоские строки через \\x1f (имя, рубли, число запросов): объекты с
длинными ключами не влезают в бюджет вывода.
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


def compact_models(rows: list[tuple[str, float, int]], total: float, max_models: int) -> list[str]:
    head, dropped = [], []
    for name, cost, count in rows:
        if (cost >= GROUP_RUB and (total <= 0 or cost / total >= GROUP_SHARE)
                and len(head) < max_models):
            head.append((name, cost, count))
        else:
            dropped.append((cost, count))
    out = [f"{n.replace(chr(31), ' ')}\x1f{c:.2f}\x1f{k}" for n, c, k in head]
    tail_cost = sum(c for c, _ in dropped)
    tail_count = sum(k for _, k in dropped)
    if tail_cost > 0.0 or tail_count:
        out.append(f"Другое\x1f{tail_cost:.2f}\x1f{tail_count}")
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
    per: dict[str, list] = collections.defaultdict(lambda: [0.0, 0])
    for it in items:
        cost = float(it.get("cost") or 0)
        name = it.get("modelDisplayName") or it.get("model") or "—"
        per[name][0] += cost
        per[name][1] += 1
    rows = sorted(((n, v[0], v[1]) for n, v in per.items()), key=lambda r: -r[1])
    row["gen"] = sum(r[2] for r in rows)
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
            total = sum(c for _, c, _ in src)
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
            for m in r["m"]:
                n, c, k = m.split("\x1f")
                print(f"    {float(c):>8.2f} ₽ {k:>5}  {n}")
        return 0

    json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
