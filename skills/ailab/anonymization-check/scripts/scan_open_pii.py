#!/usr/bin/env python3
"""Проверка полноты обезличивания: что закрыто токенами, а что осталось открытым.

Смысл: обезличивание делают люди, и оно бывает неполным — закрывают то, о чём
подумали. Скрипт ничего не закрывает, он ПОКАЗЫВАЕТ, что осталось открытым,
чтобы это увидел человек до отправки документа во внешнюю модель.

Использование:
    python scan_open_pii.py "<файл.docx>"              полный отчёт
    python scan_open_pii.py "<файл.docx>" --summary    только счётчики, без значений
    python scan_open_pii.py "<файл.docx>" --header     строка для шапки отчёта
    python scan_open_pii.py "<файл.docx>" --json       машинный вывод

Поддерживается .docx (весь пакет: текст, таблицы, колонтитулы, метаданные) и .txt.

--- Два правила, заложенные в код ---

1. Разбираются И абзацы, И таблицы. В ТЗ содержимое лежит в ячейках таблиц, а не
   в абзацах; проверка только по абзацам даёт пустой результат и читается как
   «всё чисто».

2. Регистр сворачивается питоном (`lower()`), а не средствами ОС: `grep -i` в
   Windows-окружении не сворачивает кириллицу, и счётчик молча выходит нулевым.

--- Чего скрипт НЕ делает ---

Ноль находок означает «шаблоны не сработали», а НЕ «документ чист». Заказчик,
названный описательно («Инвестор проекта в районе станции»), под шаблон не
попадёт. Поэтому код возврата 0 при пустом результате — это «проверка прошла»,
а не «утечек нет». Ненулевой код (1) отдаётся только по флагу --fail-on-open.
"""
import argparse
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# ---------------------------------------------------------------- шаблоны
# Пары (категория, регулярное выражение). Регистр НЕ указываем: текст заранее
# приводится к нижнему — так надёжнее, чем флаги в самом шаблоне.
PATTERNS = [
    # Название в кавычках захватывается вместе с формой: без него в отчёте стоит
    # голое «ООО», и человек не может отличить заказчика от «АО «Мосводоканал»»,
    # которое в любом ТЗ Москвы и объект не идентифицирует.
    ("орг. форма", r"\b(ооо|оао|зао|пао|ао|ип|гбу|гку|фгбу|фгбоу|фгуп|муп|гуп|нко|сро|тсж|ано)\b"
                   r"\s*(?:«[^»\n]{1,120}»|\"[^\"\n]{1,120}\")?"),
    ("инициалы", r"\b[а-яё]\.\s?[а-яё]\.\s?[а-яё][а-яё-]{2,}"),
    ("фамилия с инициалами", r"\b[а-яё][а-яё-]{2,}\s[а-яё]\.\s?[а-яё]\."),
    ("кадастровый номер", r"\b\d{2}:\d{2}:\d{6,7}:\d+"),
    ("ГПЗУ", r"\bгпзу\b[^\n]{0,60}"),
    # \d{1,4} и полный номер телефона: с одиночной \d находка обрывалась до
    # «д. 1» и «+7 (4» — в отчёте это бесполезно.
    ("адрес", r"\b(?:г\.|гор\.|город|ул\.|улица|пер\.|переулок|проезд|шоссе|проспект|д\.|дом|корп\.|корпус|стр\.|строение|владение|помещение)\s*\.?\s*\d{1,4}"),
    # Границы по [\w-] обязательны: без них индекс «123456» находился внутри
    # номера ГПЗУ «RU77-123456» — это ложная находка.
    ("почтовый индекс", r"(?<![\w-])\d{6}(?![\w-])"),
    ("телефон", r"\+7[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}"
                r"|\b8[\s(-]*\(?\d{3}\)?[\s-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}"),
    ("электронная почта", r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    ("реквизиты", r"\b(инн|огрн|кпп|снилс|бик)\b\s*:?\s*\d+"),
    ("счёт", r"\bр/?с\b\s*:?\s*\d{20}|\b\d{20}\b"),
]

# Токены обезличивания: [АДРЕС-003], [ЗАКАЗЧИК-1], [ОБЪЕКТ-012] и подобные.
TOKEN_RE = re.compile(r"\[([а-яёa-z][а-яёa-z0-9 _-]*?)-(\d{1,4})\]")

# Второй способ замены — подчёркивания. Он наш: структура таблиц и формуляров
# не едет, значения просто исчезают. Проверять только токены нельзя: на нашей
# обезличенной копии EIR токенов 0, а подчёркиваний 39 — и проверка объявила бы
# чистый документ оригиналом.
UNDERSCORE_RE = re.compile(r"_{3,}")

# Категории, которые скрипт НЕ считает утечкой по своей природе — их наличие
# нормально, но человек должен про них знать (ресурсоснабжающие организации
# есть в любом ТЗ Москвы и объект не идентифицируют).
BENIGN_HINT = ("мосгоргеотрест", "мосводоканал", "мосэнергосбыт", "мэш",
               "мосгаз", "ростелеком", "почта россии")


def read_docx(path: Path):
    """Текст .docx по частям: возвращает список (часть, вид, номер, текст).

    Абзацы и ячейки таблиц разделяются честно: у стандартного ElementTree нет
    родительских ссылок, поэтому карта предков строится один раз. Без этого
    ячейка таблицы помечалась бы как обычный абзац — а в ТЗ содержимое лежит
    именно в таблицах, и по виду записи это должно быть видно.
    """
    blocks = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        wanted = [n for n in names
                  if n in ("word/document.xml", "docProps/core.xml", "docProps/app.xml")
                  or re.fullmatch(r"word/(header|footer)\d*\.xml", n)]
        for name in wanted:
            try:
                root = ET.fromstring(z.read(name))
            except ET.ParseError:
                continue
            if name.startswith("docProps"):
                for el in root.iter():
                    tag = el.tag.split("}")[-1]
                    if tag in ("creator", "lastModifiedBy", "Manager", "Company") and (el.text or "").strip():
                        blocks.append((name, "метаданные", tag, el.text.strip()))
                continue
            parent = {c: p for p in root.iter() for c in p}
            for i, par in enumerate(root.iter(f"{W}p")):
                text = "".join(t.text or "" for t in par.iter(f"{W}t"))
                if not text.strip():
                    continue
                node, in_table = par, False
                while node in parent:
                    node = parent[node]
                    if node.tag == f"{W}tc":
                        in_table = True
                        break
                blocks.append((name, "ячейка таблицы" if in_table else "абзац", i, text))
    return blocks


def read_txt(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    return [(path.name, "строка", i, line) for i, line in enumerate(text.splitlines(), 1) if line.strip()]


def scan(blocks):
    """Возвращает (закрыто, открыто).

    «Закрыто» — это ДВА законных способа замены, и считаются оба: скобочные
    токены [АДРЕС-003] (по ним видно, что за значение) и подчёркивания ______
    (наш способ — структура формуляров не едет).
    """
    closed = Counter()
    open_hits = defaultdict(list)          # категория -> [(где, что, контекст)]
    for part, kind, num, text in blocks:
        low = text.lower()
        for m in TOKEN_RE.finditer(low):
            closed[f"токен {m.group(1).strip().upper()}"] += 1
        n_under = len(UNDERSCORE_RE.findall(text))
        if n_under:
            closed["подчёркивания"] += n_under
        for category, pattern in PATTERNS:
            for m in re.finditer(pattern, low):
                found = text[m.start():m.end()].strip()
                ctx = text[max(0, m.start() - 40):m.end() + 40].strip()
                open_hits[category].append((f"{kind} {part}:{num}", found, ctx))
    return closed, open_hits


def is_benign(found: str) -> bool:
    return any(h in found.lower() for h in BENIGN_HINT)


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверка полноты обезличивания документа")
    ap.add_argument("file", help=".docx или .txt — обезличенная копия")
    ap.add_argument("--summary", action="store_true", help="только счётчики, без значений")
    ap.add_argument("--header", action="store_true", help="строка для шапки отчёта")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    ap.add_argument("--fail-on-open", action="store_true", help="код 1, если есть открытые находки")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"файл не найден: {path}", file=sys.stderr)
        return 2

    if path.suffix.lower() == ".docx":
        blocks = read_docx(path)
    elif path.suffix.lower() in (".txt", ".md"):
        blocks = read_txt(path)
    else:
        print(f"формат не поддержан: {path.suffix} (нужен .docx или .txt)", file=sys.stderr)
        return 2

    closed, open_hits = scan(blocks)
    total_closed = sum(closed.values())
    total_open = sum(len(v) for v in open_hits.values())
    benign = sum(1 for cat, items in open_hits.items() for item in items if is_benign(item[1]))

    if not total_closed:
        note = ("Признаков обезличивания в документе НЕТ (ни подчёркиваний, ни "
                "токенов). Если это должна быть обезличенная копия — скорее всего "
                "перед вами оригинал. Работа остановлена, файл дальше не проверялся.")
        if args.json:
            print(json.dumps({"file": str(path), "error": "no_anonymization_markers",
                              "note": note}, ensure_ascii=False, indent=2))
        else:
            print(note)
        return 1

    cats = {c: len(v) for c, v in sorted(open_hits.items(), key=lambda x: -len(x[1]))}
    kinds = ", ".join(f"{k} — {v}" for k, v in closed.most_common())

    if args.json:
        print(json.dumps({
            "file": str(path),
            "blocks": len(blocks),
            "closed": {"total": total_closed, "kinds": dict(closed)},
            "open": {"total": total_open, "by_category": cats, "likely_benign": benign},
            "findings": {c: [{"where": w, "found": f} for w, f, _ in v]
                         for c, v in open_hits.items()},
        }, ensure_ascii=False, indent=2))
    elif args.header:
        if total_open:
            opened = ", ".join(f"{c} ({n})" for c, n in cats.items())
            print(f"Обезличивание: закрыто — {total_closed} замен ({kinds}). "
                  f"ОТКРЫТО: {opened}. Цитаты из мест с открытыми данными не берутся.")
        else:
            print(f"Обезличивание: закрыто — {total_closed} замен ({kinds}). Открытых "
                  f"значений шаблоны не нашли — это НЕ доказательство полноты, "
                  f"описательные упоминания проверяются глазами.")
    elif args.summary:
        print(f"документ: {path.name} | блоков текста: {len(blocks)}")
        print(f"закрыто: {total_closed} ({kinds})")
        print(f"осталось открытым: {total_open} совпадений по {len(cats)} категориям")
        for c, n in cats.items():
            print(f"    {c}: {n}")
        if benign:
            print(f"  из них похожи на ресурсоснабжающие (обычно не утечка): {benign}")
    else:
        print(f"ФАЙЛ: {path}")
        print(f"блоков текста: {len(blocks)}\n")
        print(f"ЗАКРЫТО: {total_closed}")
        for k, v in closed.most_common():
            print(f"    {k}: {v}")
        print(f"\nОСТАЛОСЬ ОТКРЫТЫМ: {total_open} совпадений\n")
        for category, items in sorted(open_hits.items(), key=lambda x: -len(x[1])):
            print(f"--- {category}: {len(items)} ---")
            for where, found, ctx in items[:12]:
                flag = "  (похоже на ресурсоснабжающую)" if is_benign(found) else ""
                print(f"    [{where}] {found}{flag}")
                print(f"        …{ctx}…")
            if len(items) > 12:
                print(f"    … ещё {len(items) - 12}")
            print()
        print("Ноль находок означает «шаблоны не сработали», а не «документ чист».")
        print("Описательные упоминания объекта и заказчика проверяются глазами.")

    if args.fail_on_open and total_open:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
