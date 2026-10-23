#!/usr/bin/env python3
"""Модели Polza.ai: фактические ставки по своим генерациям + прайс каталога.

Зачем два источника. Прайс каталога (`top_provider.pricing`) — это НЕ то, что
списывают. Проверено на своих генерациях за 7 суток, ставка входа:

    openai/gpt-6.1-sol             282,18 ₽/1M   каталог 118,09   ×2,39
    anthropic/claude-sonnet-5.5    238,70         каталог 236,18   ×1,01
    google/gemini-3-flash-preview   61,37         каталог  29,52   ×2,08
    deepseek/deepseek-v4.1-flash    50,67         каталог   5,78   ×8,76

Множитель гуляет от 1,01 до 8,76: каталог не просто занижен, он занижен
ПО-РАЗНОМУ, поэтому порядок моделей по нему не совпадает с порядком по деньгам.
У DeepSeek в каталоге цена кэша вообще 0,00, а фактически кэш-чтение стоит
0,72 ₽/1M и даёт 280 ₽ из 2 298 ₽ за неделю.

Поэтому:
  * модели, которыми уже пользовались, идут со СВОЕЙ фактической ставкой —
    она считается из costLines каждой генерации (`clientRub` / `quantity`);
  * остальные — с прайсом каталога и пометкой «не факт».

Источник факта: GET /history/generations, поле costLines — по каждому виду
токенов своя строка с quantity и clientRub. Это и есть списанные рубли; из
поля cost ставку не вывести, там нет разбивки по видам.

Формат: одна строка JSON
  {"ok":true,"nf":4,"nc":40,"cur":"RUB","min":50.67,"shown":44,
   "m":["ф\\x1fdeepseek/deepseek-v4.1-flash\\x1fDeepSeek: DeepSeek V4.1 Flash\\x1f50.67\\x1f105.79\\x1f0.72\\x1f1921\\x1f2298.47", ...]}

Поля строки: источник («ф» факт / «п» прайс), id, имя, вход, выход, кэш, запросов,
всего рублей. Источник — первое поле, потому что по нему плагин раскладывает
список на две секции.

ВАЖНО про бюджет вывода: плагин получает от shell.exec только ХВОСТ stdout
(4000 символов). Список печатается от дешёвого и ужимается под бюджет, иначе
обрезка съела бы именно дешёвые модели — самое ценное здесь.
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
ENV_PATHS = [r"%LOCALAPPDATA%\hermes\.env"]
ENV_KEY = "HERMES_CUSTOM_POLZA_AI_API_KEY"

MAX_ROWS = 40            # строк каталога (строки факта печатаются все)
CATALOG_DEADLINE_S = 12
HISTORY_DEADLINE_S = 20

# Виды строк в costLines, раскладываемые по колонкам карточки.
KIND_PROMPT = "prompt"
KIND_COMPLETION = "completion"
KIND_CACHE = "cached_read"


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


def api_get(path: str, key: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def catalog(key: str) -> tuple:
    """Чат-модели с прайсом каталога, по возрастанию цены входа."""
    rows, currency = [], "RUB"
    deadline = time.monotonic() + CATALOG_DEADLINE_S
    for x in (api_get("/models", key).get("data") or []):
        if time.monotonic() > deadline:
            break
        if x.get("type") != "chat":
            continue
        p = ((x.get("top_provider") or {}).get("pricing") or {})
        pin = num(p.get("prompt_per_million"))
        if pin <= 0:
            continue
        currency = p.get("currency") or currency
        rows.append((pin, num(p.get("completion_per_million")),
                     num(p.get("input_cache_read_per_million")),
                     x.get("id") or "?", x.get("name") or x.get("id") or "?"))
    rows.sort(key=lambda r: (r[0], r[1], r[3]))
    return rows, currency


def history(key: str, days: int) -> list:
    """Генерации за окно с жёстким дедлайном: у плагина всего 30 с."""
    end = datetime.datetime.now()
    start = end - datetime.timedelta(days=days)
    items, page = [], 1
    deadline = time.monotonic() + HISTORY_DEADLINE_S
    while page <= 25:
        if time.monotonic() > deadline:
            break
        query = urllib.parse.urlencode({
            "limit": 100, "page": page,
            "dateFrom": start.isoformat(), "dateTo": end.isoformat(),
            "sortBy": "createdAt", "sortOrder": "desc",
        })
        try:
            data = api_get("/history/generations?" + query, key)
        except Exception:
            break
        batch = data.get("items") or []
        items.extend(batch)
        if page >= int((data.get("meta") or {}).get("totalPages") or 1) or not batch:
            break
        page += 1
    return items


def actual(items: list) -> dict:
    """Фактические ставки: модель → вид → ставка ₽ за 1 млн.

    Считаем costLines, а не cost: costLines дают количество и списанные рубли
    отдельно по каждому виду, из них ставка получается делением.
    """
    per = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0.0]))
    gen = collections.Counter()
    for it in items:
        mid = it.get("model") or "?"
        gen[mid] += 1
        for ln in (it.get("costLines") or []):
            kind = ln.get("kind") or "?"
            per[mid][kind][0] += int(num(ln.get("quantity")))
            per[mid][kind][1] += num(ln.get("clientRub"))
    out = {}
    for mid, kinds in per.items():
        out[mid] = {k: (rub / qty * 1e6 if qty else 0.0) for k, (qty, rub) in kinds.items()}
        out[mid]["_total"] = sum(v[1] for v in kinds.values())
        out[mid]["_gen"] = gen[mid]
    return out


def build(key: str, days: int):
    cat, currency = catalog(key)
    fact = actual(history(key, days))
    names = {r[3]: r[4] for r in cat}

    fact_rows = []
    for mid, r in fact.items():
        pin = r.get(KIND_PROMPT, 0.0)
        if pin <= 0:
            continue
        fact_rows.append((pin, r.get(KIND_COMPLETION, 0.0), r.get(KIND_CACHE, 0.0), mid,
                          names.get(mid, mid), r["_gen"], r["_total"]))
    fact_rows.sort(key=lambda x: (x[0], x[3]))

    used = {r[3] for r in fact_rows}
    cat_rows = [r for r in cat if r[3] not in used]

    meta = {
        "cur": currency,
        "nf": len(fact_rows),
        "nc": len(cat_rows),
        "min": round(fact_rows[0][0] if fact_rows else (cat_rows[0][0] if cat_rows else 0.0), 2),
    }
    return fact_rows, cat_rows, meta


def fmt(fact_rows, cat_rows, meta, limit: int) -> str:
    rows = [f"ф\x1f{r[3]}\x1f{r[4]}\x1f{r[0]:.2f}\x1f{r[1]:.2f}\x1f{r[2]:.2f}\x1f{r[5]}\x1f{r[6]:.2f}"
            for r in fact_rows]
    rows += [f"п\x1f{r[3]}\x1f{r[4]}\x1f{r[0]:.2f}\x1f{r[1]:.2f}\x1f{r[2]:.2f}\x1f0\x1f0.00"
             for r in cat_rows[:limit]]
    payload = dict(meta)
    payload.update({"ok": True, "shown": len(rows), "m": rows})
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Модели Polza.ai: факт и прайс каталога")
    ap.add_argument("--days", type=int, default=30, help="окно истории для фактических ставок")
    ap.add_argument("--limit", type=int, default=MAX_ROWS, help="сколько строк каталога показать")
    ap.add_argument("--pretty", action="store_true", help="таблицы для чтения глазами")
    ap.add_argument("--budget", type=int, default=3900, help="предел длины вывода")
    args = ap.parse_args()

    fact_rows, cat_rows, meta = build(read_key(), args.days)
    if not fact_rows and not cat_rows:
        print(json.dumps({"ok": False, "err": "нет данных ни по факту, ни по каталогу"},
                         ensure_ascii=False))
        return 1

    if not args.pretty:
        limit = args.limit
        line = fmt(fact_rows, cat_rows, meta, limit)
        # ужимаем, пока не влезет: плагин видит только хвост stdout
        while len(line) > args.budget and limit > 5:
            limit -= 5
            line = fmt(fact_rows, cat_rows, meta, limit)
        print(line)
        return 0

    print(f"факт по {meta['nf']} своим моделям (окно {args.days} сут) · "
          f"каталог {meta['nc']} моделей · {meta['cur']} за 1 млн токенов\n")
    print("ПО ФАКТУ СПИСАНИЯ (costLines)")
    print(f"  {'модель':<38}{'вход':>10}{'выход':>10}{'кэш':>9}{'запр':>7}{'всего руб':>12}")
    for r in fact_rows:
        print(f"  {r[4][:38]:<38}{r[0]:>10.2f}{r[1]:>10.2f}{r[2]:>9.2f}{r[5]:>7}{r[6]:>12.2f}")
    print("\nПРАЙС КАТАЛОГА — НЕ ФАКТ")
    print(f"  {'модель':<38}{'вход':>10}{'выход':>10}{'кэш':>9}  id")
    for r in cat_rows[:args.limit]:
        print(f"  {r[4][:38]:<38}{r[0]:>10.2f}{r[1]:>10.2f}{r[2]:>9.2f}  {r[3]}")
    if len(cat_rows) > args.limit:
        print(f"  ... ещё {len(cat_rows) - args.limit} моделей дороже")
    return 0


if __name__ == "__main__":
    sys.exit(main())
