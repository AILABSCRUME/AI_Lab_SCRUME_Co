#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_review_docx.py — сборка итоговой ведомости сверки тома ЭОМ на 4 колонки.

Формат: «ВОПРОС | МАСТЕРМАЙНД | AI_Lab_SCRUM Co | РАСХОЖДЕНИЯ».
Несоответствия и новые находки — красным (C00000). Новые пункты — целыми
красными строками с пометкой источника («шаг 1, код» / «шаг 3, аудитор»).

Запуск:
    python build_review_docx.py <шаблон.docx> <выход.docx> <rash.json>

rash.json:
{
  "by_row":  {"2": "текст расхождения для строки 2 шаблона", "3": "..."},
  "new_rows": [["Вопрос", "МастерМайнд", "AI_Lab_SCRUM Co", "Расхождение"], ...],
  "note": "итоговое примечание"
}

Питфоллы (проверено):
  * без дописывания w:gridCol Word ломает ширины новой колонки;
  * cell.text = ... теряет формат — задавать через add_run + font.size;
  * старое примечание шаблона удалять, иначе их остаётся два противоречащих.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import docx
from docx.shared import Pt, RGBColor, Cm
from docx.oxml.ns import qn

RED = RGBColor(0xC0, 0x00, 0x00)
WIDTHS = [Cm(4.4), Cm(5.4), Cm(8.6), Cm(8.6)]
OLD_NOTE_MARKER = "Примечание: красным показаны расхождения, уточнения и дополнения"


def set_cell(cell, text: str, red: bool = False, bold: bool = False, size: int = 9) -> None:
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text)
    r.font.size = Pt(size)
    if red:
        r.font.color.rgb = RED
    if bold:
        r.bold = True


def build(src: Path, dst: Path, payload: dict) -> None:
    d = docx.Document(str(src))
    t = d.tables[0]

    # 1) четвёртая колонка в шапке
    new_hdr = copy.deepcopy(t.rows[0].cells[-1]._tc)
    t.rows[0].cells[-1]._tc.addnext(new_hdr)
    set_cell(t.rows[0].cells[3], "РАСХОЖДЕНИЯ", red=True, bold=True)

    # 2) расхождения по существующим строкам шаблона
    by_row = payload.get("by_row", {})
    for ri in range(1, len(t.rows)):
        row = t.rows[ri]
        new_tc = copy.deepcopy(row.cells[-1]._tc)
        row.cells[-1]._tc.addnext(new_tc)
        txt = by_row.get(str(ri), "")
        set_cell(row.cells[3], txt or "—", red=bool(txt))

    # 3) новые строки — целиком красным
    for cells in payload.get("new_rows", []):
        t._tbl.append(copy.deepcopy(t.rows[1]._tr))
        row = t.rows[-1]
        for ci, txt in enumerate(cells[:4]):
            set_cell(row.cells[ci], txt, red=(ci != 1), bold=(ci == 0))

    # 4) примечание: убрать устаревшее, дописать своё
    for para in list(d.paragraphs):
        if para.text.strip().startswith(OLD_NOTE_MARKER):
            para._element.getparent().remove(para._element)
    note = payload.get("note")
    if note:
        p = d.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        r = p.add_run(note)
        r.font.size = Pt(9)
        r.bold = True

    # 5) ЛОВУШКА: без этого Word ломает ширины новой колонки
    grid = t._tbl.find(qn("w:tblGrid"))
    cols = grid.findall(qn("w:gridCol"))
    while len(cols) < 4:
        cols[-1].addnext(copy.deepcopy(cols[-1]))
        cols = grid.findall(qn("w:gridCol"))

    for row in t.rows:
        for ci, cell in enumerate(row.cells):
            if ci < len(WIDTHS):
                cell.width = WIDTHS[ci]

    d.save(str(dst))
    print(f"сохранено: {dst}")
    print(f"строк: {len(d.tables[0].rows)} | колонок: {len(d.tables[0].columns)}")


def verify(path: Path) -> None:
    d = docx.Document(str(path))
    t = d.tables[0]
    print("шапка:", [c.text.strip() for c in t.rows[0].cells])
    for ri, row in enumerate(t.rows):
        red_cols = set()
        for ci, cell in enumerate(row.cells):
            for para in cell.paragraphs:
                for r in para.runs:
                    if r.font.color and r.font.color.rgb and str(r.font.color.rgb) == "C00000" \
                            and r.text.strip():
                        red_cols.add(ci)
        cells = [c.text.strip() for c in row.cells]
        print(f"[{ri:2d}] красн={sorted(red_cols)} | {cells[0][:40]:40s} | "
              f"{cells[3][:60] if len(cells) > 3 else ''}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    src, dst, payload_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    build(src, dst, json.loads(payload_path.read_text(encoding="utf-8")))
    verify(dst)
