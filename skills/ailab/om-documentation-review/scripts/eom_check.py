#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eom_check.py — механическая проверка тома ЭОМ / ИОС1.1 (шаги 1 и 2 из методики).

Что делает БЕЗ модели, только кодом:
  1. Карта тома: страницы, наличие текстового слоя, где ПЗ/ГЧ.
  2. Шифры основных надписей по каждой странице + расхождения с шифром комплекта
     (ищет вклеенные листы чужого объекта).
  3. Перечень всех обозначений НТД с номерами страниц и контекстом -> задание для базы.
  4. Нумерация таблиц: пропуски и дубли номеров.
  5. Арифметика таблиц нагрузок: суммы Ру/Рр/Qр/Sр, сверка с "Итого" и "Итого ВРУ".
  6. Строки, исключённые из ОБОИХ сезонных режимов (выпавшие нагрузки).
  7. Внутренние проверки: Sр = sqrt(Pр^2+Qр^2), cos(phi), tg(phi).

Запуск:
    python eom_check.py <файл.pdf> [-o <папка вывода>] [--cipher МП-18/1604-ИОС1.1]

Выход в папке <pdf>_check/:
    report.md        — итоговый протокол механической проверки
    ntd_task.md      — задание для базы НТД (шаг 2, проверить вручную/через MCP)
    rows.csv         — все разобранные строки таблиц нагрузок (для перепроверки)
    pages.json       — извлечённый текст по страницам

Важно: скрипт НЕ проверяет статусы НТД (это база, не текст) и НЕ читает графику.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    sys.exit("нужен pypdf:  uv pip install pypdf")

NUM = r"\d+(?:[.,]\d+)?"


# ─────────────────────────────────────────────────────────── извлечение

def extract_pages(pdf: Path) -> list[dict]:
    reader = PdfReader(str(pdf))
    out = []
    for i, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        out.append({"page": i, "chars": len(text.strip()), "text": text})
    return out


def norm_space(s: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", s).strip()


# ─────────────────────────────────────────────────────────── 1. карта тома

def volume_map(pages: list[dict]) -> dict:
    total = len(pages)
    empty = [p["page"] for p in pages if p["chars"] < 50]
    thin = [p["page"] for p in pages if 50 <= p["chars"] < 300]
    chars = sum(p["chars"] for p in pages)

    # где текстовая часть, где графика — по плотности текста
    heavy = [p["page"] for p in pages if p["chars"] >= 800]
    graphic_from = None
    if heavy:
        # графика начинается там, где после плотного блока пошёл разреженный
        for i in range(1, len(heavy)):
            if heavy[i] - heavy[i - 1] > 3:
                graphic_from = heavy[i]
                break

    return {
        "pages": total,
        "chars": chars,
        "empty": empty,
        "thin": thin,
        "graphic_from": graphic_from,
        "no_text_layer": len(empty) > total * 0.5,
    }


# ─────────────────────────────────────────────────────────── 2. шифры штампов

CIPHER_RE = re.compile(r"([А-ЯЁA-Z][А-ЯЁA-Z0-9\s\-/]{1,28}?)\s*-\s*ИОС\s*(\d+(?:[.,]\d+)?)")


def norm_cipher(raw: str, part: str) -> str:
    """Приводит шифр к канонической форме: убирает пробелы вокруг дефисов."""
    s = re.sub(r"\s+", "", raw.upper().replace("Ё", "Е"))
    s = re.sub(r"-{2,}", "-", s)
    return f"{s}-ИОС{part.replace(',', '.')}"


def scan_ciphers(pages: list[dict]) -> dict:
    per_page: dict[int, list[str]] = {}
    counter: Counter = Counter()
    for p in pages:
        found = []
        for m in CIPHER_RE.finditer(p["text"]):
            # В плотных штампах (А3) к шифру приклеивается имя щита:
            # «ГРЩШРКП-ГП-ПИР-4-П-ИОС1.1». Обрезать «на глаз» нельзя — можно
            # срезать половину настоящего шифра (ШРКП-ГП-ПИР-4 -> ПИР-4).
            # Поэтому сохраняем как есть, а лишний префикс отсекаем при
            # сравнении: свой объект опознаётся по ВХОЖДЕНИЮ, не по равенству.
            c = norm_cipher(m.group(1), m.group(2))
            if len(c.split("-ИОС")[0]) < 2:
                continue
            found.append(c)
            counter[c] += 1
        if found:
            per_page[p["page"]] = sorted(set(found))
    return {"per_page": per_page, "counts": counter}


def skeleton(cipher: str) -> str:
    """Скелет шифра: только буквы и цифры, без дефисов и слэшей.

    Нужен, чтобы «МП-18/1604-ИОС1.1» и «МП-181604-ИОС1.1» считались одним
    шифром (потерянный разделитель), а не разными объектами.
    """
    return re.sub(r"[^А-ЯЁA-Z0-9]", "", cipher.upper().replace("Ё", "Е"))


def object_part(cipher: str) -> str:
    """Часть шифра ДО «-ИОС» — идентифицирует объект, а не подраздел."""
    return skeleton(cipher.split("-ИОС")[0])


def cipher_report(scan: dict, expected: str | None) -> dict:
    """Ищет страницы, где шифр относится к ДРУГОМУ объекту.

    Различать три случая:
      • чужой объект  — скелет префикса не совпадает  -> КРИТИЧНО, вклеенный лист
      • другой подраздел того же объекта (-ИОС1.2)    -> нормально, это ссылка
      • иное написание своего шифра (потерян «/»)      -> замечание по оформлению
    """
    if not scan["counts"]:
        return {"dominant": None, "aliens": [], "variants": [], "pages_with_cipher": 0}

    dominant = scan["counts"].most_common(1)[0][0]
    if expected:
        m = re.search(r"ИОС\s*([\d.,]+)", expected)
        part = m.group(1) if m else "1.1"
        base = expected.split("-ИОС")[0] if "-ИОС" in expected else expected
        dominant = norm_cipher(base, part)

    obj = object_part(dominant)

    def same_object(c: str) -> bool:
        """Свой объект: скелет совпадает ИЛИ содержит наш как хвост
        (перед шифром могло приклеиться имя щита: «ГРЩ» + наш шифр)."""
        sk = object_part(c)
        return sk == obj or sk.endswith(obj) or obj.endswith(sk)

    aliens: list[dict] = []
    for page, ciphers in sorted(scan["per_page"].items()):
        foreign = [c for c in ciphers if not same_object(c)]
        if foreign:
            aliens.append({"page": page, "ciphers": sorted(set(foreign))})

    variants = sorted({c for c in scan["counts"]
                       if object_part(c) == obj and c != dominant})

    return {
        "dominant": dominant,
        "aliens": aliens,
        "variants": variants,
        "pages_with_cipher": len(scan["per_page"]),
    }


# ─────────────────────────────────────────────────────────── 3. НТД

# Номера нормативов в PDF рвутся пробелом или переносом в любом месте:
#   «ГОСТ 3214 4-2013», «ГОСТ 28249- 93», «СНиП 23 -05-95», «СП 6.13130.202 5».
# Поэтому сначала ЛОВИМ обозначение с внутренними пробелами (склеиваем,
# относящиеся к цифрам), и только потом классифицируем. Разбор по готовому
# шаблону «цифры-дефис-цифры» отрезает хвост и даёт ложные «без года».
def flatten(text: str) -> str:
    """Плоский текст: переносы строк -> пробел (иначе номера рвутся)."""
    return re.sub(r"\s+", " ", text)


NTD_LOOSE = re.compile(
    r"(?P<html>"
    r"СП\s*\d[\d.\s\-]{0,24}"
    r"|ГОСТ(?:\s+Р)?(?:\s+(?:IEC|МЭК|ИСО|ISO))?\s*\d[\d.\s\-]{0,24}"
    r"|СНиП\s*\d[\d.\s\-]{0,20}"
    r"|СО\s*\d[\d.\s\-]{0,20}"
    r"|ТР\s*ЕАЭС\s*\d{3}\s*/\s*\d{3,4}"
    r"|№\s*\d{2,4}\s*-\s*Ф[З3]"
    r")"
)


def tidy_ntd(raw: str) -> str:
    """Склеивает обозначение, разорванное ПРОБЕЛАМИ.

    Трогаем ТОЛЬКО пробелы. Дефисы и точки — часть номера, их удалять нельзя
    (иначе «ГОСТ 10434-82» превращается в «ГОСТ 1043482» и номер теряет смысл).
      «ГОСТ 3214 4-2013»  -> «ГОСТ 32144-2013»
      «ГОСТ 28249- 93»    -> «ГОСТ 28249-93»
      «СНиП 23 -05-95»    -> «СНиП 23-05-95»
      «СО 153 -34.21.122-2003» -> «СО 153-34.21.122-2003»
    """
    s = norm_space(raw)
    # пробел после типа документа оставляем одним
    m = re.match(r"(ГОСТ(?:\s+Р)?(?:\s+(?:IEC|МЭК|ИСО|ISO))?|СНиП|СО|СП|ТР\s*ЕАЭС)(.*)$", s)
    head, tail = (m.group(1), m.group(2)) if m else ("", s)
    # в хвосте убираем ВСЕ пробелы (включая вокруг «-» и «.»), но сами знаки сохраняем
    tail = re.sub(r"\s+", "", tail)
    # точка в конце — это знак конца предложения, а не часть номера
    tail = tail.rstrip(".,;:")
    return (head + " " + tail).strip() if head else tail.strip()


# Один документ может встречаться в разных написаниях («СП 256.1325800.2016» и
# «СП256.1325800.2016»). Для отчёта считаем их одним — иначе список пухнет
# дублями и в базу уходит два задания на один документ.
def ntd_identity(key: str) -> str:
    return re.sub(r"[^А-ЯЁA-Z0-9]", "", key.upper().replace("Ё", "Е"))


def classify_ntd(key: str) -> str:
    if key.startswith("СП"):
        return "СП"
    if key.startswith("ГОСТ"):
        return "ГОСТ"
    if key.startswith("СНиП"):
        return "СНиП"
    if key.startswith("СО"):
        return "СО"
    if key.startswith("ТР"):
        return "ТР ЕАЭС"
    if "ФЗ" in key or "Ф3" in key:
        return "ФЗ"
    return "прочее"


def ntd_completeness(key: str) -> str | None:
    """Дефект обозначения, видимый механически."""
    if re.fullmatch(r"ГОСТ(?:\s+Р)?(?:\s+(?:IEC|МЭК|ИСО|ISO))?\s*\d[\d.\-]*", key):
        if not re.search(r"-\d{2,4}$", key):
            return "без года"
    if re.fullmatch(r"СНиП\s*\d[\d.\-]*", key):
        if not re.search(r"-\d{2,4}$", key):
            return "обрезан номер"
    if re.fullmatch(r"СП\s*\d+(\.\d+){1,3}", key):
        # СП без года в конце (СП 256.1325800.2016 — год есть)
        if not re.search(r"\.\d{4}$", key):
            return "без года"
    return None


def scan_ntd(pages: list[dict]) -> dict:
    """Собирает обозначения НТД; ПУЭ разбирается отдельным проходом."""
    items: dict[str, dict] = {}

    for p in pages:
        text = flatten(p["text"])

        for m in NTD_LOOSE.finditer(text):
            key = tidy_ntd(m.group("html"))
            if len(key) < 4:
                continue
            ident = ntd_identity(key)
            rec = items.setdefault(ident, {
                "kind": classify_ntd(key), "raw": key, "pages": set(), "ctx": [],
                "spellings": set()})
            rec["spellings"].add(key)
            # канонизируем: чем больше в написании пробелов, тем привычнее для чтения
            if key.count(" ") > rec["raw"].count(" "):
                rec["raw"] = key
            rec["pages"].add(p["page"])
            if len(rec["ctx"]) < 3:
                a = max(0, m.start() - 70)
                b = min(len(text), m.end() + 70)
                rec["ctx"].append(norm_space(text[a:b]))

        # ПУЭ упоминается без номера — собираем отдельно, чтобы не плодить мусор
        if re.search(r"\bПУЭ\b", text):
            rec = items.setdefault("ПУЭ", {
                "kind": "ПУЭ", "raw": "ПУЭ", "pages": set(), "ctx": [],
                "spellings": {"ПУЭ"}})
            rec["pages"].add(p["page"])
            if len(rec["ctx"]) < 3:
                mm = re.search(r"\bПУЭ[^.;]{0,80}", text)
                if mm:
                    rec["ctx"].append(norm_space(mm.group(0)))

    for v in items.values():
        v["pages"] = sorted(v["pages"])
    return items


# ─────────────────────────────────────────────────────────── 4. нумерация таблиц

def scan_tables(pages: list[dict]) -> dict:
    seen: list[tuple[int, int]] = []
    for p in pages:
        for m in re.finditer(r"Таблица\s+(\d{1,2})", p["text"]):
            seen.append((int(m.group(1)), p["page"]))

    numbers = [n for n, _ in seen]
    uniq = sorted(set(numbers))
    gaps = [n for n in range(1, max(uniq) + 1) if n not in uniq] if uniq else []
    dupes = {n: c for n, c in Counter(numbers).items() if c > 1}

    return {"all": seen, "numbers": uniq, "gaps": gaps, "dupes": dupes}


# ─────────────────────────────────────────────────────────── 5-6. таблицы нагрузок

@dataclass
class Row:
    """Одна строка таблицы нагрузок.

    ``vals`` — числа ПОСЛЕ «Ру» и «Кол-во», в порядке документа. Хвост всегда
    оканчивается одинаково: …, Рр, Qр, Sр, (Iр). Поэтому надёжнее брать С КОНЦА,
    а не по абсолютному индексу: в вёрстке B между Кснм и cosφ есть лишние
    колонки, и фиксированный индекс уезжает.
    """
    table: str
    n: int
    name: str
    qty: Decimal | None
    ru: Decimal | None
    vals: list[Decimal] = field(default_factory=list)
    status: str = "calc"
    raw: str = ""
    has_current: bool = False       # есть ли колонка Iр в конце

    def _tail(self, back: int) -> Decimal | None:
        """Рр/Qр/Sр считаем С КОНЦА строки — там колонки всегда стоят подряд.

        Хвост строки: …, Рр, Qр, Sр, [Iр].
          back=3 -> Рр, back=2 -> Qр, back=1 -> Sр   (когда Iр есть)
          back=2 -> Рр, back=1 -> Qр, back=0 -> Sр   (когда Iр нет)
        Считать по абсолютному индексу нельзя: в вёрстке B между «Кснм» и
        «cosφ» появляется лишняя колонка, и все индексы уезжают на единицу.
        """
        if not self.vals:
            return None
        idx = len(self.vals) - back
        return self.vals[idx] if 0 <= idx < len(self.vals) else None

    @property
    def participates(self) -> bool:
        """Строка учтена в итоге.

        В вёрстке B явных пометок «Не участ.» нет — строка участвует, если у неё
        заполнены Рр/Qр/Sр. Нулевую строку (зарядные с Кс=0) тоже считаем
        участвующей: она входит в итог нулём, и исключение искажает сумму.
        """
        # В вёрстке B пожарная таблица — отдельный блок со своим итогом,
        # поэтому её строки УЧАСТВУЮТ в сумме своей таблицы (ключ содержит «пожар»).
        if self.status == "excluded" or self.status == "other_season":
            return False
        return len(self.vals) >= 5

    @property
    def rr(self) -> Decimal | None:
        return self._tail(4 if self.has_current else 3)      # Рр

    @property
    def qr(self) -> Decimal | None:
        return self._tail(3 if self.has_current else 2)      # Qр

    @property
    def sr(self) -> Decimal | None:
        return self._tail(2 if self.has_current else 1)      # Sр



# ── Два стандарта вёрстки таблиц нагрузок ────────────────────────────────────
# Стандарт A (МП-18/1604): колонки «№ | Наименование | Кол-во | Ру | Кс | ...»,
#   таблица одна на режим, итоги «Итого» / «Итого ВРУ с КРМ».
# Стандарт B (ШРКП): колонки «№ | Нагрузка | Ру | Кол-во | ...», строки разбиты
#   на ВВОДА, итоги «Итого по вводу N» / «Итого по вводу N с КРМ», плюс отдельный
#   блок «(Пожар. реж)» на каждый ввод.
#
# Определяем порядок колонок по заголовку таблицы, а не угадываем.

LAYOUT_A = "qty_ru"      # сначала Кол-во, потом Ру
LAYOUT_B = "ru_qty"      # сначала Ру, потом Кол-во


def detect_layout(text: str) -> str:
    """По заголовку колонок определяет, что идёт первым — Ру или Кол-во."""
    for line in text.splitlines():
        flat = re.sub(r"\s+", " ", line)
        if "Нагрузка" in flat and ("Ру" in flat or "Ру," in flat) and "Кол" in flat:
            i_ru = flat.find("Ру")
            i_kol = flat.find("Кол")
            return LAYOUT_B if i_ru < i_kol else LAYOUT_A
    return LAYOUT_A       # по умолчанию — как в МП-18/1604


MODE_HEAD_RE = re.compile(r"Расчет нагрузок в режиме\s+(\w+)", re.I)
# «ВВОД 1», «ВВО Д 1», «ВВОД1» — пробел рвёт и само слово
INPUT_HEAD_RE = re.compile(r"^В\s*В\s*О\s*Д?\s*(\d)\s*:?\s*$", re.I)
FIRE_MARK_RE = re.compile(r"\(Пожар\.?\s*реж", re.I)
RE_INPUT_TOTAL = re.compile(r"Итого по вводу\s*\d", re.I)
INPUT_TOTAL_KRМ = re.compile(r"Итого по вводу\s*(\d)\s*с КРМ", re.I)
KRM_RE = re.compile(r"Компенсация РМ", re.I)

def is_load_table_head(line: str) -> bool:
    """Заголовок сезонной таблицы нагрузок.

    В PDF заголовок часто РВЁТСЯ на две строки: «Таблица 2 Итоговый расчет …
    Режим» + ««Зима»». Поэтому ищем по признаку «расчёт/расчет», а сезон берём
    из этой же строки ИЛИ из regex по слову Зима/Лето.
    """
    low = line.lower()
    if "таблица" not in low:
        return False
    return "расчет" in low or "расчёт" in low


def head_season(line: str) -> str:
    low = line.lower()
    if "лето" in low:
        return "лето"
    if "зима" in low:
        return "зима"
    return "?"


def detect_status(line: str) -> str:
    low = line.lower()
    if "пожар" in low:
        return "fire"
    if "не участ" in low or "не учит" in low:
        return "excluded"
    if "зима" in low or "лето" in low:
        return "other_season"
    return "calc"


def parse_load_tables(pages: list[dict]) -> tuple[list[Row], dict[str, dict]]:
    """Разбор таблиц нагрузок в ДВУХ вёрстках (см. LAYOUT_A / LAYOUT_B).

    Ключ таблицы: «<режим>|<ввод>|<пожар>», например «лето|1|норма».
    """
    rows: list[Row] = []
    totals: dict[str, dict] = {}
    all_text = "\n".join(p["text"] for p in pages[:40])
    layout = detect_layout(all_text)

    # Есть ли колонка Iр — смотреть ТОЛЬКО в строке-шапке таблицы нагрузок.
    # Поиск по всему тому даёт ложные срабатывания (Iр встречается в тексте
    # и в других таблицах) и сдвигает Рр/Qр/Sр.
    has_current = False
    for line in all_text.splitlines():
        flat = re.sub(r"\s+", " ", line)
        if "Нагрузка" in flat and ("Ру" in flat) and "Кол" in flat:
            has_current = bool(re.search(r"Iр|Iр,|Ip", flat))
            break

    current: str | None = None      # ключ таблицы
    pending_season = False
    pending_input: str | None = None
    in_fire = False
    mode: str | None = None

    def make_key(season: str, inp: str, fire: bool) -> str:
        return f"{season}|{inp}|{'пожар' if fire else 'норма'}"

    for p in pages:
        for raw_line in p["text"].splitlines():
            line = norm_space(raw_line)
            if not line:
                continue

            # сезон уехал на следующую строку после заголовка
            if pending_season:
                seas = head_season(line)
                if seas != "?":
                    mode = seas
                    current = make_key(seas, pending_input or "—", in_fire)
                    totals.setdefault(current, {})
                    pending_season = False
                    continue

            m_mode = MODE_HEAD_RE.search(line)
            if m_mode:
                mode = m_mode.group(1).lower()
                in_fire = False
                pending_input = None
                current = make_key(mode, pending_input or "—", False)
                totals.setdefault(current, {})
                continue

            if is_load_table_head(line):
                if head_season(line) != "?":
                    mode = head_season(line)
                    current = make_key(mode, pending_input or "—", False)
                    totals.setdefault(current, {})
                else:
                    pending_season = True
                continue

            # блок «(Пожар. реж)» — свой набор строк на том же вводе
            if FIRE_MARK_RE.search(line):
                in_fire = True
                if mode and pending_input:
                    current = make_key(mode, pending_input, True)
                    totals.setdefault(current, {})
                continue

            m_inp = INPUT_HEAD_RE.match(line)
            if m_inp:
                pending_input = m_inp.group(1)
                in_fire = False
                if mode:
                    current = make_key(mode, pending_input, False)
                    totals.setdefault(current, {})
                continue

            # «- Итого по вводу 1: ...» и «... с КРМ»
            if RE_INPUT_TOTAL.search(line) or KRM_RE.search(line):
                if current:
                    # «Итого по вводу 1: 0,93 0,39 446,9 174,2 479,6 728,7»
                    #   = [№ввода] cosφ tgφ Рр Qр Sр Iр
                    # Отбрасываем номер ввода; далее ТРИ подряд: Рр, Qр, Sр.
                    # Брать хвост нельзя — Iр сдвигает всё на один.
                    tail = line.split(":", 1)[1] if ":" in line else line
                    nums = [Decimal(x.replace(",", ".")) for x in re.findall(NUM, tail)]
                    slot = "vru" if "КРМ" in line else "itogo"
                    if len(nums) >= 5:
                        totals[current][slot] = {
                            "rr": nums[2], "qr": nums[3], "sr": nums[4],
                            "page": p["page"],
                        }
                continue

            # сводка по авар. режиму — не итог одного ввода
            if re.match(r"^Итого по авар", line, re.I):
                continue

            # старая вёрстка: «Итого ...» / «Итого ВРУ c КРМ»
            m_vru = re.search(r"Итого\s+ВРУ[^\n]*", line, re.I)
            if m_vru and current:
                nums = [Decimal(x.replace(",", ".")) for x in re.findall(NUM, m_vru.group(0))]
                if len(nums) >= 5:
                    totals[current]["vru"] = {
                        "ru": nums[0], "rr": nums[-3], "qr": nums[-2], "sr": nums[-1],
                        "page": p["page"]}
                continue
            m_itog = re.match(r"^Итого\s+(.+)$", line)
            if m_itog and current:
                nums = [Decimal(x.replace(",", ".")) for x in re.findall(NUM, m_itog.group(1))]
                if len(nums) >= 3:
                    totals[current]["itogo"] = {
                        "ru": nums[0], "rr": nums[-3], "qr": nums[-2], "sr": nums[-1],
                        "page": p["page"]}
                continue

            # «ИТ О ГО :» / «ИТОГО:» — это промежуточный итог внутри таблицы
            # (например по квартирам), а не строка нагрузки. Иначе он попадает
            # в разбор как нагрузка с Ру=2219 кВт и ломает сверку.
            if re.match(r"^И\s*Т\s*О\s*Г\s*О", line, re.I):
                if current:
                    tail = line.split(":", 1)[1] if ":" in line else line
                    nums = [Decimal(x.replace(",", ".")) for x in re.findall(NUM, tail)]
                    if len(nums) >= 6:
                        # «ИТ О ГО : 2219 180 0,144 0,144 1 0,95 0,329 319,5 105 336,4 509,6»
                        # [Ру, Кол-во, ... , Рр, Qр, Sр, Iр] — берём хвост
                        sub = totals[current].setdefault("subtotals", [])
                        sub.append({
                            "ru": nums[0], "rr": nums[-4], "qr": nums[-3],
                            "sr": nums[-2], "page": p["page"]})
                continue

            # вложенные строки подвидов («1-комнатные 73 11») — не отдельные нагрузки
            if re.match(r"^\d+-\s*комнатн", line, re.I):
                continue

            m_row = re.match(rf"^(\d{{1,2}})\s+(\S.*)$", line)
            if not m_row or current is None:
                continue
            if "Изм." in line or "Кол.уч" in line:
                continue

            n = int(m_row.group(1))
            rest = m_row.group(2)
            name = re.split(rf"\s{NUM}\s", " " + rest, maxsplit=1)[0].strip()

            cleaned = re.sub(r"\d+\s*кВт", "", rest)
            nums = [Decimal(x.replace(",", ".")) for x in re.findall(NUM, cleaned)]
            if len(nums) < 2:
                continue

            if layout == LAYOUT_B:
                ru, qty = nums[0], nums[1]        # Ру, Кол-во
            else:
                qty, ru = nums[0], nums[1]        # Кол-во, Ру
            if not (Decimal(0) < ru < Decimal(20000)):
                continue

            if layout == LAYOUT_B:
                # статус задаётся блоком (норма / «(Пожар. реж)»), а НЕ словом
                # в названии: «Лифт пожарных подразделений» — это нагрузка
                # нормального режима, хотя слово «пожар» в нём есть.
                status = "fire" if in_fire else "calc"
            else:
                status = detect_status(rest)

            row = Row(table=current, n=n, name=name[:60], qty=qty, ru=ru,
                      vals=nums[2:], status=status, raw=line[:200],
                      has_current=has_current)
            rows.append(row)

    return rows, totals


def rows_by_table(rows: list[Row]) -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        out[r.table].append(r)
    return dict(out)


def season_pair(tables: dict[str, list[Row]]) -> tuple[str, str] | None:
    summer = [t for t in tables if "лето" in t.lower()]
    winter = [t for t in tables if "зима" in t.lower()]
    if summer and winter:
        return summer[0], winter[0]
    return None


def dropped_rows(tables: dict[str, list[Row]]) -> tuple[list[dict], list[dict]]:
    """Строки, выпавшие из баланса. Возвращает (настоящие потери, пожарный резерв).

    Различать два случая, иначе вывод будет ложным:
      • «пожар» в ОБОИХ режимах — это НОРМА. Нагрузки СПЗ (клапаны ДУ,
        противодымная вентиляция) считаются отдельным пожарным режимом и в
        нормальном балансе не участвуют. В замечания не идёт.
      • «свой сезон» в одной таблице и «пожар»/«исключено» в другой — нагрузка
        не учтена НИГДЕ. Это и есть выпавшая нагрузка.
    """
    pair = season_pair(tables)
    if not pair:
        return [], []
    a, b = pair
    by_a = {r.n: r for r in tables[a]}
    by_b = {r.n: r for r in tables[b]}

    lost: list[dict] = []
    fire_ok: list[dict] = []
    for n in sorted(set(by_a) | set(by_b)):
        ra, rb = by_a.get(n), by_b.get(n)
        if not ra or not rb:
            continue
        if ra.participates or rb.participates:
            continue

        item = {
            "n": n,
            "name": (ra.name or rb.name),
            "ru": ra.ru if ra.ru is not None else rb.ru,
            "status_a": ra.status, "status_b": rb.status,
            "table_a": a, "table_b": b,
        }
        if ra.status == "fire" and rb.status == "fire":
            fire_ok.append(item)
        else:
            lost.append(item)
    return lost, fire_ok


def arithmetic(tables: dict[str, list[Row]], totals: dict[str, dict]) -> list[dict]:
    findings = []
    for tag, rows in tables.items():
        if not rows:
            continue
        act = [r for r in rows if r.participates]
        sum_ru_all = sum((r.ru for r in rows if r.ru is not None), Decimal(0))
        sum_ru_act = sum((r.ru for r in act if r.ru is not None), Decimal(0))
        sum_rr = sum((r.rr for r in act if r.rr is not None), Decimal(0))
        sum_qr = sum((r.qr for r in act if r.qr is not None), Decimal(0))
        sum_sr = sum((r.sr for r in act if r.sr is not None), Decimal(0))

        t = totals.get(tag, {})
        itogo = t.get("itogo")
        vru = t.get("vru")

        findings.append({
            "table": tag,
            "rows": len(rows),
            "participating": len(act),
            "sum_ru_all": sum_ru_all,
            "sum_ru_act": sum_ru_act,
            "sum_rr": sum_rr,
            "sum_qr": sum_qr,
            "sum_sr": sum_sr,
            "doc_itogo": itogo,
            "doc_vru": vru,
        })
    return findings


def sqrt_checks(totals: dict[str, dict]) -> list[dict]:
    out = []
    for tag, t in totals.items():
        v = t.get("vru")
        if not v:
            continue
        p, q, s = float(v["rr"]), float(v["qr"]), float(v["sr"])
        calc = math.sqrt(p * p + q * q)
        diff = abs(calc - s)
        cos = p / s if s else None
        tg = q / p if p else None
        out.append({
            "table": tag, "p": p, "q": q, "s_doc": s, "s_calc": round(calc, 2),
            "diff": round(diff, 2), "ok": diff < 0.6,
            "cos": round(cos, 4) if cos else None,
            "tg": round(tg, 4) if tg else None,
        })
    return out


# ─────────────────────────────────────────────────────────── отчёт

def fmt(d) -> str:
    if d is None:
        return "—"
    if isinstance(d, Decimal):
        s = f"{d:.2f}".rstrip("0").rstrip(".")
        return s.replace(".", ",")
    return str(d)


def build_report(pdf: Path, vmap: dict, ciph: dict, ntd: dict, tabs: dict,
                 rows: list[Row], totals: dict, tables: dict[str, list[Row]],
                 dropped: list[dict], fire_ok: list[dict],
                 arith: list[dict], sqrts: list[dict], outdir: Path) -> str:
    L: list[str] = []
    A = L.append

    A(f"# Механическая проверка тома: {pdf.name}\n")
    A("Выполнено кодом (без модели). Статусы НТД и графика — НЕ проверялись.\n")

    A("## 1. Карта тома\n")
    A(f"- Страниц: **{vmap['pages']}**, извлечено символов: **{vmap['chars']}**")
    if vmap["no_text_layer"]:
        A("- ⚠ **текстового слоя нет больше чем на половине страниц — нужен OCR, дальше проверка невозможна**")
    if vmap["empty"]:
        A(f"- страниц без текста ({len(vmap['empty'])}): {', '.join(map(str, vmap['empty'][:30]))}")
    if vmap["thin"]:
        A(f"- страниц с разреженным текстом ({len(vmap['thin'])}): {', '.join(map(str, vmap['thin'][:30]))}")
    if vmap["graphic_from"]:
        A(f"- предположительно графика начинается со стр. **{vmap['graphic_from']}** "
          f"(дальше текстовый слой разрежен — схемы, а не текст)")
    A("")

    A("## 2. Шифры основных надписей\n")
    if ciph["dominant"]:
        n_pages = ciph.get("pages_with_cipher") or 0
        A(f"Доминирующий шифр: **{ciph['dominant']}** (найден на {n_pages} стр.)\n")
    if ciph["aliens"]:
        A("### ⚠ Страницы с ЧУЖИМ шифром — вклеенные листы другого объекта\n")
        A("| стр. | шифр на листе |")
        A("|---|---|")
        for a in ciph["aliens"]:
            A(f"| {a['page']} | {', '.join(a['ciphers'])} |")
        A("")
        A("Проверить визуально: совпадает ли объект, адрес и ГИП в штампе.\n")
    else:
        A("Чужих шифров не найдено.\n")
    if ciph["variants"]:
        A(f"Варианты написания своего шифра (нормализуются в один): {', '.join(ciph['variants'])}\n")
    glued = [v for v in ciph["variants"] if not any(ch.isdigit() for ch in v.split("-ИОС")[0][-4:]) is False]
    prefixed = [v for v in ciph["variants"]
                if len(object_part(v)) > len(object_part(ciph["dominant"] or ""))]
    if prefixed:
        A(f"**К шифру приклеено имя щита** ({len(prefixed)} вариантов) — в плотных штампах А3 "
          f"обозначение идёт вплотную к названию панели, например `{prefixed[0]}`. "
          f"Это не чужой объект, но для ГЧ стоит проверить, что шифр в штампе читается однозначно.\n")

    A("## 3. Нумерация таблиц\n")
    if tabs["numbers"]:
        A(f"Найденные номера: {tabs['numbers']}")
        if tabs["gaps"]:
            A(f"- ⚠ **пропущены номера: {tabs['gaps']}** — проверить, не выпал ли раздел")
        if tabs["dupes"]:
            det = ", ".join(f"№{n} — {c} раза" for n, c in sorted(tabs["dupes"].items()))
            A(f"- ⚠ **номера повторяются: {det}** — ссылки вида «в таблицах N и M» станут неоднозначными")
    else:
        A("Таблиц не найдено.")
    A("")

    A("## 4. Таблицы нагрузок: арифметика\n")
    if arith:
        A("| таблица | строк | участвуют | ΣРу всех | ΣРу участн. | ΣРр | ΣQр | ΣSр |")
        A("|---|---|---|---|---|---|---|---|")
        for a in arith:
            A(f"| {a['table']} | {a['rows']} | {a['participating']} | {fmt(a['sum_ru_all'])} | "
              f"{fmt(a['sum_ru_act'])} | {fmt(a['sum_rr'])} | {fmt(a['sum_qr'])} | {fmt(a['sum_sr'])} |")
        A("")
        A("**Сверка с «Итого» в документе:**\n")
        for a in arith:
            it, vr = a["doc_itogo"], a["doc_vru"]
            if it:
                A(f"- {a['table']} «Итого»: Ру={fmt(it.get('ru'))} Рр={fmt(it['rr'])} "
                  f"Qр={fmt(it['qr'])} Sр={fmt(it['sr'])}  (стр. {it['page']})")
            if vr:
                A(f"- {a['table']} «Итого с КРМ»: Ру={fmt(vr.get('ru'))} Рр={fmt(vr['rr'])} "
                  f"Qр={fmt(vr['qr'])} Sр={fmt(vr['sr'])}  (стр. {vr['page']})")
        A("")
        A("### Разбор расхождений: сумма строк против «Итого»\n")
        A("Сумма строк в таблице почти никогда не равна итогу: в итог входят строки,")
        A("вынесенные отдельным подытогом (квартиры), и не входят исключённые. Ниже —")
        A("разложение остатка, чтобы было видно, объясним он или это ошибка.\n")
        for a in arith:
            tag = a["table"]
            it = a["doc_itogo"] or a["doc_vru"]
            if not it:
                continue
            delta = a["sum_rr"] - it["rr"]
            subs = totals.get(tag, {}).get("subtotals") or []
            sub_sum = sum((s["rr"] for s in subs), Decimal(0))

            # Квартиры обычно выносятся отдельной строкой и в «Итого» не входят.
            # Их Рр вычитаем отдельно, иначе разница выглядит ошибкой.
            apt = [r for r in tables.get(tag, [])
                   if re.search(r"квартир", r.name, re.I) and r.rr]
            apt_sum = sum((r.rr for r in apt), Decimal(0))

            # Подытог («ИТ О ГО») добавляет вынесенное в сумму -> знак «+».
            # Квартиры в вёрстке A сидят ОТДЕЛЬНОЙ строкой и уже входят в Σ,
            # а в итог нет -> их надо вычесть, знак «-».
            # Коррекцию применяем ТОЛЬКО если она реально объясняет разницу:
            # иначе «квартиры» из другой части таблицы дают ложный остаток.
            if subs and abs(delta + sub_sum) < abs(delta):
                rest = delta + sub_sum
                used = "подытог"
            elif apt_sum and abs(delta - apt_sum) < abs(delta) - 1:
                rest = delta - apt_sum
                used = "квартиры"
            else:
                rest = delta
                used = None
            line = f"- **{tag}**: Σ строк = {fmt(a['sum_rr'])}; итог = {fmt(it['rr'])}; разница = {fmt(delta)}"
            if used == "подытог":
                line += f"; подытоги = {fmt(sub_sum)}"
            if used == "квартиры":
                line += f"; квартиры (отдельной строкой) = {fmt(apt_sum)}"
            if used:
                line += f"; остаток = **{fmt(rest)}**"
                if abs(rest) < 2:
                    line += " — сходится"
            A(line)
        A("")
        A("> Остаток, близкий к нулю, — баланс верный. Остаток в десятки кВт — либо")
        A("> пропущенная строка, либо расхождение в коэффициентах: смотреть построчно.")
        A("> В вёрстке с вводами («Итого по вводу N») итог считается по вводу целиком,\n"
          "> поэтому сверять нужно суммы строк, накопленные ДО строки итога.\n")
    else:
        A("Таблицы нагрузок не распознаны (проверить формат извлечения).")
    A("")

    A("## 5. Строки, выпавшие из ОБОИХ сезонных режимов\n")
    if dropped:
        A("| № | нагрузка | Ру, кВт | статус в одной таблице | статус в другой |")
        A("|---|---|---|---|---|")
        for d in dropped:
            A(f"| {d['n']} | {d['name'][:45]} | {fmt(d['ru'])} | {d['status_a']} | {d['status_b']} |")
        A("")
        total = sum((d["ru"] for d in dropped if d["ru"] is not None), Decimal(0))
        A(f"Суммарная Ру выпавших строк: **{fmt(total)} кВт**.")
        A("")
        A("Это критическая проверка: строка, помеченная «зима» в летней таблице и «пожар» "
          "в зимней, не учтена НИГДЕ. Сравнить с запасом до разрешённой мощности по ТУ.\n")
    else:
        A("Выпавших строк не найдено (или таблицы не распознаны).\n")

    if fire_ok:
        A("### Пожарный режим — это не потеря\n")
        A("Эти строки исключены в обоих режимах как «Режим Пожар». Для нагрузок СПЗ "
          "это **норма**: они считаются отдельным пожарным режимом.\n")
        A("| № | нагрузка | Ру, кВт |")
        A("|---|---|---|")
        for d in fire_ok:
            A(f"| {d['n']} | {d['name'][:45]} | {fmt(d['ru'])} |")
        A("")

    A("## 6. Внутренние проверки (Sр, cos φ, tg φ)\n")
    if sqrts:
        A("| таблица | Рр | Qр | Sр док. | Sр расч. | Δ | статус | cos φ | tg φ |")
        A("|---|---|---|---|---|---|---|---|---|")
        for s in sqrts:
            A(f"| {s['table']} | {s['p']} | {s['q']} | {s['s_doc']} | {s['s_calc']} | "
              f"{s['diff']} | {'OK' if s['ok'] else 'РАСХОЖДЕНИЕ'} | {s['cos']} | {s['tg']} |")
        A("")
        A("> tg φ сравнивать с требованием ТУ (обычно не выше 0,36) и cos φ с 0,94.")
    else:
        A("Итогов ВРУ с КРМ не найдено.")
    A("")

    A("## 7. Что НЕ проверено этим прогоном\n")
    A("- **Статусы и замены НТД** — требуют базы (ГОСТ Ассистент / Техэксперт), см. `ntd_task.md`")
    A("- **Графическая часть** — однолинейки, спецификации, селективность защит")
    A("- **Привязка номеров пунктов к тексту норм** — только чтение первоисточника по номеру строки")
    A("- **Полнота текстовой части** по п.87 ПП РФ №87 — смысловая проверка, не механическая")
    A("")

    return "\n".join(L)


def build_ntd_task(ntd: dict) -> str:
    L: list[str] = []
    A = L.append
    A("# Задание для проверки НТД\n")
    A("Проверять ТОЛЬКО по базе (ГОСТ Ассистент / Техэксперт / Кодекс). "
      "Модель статусы не знает и выдумывает.\n")
    A("Для каждой позиции: найти документ → взять статус и дату → если статус "
      "«не действующий»/«прекращено», найти замену → для ссылок в тексте дополнительно "
      "прочитать текст указанного пункта и убедиться, что он О ТОМ.\n")
    A(f"Всего уникальных обозначений: **{len(ntd)}**\n")
    A("| обозначение | тип | страницы | дефект обозначения |")
    A("|---|---|---|---|")
    for key, rec in sorted(ntd.items(), key=lambda kv: (kv[1]["kind"], kv[1]["raw"])):
        name = rec["raw"]
        pages = ", ".join(map(str, rec["pages"][:12]))
        if len(rec["pages"]) > 12:
            pages += f" … +{len(rec['pages']) - 12}"
        defect = ntd_completeness(name) or ""
        A(f"| {name} | {rec['kind']} | {pages} | {defect} |")

    flagged = [(rec["raw"], ntd_completeness(rec["raw"]))
               for rec in ntd.values() if ntd_completeness(rec["raw"])]
    if flagged:
        A("")
        A(f"**Механически найденные дефекты обозначений: {len(flagged)}**\n")
        A("| обозначение | дефект |")
        A("|---|---|")
        for k, d in sorted(flagged):
            A(f"| {k} | {d} |")
    A("")
    A("## Контекст употребления\n")
    for key, rec in sorted(ntd.items(), key=lambda kv: kv[1]["kind"]):
        A(f"### {rec['raw']}")
        for c in rec["ctx"][:2]:
            A(f"> …{c}…")
        A("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Механическая проверка тома ЭОМ/ИОС1.1")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument("--cipher", default=None, help="ожидаемый шифр комплекта, напр. МП-18/1604-ИОС1.1")
    args = ap.parse_args()

    if not args.pdf.is_file():
        sys.exit(f"файл не найден: {args.pdf}")

    outdir = args.out or args.pdf.with_name(args.pdf.stem + "_check")
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"[1/6] извлечение: {args.pdf.name}")
    pages = extract_pages(args.pdf)
    (outdir / "pages.json").write_text(
        json.dumps(pages, ensure_ascii=False), encoding="utf-8")

    print("[2/6] карта тома")
    vmap = volume_map(pages)

    print("[3/6] шифры штампов")
    ciph = cipher_report(scan_ciphers(pages), args.cipher)

    print("[4/6] обозначения НТД")
    ntd = scan_ntd(pages)

    print("[5/6] нумерация таблиц и разбор нагрузок")
    tabs = scan_tables(pages)
    rows, totals = parse_load_tables(pages)
    tables = rows_by_table(rows)
    dropped, fire_ok = dropped_rows(tables)
    arith = arithmetic(tables, totals)
    sqrts = sqrt_checks(totals)

    print("[6/6] отчёты")
    report = build_report(args.pdf, vmap, ciph, ntd, tabs, rows, totals, tables,
                          dropped, fire_ok, arith, sqrts, outdir)
    (outdir / "report.md").write_text(report, encoding="utf-8", newline="\n")
    (outdir / "ntd_task.md").write_text(build_ntd_task(ntd), encoding="utf-8", newline="\n")

    with (outdir / "rows.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["таблица", "строка", "наименование", "кол", "Ру", "Рр", "Qр", "Sр", "статус", "участвует"])
        for r in rows:
            w.writerow([r.table, r.n, r.name, fmt(r.qty), fmt(r.ru), fmt(r.rr),
                        fmt(r.qr), fmt(r.sr), r.status, "да" if r.participates else "нет"])

    print()
    print(f"готово -> {outdir}")
    print(f"  report.md    отчёт механической проверки")
    print(f"  ntd_task.md  задание для базы НТД ({len(ntd)} обозначений)")
    print(f"  rows.csv     {len(rows)} строк таблиц нагрузок")
    print()
    print(f"  страниц {vmap['pages']} | чужих шифров: {len(ciph['aliens'])} | "
          f"пропуски таблиц: {tabs['gaps'] or 'нет'} | выпавших строк: {len(dropped)} | "
          f"пожарный резерв: {len(fire_ok)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
