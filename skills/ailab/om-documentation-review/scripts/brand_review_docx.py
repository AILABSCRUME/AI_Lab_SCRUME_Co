#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brand_review_docx.py — логотип и колонтитулы AI_Lab_SCRUM_Co для ведомости сверки.

Что делает:
  1) перекрашивает приложенный логотип под светлый фон (белый текст → тёмный,
     оранжевый градиент сохраняется), обрезает и сохраняет PNG;
  2) ставит логотип в верхний колонтитул слева, AI_Lab_SCRUM_Co справа;
     в нижний — наименование слева, описание с датой справа;
  3) добавляет оранжевые разделительные линии (bottom хедера, top футера);
  4) подгоняет ширины колонок под формат страницы.

Запуск:
    python brand_review_docx.py <документ.docx> <логотип.png> [текст колонтитула]

Питфоллы (проверено):
  * логотип приходит БЕЛЫМ на прозрачном фоне — на белой бумаге исчезнет;
  * фиксированный таб-стоп на 17 см не работает для A3 landscape (42 см) —
    стоп считать от page_width - margins;
  * логотип ставить в колонтитул, а не в тело документа.
"""
from __future__ import annotations

import sys
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt, RGBColor
from PIL import Image

DARK = RGBColor(0x1F, 0x24, 0x2B)
ORANGE = RGBColor(0xE0, 0x60, 0x00)
DARK_RGB = (0x1F, 0x24, 0x2B)
BRAND = "AI_Lab_SCRUM_Co"


def make_light_logo(src: Path, dst: Path, max_width: int = 900) -> Path:
    """Белый текст → тёмный, оранжевая графика без изменений."""
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    px = im.load()
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    po = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            neutral = abs(r - g) < 28 and abs(g - b) < 28 and abs(r - b) < 28
            po[x, y] = (DARK_RGB[0], DARK_RGB[1], DARK_RGB[2], a) if neutral else (r, g, b, a)
    box = out.getchannel("A").getbbox()
    if box:
        out = out.crop(box)
    if out.size[0] > max_width:
        out = out.resize((max_width, int(out.size[1] * max_width / out.size[0])), Image.LANCZOS)
    out.save(dst)
    return dst


def _clear(par) -> None:
    for r in list(par.runs):
        r._element.getparent().remove(r._element)
    par.text = ""


def _border(par, edge: str, color: str = "E06000") -> None:
    pPr = par._p.get_or_add_pPr()
    bdr = pPr.find(qn("w:pBdr"))
    if bdr is None:
        bdr = OxmlElement("w:pBdr")
        pPr.append(bdr)
    e = OxmlElement("w:" + edge)
    e.set(qn("w:val"), "single")
    e.set(qn("w:sz"), "6")
    e.set(qn("w:space"), "4")
    e.set(qn("w:color"), color)
    bdr.append(e)


def brand(doc_path: Path, logo_src: Path, footer_right: str) -> None:
    work = doc_path.parent / "_logo_light.png"
    make_light_logo(logo_src, work)

    d = docx.Document(str(doc_path))
    sec = d.sections[0]
    text_width = Emu(sec.page_width - sec.left_margin - sec.right_margin)
    wide = text_width.cm > 30
    print("формат: %.0f x %.0f см | область %.1f см -> %s" % (
        sec.page_width.cm, sec.page_height.cm, text_width.cm,
        "A3 landscape" if wide else "A4"))

    # верх: логотип слева, бренд справа
    sec.header.is_linked_to_previous = False
    hp = sec.header.paragraphs[0] if sec.header.paragraphs else sec.header.add_paragraph()
    _clear(hp)
    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    hp.paragraph_format.tab_stops.clear_all()
    hp.paragraph_format.tab_stops.add_tab_stop(text_width, WD_TAB_ALIGNMENT.RIGHT)
    hp.add_run().add_picture(str(work), width=Cm(3.6))
    r = hp.add_run("\t" + BRAND)
    r.font.size = Pt(9)
    r.font.color.rgb = ORANGE
    r.bold = True
    _border(hp, "bottom")

    # низ: бренд слева, описание справа
    sec.footer.is_linked_to_previous = False
    fp = sec.footer.paragraphs[0] if sec.footer.paragraphs else sec.footer.add_paragraph()
    _clear(fp)
    fp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    fp.paragraph_format.tab_stops.clear_all()
    fp.paragraph_format.tab_stops.add_tab_stop(text_width, WD_TAB_ALIGNMENT.RIGHT)
    fl = fp.add_run(BRAND)
    fl.font.size = Pt(9)
    fl.font.color.rgb = DARK
    fl.bold = True
    fr = fp.add_run("\t" + footer_right)
    fr.font.size = Pt(8)
    fr.font.color.rgb = DARK
    _border(fp, "top")

    # логотип не должен остаться в теле
    for par in list(d.paragraphs):
        if par._p.findall(".//" + qn("w:drawing")):
            par._element.getparent().remove(par._element)

    colw = [Cm(9.5), Cm(10.0), Cm(11.5), Cm(11.5)] if wide else \
           [Cm(4.4), Cm(5.4), Cm(8.6), Cm(8.6)]
    t = d.tables[0]
    for row in t.rows:
        for ci, cell in enumerate(row.cells):
            if ci < len(colw):
                cell.width = colw[ci]

    d.save(str(doc_path))
    print("готово:", doc_path)
    print("header:", repr(sec.header.paragraphs[0].text))
    print("footer:", repr(sec.footer.paragraphs[0].text))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    brand(Path(sys.argv[1]), Path(sys.argv[2]),
          sys.argv[3] if len(sys.argv) > 3 else "Сверка результатов проверки тома ИОС1.1")
