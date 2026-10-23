---
name: ailab-pdf
description: "Use when создаёшь PDF в фирменном стиле. reportlab и стиль AI_Lab_SCRUM Co; главная ловушка — кириллица превращается в квадраты."
version: 1.0.0
author: AI_Lab_SCRUM Co
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [pdf, reportlab, style, cyrillic, ailab]
    category: ailab
    related_skills: [pdf, ailab-docx]
---

Правила фирменного стиля **AI_Lab_SCRUM Co** для PDF. Общая механика PDF (создание,
чтение, формы, объединение) — в штатном скилле `pdf`.

# AILAB PDF — корпоративные PDF

Создание PDF-документов в фирменном стиле проектной организации AI_Lab_SCRUM Co.

**Когда не применять:** когда нужен редактируемый документ — тогда `ailab-docx`,
а PDF делается экспортом из него.

## Кириллица в PDF — главная ловушка

Встроенные шрифты reportlab (Helvetica, Times, Courier) кириллицы **не
содержат**. Документ при этом собирается без единой ошибки, а весь русский текст
превращается в квадраты — замерено: `drawString` с русской строкой даёт в готовом
файле `■■■■■ ■■■■■■■■■`. Поэтому первым делом регистрируется TrueType-шрифт с
кириллицей, и только потом пишется текст.

Брендовый TT Norms Pro для этого не годится: это OpenType с постскриптовыми
контурами, `TTFont` отвечает «postscript outlines are not supported». Рабочий
шрифт — системный Arial.

## Инструменты

**reportlab** — основная библиотека для создания PDF с нуля.
**pypdf / pdfplumber** — для чтения и модификации существующих PDF.

```bash
python -c "import reportlab" || python -m pip install reportlab pypdf pdfplumber
```

## Типовой шаблон: reportlab

```python
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 PageBreak, Table, TableStyle, HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Helper: RGB tuple → HexColor ──
def gc(rgb_tuple):
    """Convert (R,G,B) to HexColor for reportlab."""
    return HexColor('#%02X%02X%02X' % rgb_tuple)

# ── Register font — обязательный шаг, без него кириллица станет квадратами ──
pdfmetrics.registerFont(TTFont('ArialTT', r'C:\Windows\Fonts\arial.ttf'))
pdfmetrics.registerFont(TTFont('ArialTT-Bold', r'C:\Windows\Fonts\arialbd.ttf'))

FONT_PDF = 'ArialTT'
FONT_PDF_BOLD = 'ArialTT-Bold'

# ── Styles ──
styles = getSampleStyleSheet()

style_body = ParagraphStyle(
    'AILAB_Body',
    fontName=FONT_PDF,
    fontSize=BODY_SIZE,
    leading=BODY_SIZE * LH_RELAXED,
    textColor=gc(INK),
    alignment=TA_LEFT,
    spaceAfter=SP_2,
)

style_h1 = ParagraphStyle(
    'AILAB_H1',
    fontName=FONT_PDF,
    fontSize=H2_SIZE,
    leading=H2_SIZE * LH_SNUG,
    textColor=gc(INK),
    alignment=TA_LEFT,
    spaceAfter=SP_4,
    spaceBefore=SP_6,
)

style_h2 = ParagraphStyle(
    'AILAB_H2',
    fontName=FONT_PDF,
    fontSize=H3_SIZE,
    leading=H3_SIZE * LH_SNUG,
    textColor=gc(INK),
    alignment=TA_LEFT,
    spaceAfter=SP_3,
    spaceBefore=SP_4,
)

style_caption = ParagraphStyle(
    'AILAB_Caption',
    fontName=FONT_PDF,
    fontSize=CAPTION_SIZE,
    leading=CAPTION_SIZE * LH_NORMAL,
    textColor=gc(GREY_500),
    alignment=TA_LEFT,
)

style_hero = ParagraphStyle(
    'AILAB_Hero',
    fontName=FONT_PDF,
    fontSize=HERO_SIZE,
    leading=HERO_SIZE * LH_TIGHT,
    textColor=gc(CHAMPAGNE),
    alignment=TA_LEFT,
)

# ── Document ──
output_path = "document.pdf"
doc = SimpleDocTemplate(
    output_path,
    pagesize=A4,
    leftMargin=PAGE_MARGIN_LEFT * cm * 2.54,   # inches → cm
    rightMargin=PAGE_MARGIN_RIGHT * cm * 2.54,
    topMargin=PAGE_MARGIN_TOP * cm * 2.54,
    bottomMargin=PAGE_MARGIN_BOTTOM * cm * 2.54,
)

story = []

# Title page (имитация тёмного cover)
# reportlab не умеет тёмный фон через Platypus — для сложной вёрстки
# используй canvas (см. ниже «Тёмный титульный лист»)

# Content
story.append(Paragraph("1.  ОБЩИЕ  ПОЛОЖЕНИЯ", style_h1))
story.append(Paragraph(
    "Настоящий документ определяет порядок проектирования и оформления "
    "конструктивных решений в составе проектной документации.",
    style_body))
story.append(Spacer(1, SP_5))

story.append(Paragraph("2.  НОРМАТИВНЫЕ  ССЫЛКИ", style_h1))
story.append(Paragraph(
    "ГОСТ 34758-2021 «Лифты. Правила и методы расчёта...»; "
    "СП 118.13330.2022 «Общественные здания и сооружения».",
    style_body))
story.append(Spacer(1, SP_5))

# Hairline
story.append(HRFlowable(
    width="100%", thickness=0.5,
    color=gc(HAIRLINE), spaceBefore=SP_4, spaceAfter=SP_4))

story.append(Paragraph("AILAB  ·  2026", style_caption))

doc.build(story)
print(f"Saved: {output_path}")
```

## Тёмный титульный лист (через canvas)

```python
from reportlab.lib.pagesizes import A4

W, H = A4  # 595.27 x 841.89 pt

c = canvas.Canvas("cover.pdf", pagesize=A4)

# Ink background
c.setFillColor(gc(INK))
c.rect(0, 0, W, H, fill=1, stroke=0)

# Hero title
c.setFillColor(gc(CHAMPAGNE))
c.setFont(FONT_PDF, HERO_SIZE)
c.drawString(50, H - 180, "ЗАГОЛОВОК")
c.drawString(50, H - 220, "ПРЕЗЕНТАЦИИ")

# Hairline
c.setStrokeColor(gc(HAIRLINE))
c.setLineWidth(0.5)
c.line(50, H - 260, 250, H - 260)

# Subtitle
c.setFillColor(gc(SILVER))
c.setFont(FONT_PDF, SMALL_SIZE + 4)
c.drawString(50, H - 285, "Подзаголовок  ·  Дата")

# Logo / brand mark
c.setFillColor(gc(CHAMPAGNE_DIM))
c.setFont(FONT_PDF, 14)
c.drawRightString(W - 50, 50, "AILAB")

c.save()
print("Saved: cover.pdf")
```

## Типовой шаблон: генерация из Markdown

Для быстрой конвертации Markdown → PDF с AILAB-стилем:

```bash
# Через pandoc с пользовательским шаблоном
pandoc input.md \
  --pdf-engine=weasyprint \
  --css=print.css \
  -o output.pdf
```

Файл `print.css`:

```css
@page {
  size: A4;
  margin: 2.5cm 2.8cm;
  @bottom-center {
    content: "AILAB  ·  " counter(page);
    font-family: Arial, sans-serif;
    font-size: 9pt;
    color: #888888;
  }
}
body {
  font-family: Arial, Helvetica, sans-serif;
  font-size: 13pt;
  line-height: 1.45;
  color: #131A2A;
}
h1 {
  font-size: 22pt;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: #131A2A;
  border-bottom: 1px solid rgba(19,26,42,0.12);
  padding-bottom: 8pt;
  margin-top: 32pt;
}
h2 {
  font-size: 16pt;
  font-weight: 500;
  color: #131A2A;
  margin-top: 24pt;
}
p {
  text-align: left;
  orphans: 3;
  widows: 3;
}
.caption {
  font-size: 10pt;
  color: #888888;
}
```

## Правила PDF

1. **Всегда** A4, portrait (кроме спец. буклетов)
2. Поля: 2.5–2.8 см со всех сторон
3. Шрифт: Arial (Windows) или Helvetica (cross-platform)
4. Колонтитулы: снизу — «AILAB  ·  № страницы», сверху — пусто
5. Никаких фоновых изображений в теле документа
6. Тёмный ink-фон — ТОЛЬКО на титульной странице
7. Ссылки: Champagne или Ink с underline, НЕ синие
8. **Готовый файл проверяется чтением, а не глазами по коду:**
   `python -c "from pypdf import PdfReader; print(PdfReader('document.pdf').pages[0].extract_text()[:200])"`
   — в выводе должен быть русский текст. Квадраты `■` означают, что шрифт не
   зарегистрирован и файл надо пересобрать

## Антипаттерны

- 🚫 Встроенные Helvetica / Times для русского текста — молча дают квадраты
- 🚫 Синие ссылки (стандарт web) — используй ink + underline
- 🚫 Цветные заголовки
- 🚫 Georgia / Times / serif шрифты
- 🚫 Яркие акцентные цвета в таблицах (только champagne, silver, grey-100)
- 🚫 Watermark'и (кроме DRAFT — и то диагонально, champagne, 10% opacity)
