---
name: ailab-docx
description: "Use when создаёшь документ Word в фирменном стиле. Типографика, цвета и структура корпоративного документа AI_Lab_SCRUM Co."
version: 1.0.0
author: AI_Lab_SCRUM Co
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [word, docx, documents, style, ailab]
    category: ailab
    related_skills: [docx, ailab-pdf]
---

Правила фирменного стиля **AI_Lab_SCRUM Co** для документов Word. Механика работы
с `.docx` (создание, правка, шаблоны, ревизии) — в штатном скилле `docx`.

# AILAB DOCX — корпоративные документы

Создание документов Word в фирменном стиле проектной организации AI_Lab_SCRUM Co.

**Когда не применять:** правка присланного документа (оформление берётся из
него) и документы по форме заказчика — там бланк задан не нами.

## Инструменты

**python-docx** — основная библиотека. На рабочей машине её может не быть:

```bash
python -c "import docx" || python -m pip install python-docx
python your_script.py
```

## Типовой шаблон документа

```python
from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn

doc = Document()

# ── Page setup ──
section = doc.sections[0]
section.top_margin    = Inches(PAGE_MARGIN_TOP)
section.bottom_margin = Inches(PAGE_MARGIN_BOTTOM)
section.left_margin   = Inches(PAGE_MARGIN_LEFT)
section.right_margin  = Inches(PAGE_MARGIN_RIGHT)

# ── Default style ──
style = doc.styles['Normal']
font = style.font
font.name = FONT
font.size = Pt(BODY_SIZE)
font.color.rgb = RGBColor(*INK)
style.paragraph_format.space_after = Pt(SP_2)
style.paragraph_format.line_spacing = LH_RELAXED

# ── Helper: add AILAB-styled heading ──
def ailab_heading(doc, text, level=1):
    """Heading in AILAB style: UPPERCASE, Ink, Medium weight."""
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.name = FONT
        run.font.color.rgb = RGBColor(*INK)
        if level == 1:
            run.font.size = Pt(H2_SIZE)
            run.font.bold = False  # Medium, not Bold
        elif level == 2:
            run.font.size = Pt(H3_SIZE)
            run.font.bold = False
    return h

def ailab_body(doc, text):
    """Body paragraph — Regular 13pt, relaxed line-height."""
    p = doc.add_paragraph(text)
    for run in p.runs:
        run.font.name = FONT
        run.font.size = Pt(BODY_SIZE)
        run.font.color.rgb = RGBColor(*INK)
    p.paragraph_format.line_spacing = LH_RELAXED
    return p

def ailab_caption(doc, text):
    """Caption / source — small, grey."""
    p = doc.add_paragraph(text)
    for run in p.runs:
        run.font.name = FONT
        run.font.size = Pt(CAPTION_SIZE)
        run.font.color.rgb = RGBColor(*GREY_500)
    return p

def ailab_tag(doc, text):
    """Silver tag — inline rectangular label."""
    p = doc.add_paragraph()
    run = p.add_run(f" {text} ")
    run.font.name = FONT
    run.font.size = Pt(TAG_SIZE)
    run.font.color.rgb = RGBColor(*INK)
    run.font.bold = True
    # Silver background via shading
    from docx.oxml import OxmlElement
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), 'C1C5D0')
    shd.set(qn('w:val'), 'clear')
    run._r.get_or_add_rPr().append(shd)
    return p

def ailab_hairline(doc):
    """Horizontal hairline rule."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(SP_3)
    p.paragraph_format.space_after = Pt(SP_3)
    # Bottom border on paragraph
    from docx.oxml import OxmlElement
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '2')  # ~0.5pt = hairline
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), 'D8DBE1')
    pBdr.append(bottom)
    pPr.append(pBdr)
    return p

# ── Document structure example ──

# Title page block
p = doc.add_paragraph()
run = p.add_run("НАЗВАНИЕ  ДОКУМЕНТА")
run.font.name = FONT; run.font.size = Pt(H1_SIZE)
run.font.color.rgb = RGBColor(*INK)
p.alignment = WD_ALIGN_PARAGRAPH.LEFT

# Subtitle
p = doc.add_paragraph()
run = p.add_run("Тип документа  ·  Проект  ·  Дата")
run.font.name = FONT; run.font.size = Pt(BODY_SIZE)
run.font.color.rgb = RGBColor(*FG_SECONDARY)

ailab_hairline(doc)

# Section
ailab_heading(doc, "1.  ОБЩИЕ  ПОЛОЖЕНИЯ", level=1)
ailab_body(doc, "Настоящий документ определяет порядок...")

ailab_heading(doc, "2.  ТЕХНИЧЕСКИЕ  РЕШЕНИЯ", level=1)
ailab_heading(doc, "2.1.  Конструктивные решения", level=2)
ailab_body(doc, "Основные несущие конструкции запроектированы...")

# Source / reference
ailab_hairline(doc)
ailab_caption(doc, "Источник: ГОСТ 34758-2021, СП 118.13330.2022")

doc.save("document.docx")
```

## Правила оформления документов

### Типографика
- Заголовки: UPPERCASE, Medium (не Bold), Ink Navy
- Тело: Regular 13pt, Ink, межстрочный 1.35–1.5
- Подписи/сноски: 10pt, Grey 500
- Выравнивание: ВСЕГДА по левому краю (не по ширине)
- Абзацный отступ: отсутствует (отбивка пустой строкой)

### Цвета
- Текст: ТОЛЬКО Ink (`#131A2A`) или Grey 500 (`#888888`)
- Акцент: Champagne ТОЛЬКО для ключевых цифр и декоративных заголовков
- Никаких цветных заголовков (синих, красных и т.д.)

### Структура
- Разделители между секциями — hairline (0.5pt)
- Нумерация разделов: `1.  ЗАГОЛОВОК` (цифра + два пробела + UPPERCASE)
- Между разделами — двойной отступ

### Стиль текста
- Русский язык, деловой стиль
- От третьего лица или безличные конструкции
- Без восклицательных знаков
- Без маркетинговых эпитетов
- Числа с неразрывными пробелами: `6 183 640 792,00 ₽`

## Антипаттерны

- 🚫 Times New Roman (только Arial)
- 🚫 Выравнивание по ширине
- 🚫 Цветной текст (кроме ink, grey-500, champagne)
- 🚫 Подчёркивания (кроме ссылок)
- 🚫 Курсив для русского текста
- 🚫 Более 3 уровней заголовков
