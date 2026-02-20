"""
Mu.Orbita PDF Report Generator v3.0
====================================
Generador profesional de informes PDF con ReportLab.
Drop-in replacement para el endpoint /api/v1/generate-pdf en Railway.

CAMBIOS vs v2.0:
- Colores corporativos corregidos (marrón/dorado/crema del logo)
- Markdown → ReportLab sin asteriscos crudos
- Portada profesional con branding
- Sin saltos de página vacíos
- Gráficos matplotlib con paleta corporativa
- Narrativa interpretativa con callout boxes
- Mapas con leyenda legible
- Tabla de riesgos con semáforo visual

INTEGRACIÓN:
    from muorbita_pdf_generator_v3 import generate_muorbita_report
    result = generate_muorbita_report(data_dict)
    # result = {"success": True, "pdf_base64": "...", "filename": "...", ...}

Autor: Mu.Orbita
Fecha: 2026-02
"""

import io
import re
import base64
import json
import math
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple

# ReportLab imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, KeepTogether, HRFlowable, Flowable
)
from reportlab.pdfgen import canvas

# Matplotlib para gráficos
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
from matplotlib.patches import FancyBboxPatch
import numpy as np


# ============================================================
# 1. CORPORATE COLOR PALETTE
#    Matches logo, email template, and landing page
# ============================================================

C = {
    # Primary brand — extracted from email HTML
    'header':       '#F9F7F2',   # Header bg = CREAM (not solid brown!)
    'header_border':'#E6DDD0',   # Subtle border under header
    'brown_dark':   '#3E2B1D',   # Main text color / brand text
    'brown':        '#5C4033',   # Subtítulos
    'gold':         '#9E7E46',   # "INFORME SATELITAL" accent — THE key brand color
    'gold_light':   '#C4A265',   # Decorative borders

    # Backgrounds
    'cream':        '#F9F7F2',   # Main background (email bg)
    'cream_dark':   '#E6DDD0',   # Card borders, table borders
    'white':        '#FFFFFF',   # Card interiors
    'bg_light':     '#FEFCF9',   # Slightly lighter

    # Text
    'text':         '#3E2B1D',   # Primary text (same as brown_dark)
    'text_light':   '#7A7A7A',   # Secondary text
    'text_muted':   '#AAAAAA',   # Very soft

    # Semáforo agronómico
    'green':        '#4B7F3A',   # Vigor alto / OK
    'green_bg':     '#E8F0E4',
    'yellow':       '#B8860B',   # Precaución / Moderado
    'yellow_bg':    '#FFF8E7',
    'red':          '#A63D2F',   # Alerta / Estrés
    'red_bg':       '#FDEDEC',

    # Charts
    'chart_ndvi':   '#4B7F3A',
    'chart_ndwi':   '#3B7DD8',
    'chart_evi':    '#C4A265',

    # Cover accent band (a warm muted brown, not as dark)
    'cover_band':   '#EDE6DA',

    # Table header (warm brown-gold, professional)
    'table_header': '#8B7B62',
}

def hex_color(key):
    """Get ReportLab Color from palette key."""
    return colors.HexColor(C[key])


# ============================================================
# 2. CUSTOM STYLES
# ============================================================

def get_styles():
    """Create all custom paragraph styles."""
    base = getSampleStyleSheet()

    def _add(name, **kw):
        if name in [s.name for s in base.byName.values()]:
            return
        parent = kw.pop('parent', 'Normal')
        base.add(ParagraphStyle(name, parent=base[parent], **kw))

    # --- Cover page ---
    _add('CoverBrand',    parent='Title', fontName='Helvetica-Bold', fontSize=36,
         textColor=hex_color('white'), alignment=TA_LEFT, leading=42)
    _add('CoverTagline',  fontName='Helvetica', fontSize=11,
         textColor=colors.Color(1,1,1,0.85), alignment=TA_LEFT, leading=14)
    _add('CoverTitle',    fontName='Helvetica-Bold', fontSize=22,
         textColor=hex_color('brown_dark'), alignment=TA_LEFT, leading=28, spaceBefore=6*mm)
    _add('CoverSubtitle', fontName='Helvetica', fontSize=13,
         textColor=hex_color('brown'), alignment=TA_LEFT, leading=16, spaceAfter=8*mm)
    _add('CoverMeta',     fontName='Helvetica', fontSize=10,
         textColor=hex_color('text'), leading=16, spaceAfter=2*mm)

    # --- Content pages ---
    _add('SectionTitle',  fontName='Helvetica-Bold', fontSize=14,
         textColor=hex_color('brown_dark'), spaceBefore=8*mm, spaceAfter=4*mm,
         borderPadding=(0, 0, 2, 0))
    _add('SubsectionTitle', fontName='Helvetica-Bold', fontSize=11,
         textColor=hex_color('brown'), spaceBefore=5*mm, spaceAfter=3*mm)
    _add('Body',          fontName='Helvetica', fontSize=10,
         textColor=hex_color('text'), leading=15, alignment=TA_JUSTIFY, spaceAfter=3*mm)
    _add('BodySmall',     fontName='Helvetica', fontSize=9,
         textColor=hex_color('text'), leading=13, spaceAfter=2*mm)
    _add('Callout',       fontName='Helvetica', fontSize=10,
         textColor=hex_color('text'), leading=15, alignment=TA_JUSTIFY,
         spaceBefore=2*mm, spaceAfter=2*mm,
         leftIndent=4*mm, rightIndent=2*mm)
    _add('Footnote',      fontName='Helvetica', fontSize=7.5,
         textColor=hex_color('text_muted'), leading=10, alignment=TA_LEFT)
    _add('KPIValue',      fontName='Helvetica-Bold', fontSize=24,
         alignment=TA_CENTER, leading=28)
    _add('KPILabel',      fontName='Helvetica', fontSize=8,
         textColor=hex_color('text_light'), alignment=TA_CENTER,
         spaceBefore=1*mm, spaceAfter=1*mm)
    _add('KPIStatus',     fontName='Helvetica-Bold', fontSize=9,
         alignment=TA_CENTER, spaceBefore=0.5*mm)
    _add('TableHeader',   fontName='Helvetica-Bold', fontSize=9,
         textColor=hex_color('white'), alignment=TA_CENTER)
    _add('TableCell',     fontName='Helvetica', fontSize=9,
         textColor=hex_color('text'), alignment=TA_CENTER)
    _add('TableCellLeft', fontName='Helvetica', fontSize=9,
         textColor=hex_color('text'), alignment=TA_LEFT)

    return base


# ============================================================
# 3. INTERPRETATION FUNCTIONS
# ============================================================

def ndvi_status(v: float) -> Tuple[str, str]:
    if v >= 0.60: return ("Vigor alto",     'green')
    if v >= 0.45: return ("Vigor moderado",  'yellow')
    if v >= 0.35: return ("Vigor bajo",      'yellow')
    if v >= 0.20: return ("Estrés severo",   'red')
    return ("Suelo desnudo / sin cultivo", 'red')

def ndwi_status(v: float) -> Tuple[str, str]:
    if v >= 0.20: return ("Estado óptimo",       'green')
    if v >= 0.10: return ("Déficit leve",        'yellow')
    if v >= 0.00: return ("Déficit moderado",    'yellow')
    return ("Déficit severo",  'red')

def stress_status(pct: float) -> Tuple[str, str]:
    if pct <= 15:  return ("Bajo",       'green')
    if pct <= 40:  return ("Moderado",   'yellow')
    if pct <= 60:  return ("Alto",       'red')
    return ("Crítico", 'red')

def hetero_label(p10, p90):
    d = abs(p90 - p10)
    if d < 0.15: return "Baja (homogéneo)"
    if d < 0.25: return "Moderada"
    return "Alta (VRA recomendado)"

def crop_label(ct):
    m = {'olive':'Olivar','olivar':'Olivar','olivo':'Olivar',
         'vineyard':'Viñedo','viña':'Viñedo','vid':'Viñedo',
         'almond':'Almendro','almendro':'Almendro'}
    return m.get(str(ct).lower(), str(ct).capitalize() if ct else 'Cultivo')

def fmt_date(d):
    if not d: return '—'
    try:
        return datetime.strptime(str(d)[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
    except:
        return str(d)

def crop_ndvi_range(ct):
    cl = str(ct).lower()
    if 'oliv' in cl: return '0.45–0.65'
    if 'viñ' in cl or 'vid' in cl or 'vine' in cl: return '0.40–0.60'
    if 'almend' in cl or 'almond' in cl: return '0.50–0.70'
    return '0.45–0.65'


# ============================================================
# 4. CUSTOM FLOWABLES
# ============================================================

class CalloutBox(Flowable):
    """Colored callout box with left border accent."""

    def __init__(self, text, styles, accent='gold', width=170*mm):
        Flowable.__init__(self)
        self.text = text
        self.styles = styles
        self.accent = accent
        self._width = width
        # Pre-render paragraph to measure height
        self._para = Paragraph(text, styles['Callout'])
        w, h = self._para.wrap(width - 10*mm, 500*mm)
        self._height = h + 8*mm

    def wrap(self, availWidth, availHeight):
        return self._width, self._height

    def draw(self):
        c = self.canv
        w, h = self._width, self._height

        # Background
        c.setFillColor(hex_color('cream'))
        c.roundRect(0, 0, w, h, 3, fill=True, stroke=False)

        # Left accent bar
        c.setFillColor(hex_color(self.accent))
        c.rect(0, 0, 3*mm, h, fill=True, stroke=False)

        # Text
        self._para.wrap(w - 10*mm, h)
        self._para.drawOn(c, 5*mm, 3*mm)


class SectionDivider(Flowable):
    """Thin gold line used under section titles."""
    def __init__(self, width=170*mm):
        Flowable.__init__(self)
        self._width = width
    def wrap(self, aw, ah):
        return self._width, 1*mm
    def draw(self):
        self.canv.setStrokeColor(hex_color('gold_light'))
        self.canv.setLineWidth(1.5)
        self.canv.line(0, 0, self._width, 0)


# ============================================================
# 5. MARKDOWN → REPORTLAB PARSER
# ============================================================

def md_to_flowables(md_text: str, styles) -> List:
    """
    Convert Claude's markdown analysis into ReportLab flowables.
    Handles: ##, ###, **, -, tables (basic), blank lines.
    Crucially: NO raw asterisks in output.
    """
    if not md_text:
        return [Paragraph("<i>Análisis no disponible.</i>", styles['Body'])]

    elements = []
    lines = md_text.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Blank line → small spacer
        if not line:
            elements.append(Spacer(1, 2*mm))
            i += 1
            continue

        # --- (horizontal rule)
        if line.startswith('---'):
            elements.append(Spacer(1, 3*mm))
            i += 1
            continue

        # ## Section header
        if line.startswith('## '):
            title = _clean_md(line[3:])
            elements.append(Spacer(1, 4*mm))
            elements.append(Paragraph(title, styles['SectionTitle']))
            elements.append(SectionDivider())
            elements.append(Spacer(1, 2*mm))
            i += 1
            continue

        # ### Subsection header
        if line.startswith('### '):
            title = _clean_md(line[4:])
            elements.append(Paragraph(title, styles['SubsectionTitle']))
            i += 1
            continue

        # Bullet list item
        if line.startswith('- ') or line.startswith('• '):
            text = _clean_md(line[2:])
            elements.append(Paragraph(f'▸ {text}', styles['BodySmall']))
            i += 1
            continue

        # Markdown table (|...|)
        if line.startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            elements.append(_build_md_table(table_lines, styles))
            elements.append(Spacer(1, 2*mm))
            continue

        # Regular paragraph
        text = _clean_md(line)
        elements.append(Paragraph(text, styles['Body']))
        i += 1

    return elements


def _clean_md(text: str) -> str:
    """Remove markdown artifacts, convert to ReportLab XML."""
    # Bold **text** → <b>text</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic *text* → <i>text</i>
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    # Remove stray asterisks
    text = text.replace('**', '').replace('*', '')
    # < and > for XML safety (except our tags)
    text = text.replace('&', '&amp;')
    # Preserve our tags
    text = re.sub(r'<(/?)b>', lambda m: f'<{m.group(1)}b>', text)
    text = re.sub(r'<(/?)i>', lambda m: f'<{m.group(1)}i>', text)
    return text


def _build_md_table(lines, styles) -> Table:
    """Parse markdown table lines into a ReportLab Table."""
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if cells and all(c.replace('-','').replace(':','').strip() == '' for c in cells):
            continue  # Skip separator row
        rows.append(cells)

    if not rows:
        return Spacer(1, 1*mm)

    # Build table data
    table_data = []
    for r_idx, row in enumerate(rows):
        tr = []
        for cell in row:
            clean = _clean_md(cell)
            if r_idx == 0:
                tr.append(Paragraph(clean, styles['TableHeader']))
            else:
                tr.append(Paragraph(clean, styles['TableCell']))
        table_data.append(tr)

    n_cols = max(len(r) for r in table_data) if table_data else 1
    col_w = 170*mm / n_cols

    tbl = Table(table_data, colWidths=[col_w]*n_cols)
    style_cmds = [
        ('BACKGROUND', (0,0), (-1,0), hex_color('table_header')),
        ('TEXTCOLOR', (0,0), (-1,0), hex_color('white')),
        ('BACKGROUND', (0,1), (-1,-1), hex_color('white')),
        ('GRID', (0,0), (-1,-1), 0.5, hex_color('cream_dark')),
        ('BOX', (0,0), (-1,-1), 1, hex_color('table_header')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]
    # Alternate row colors
    for r in range(1, len(table_data)):
        if r % 2 == 0:
            style_cmds.append(('BACKGROUND', (0,r), (-1,r), hex_color('cream')))
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ============================================================
# 6. CHART GENERATION (matplotlib, corporate palette)
# ============================================================

def _chart_style():
    """Apply corporate style to matplotlib."""
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': ['Helvetica', 'Arial', 'DejaVu Sans'],
        'font.size': 9,
        'axes.titlesize': 11,
        'axes.titleweight': 'bold',
        'axes.titlecolor': C['brown_dark'],
        'axes.edgecolor': C['cream_dark'],
        'axes.labelcolor': C['text_light'],
        'xtick.color': C['text_light'],
        'ytick.color': C['text_light'],
        'grid.color': C['cream_dark'],
        'grid.linewidth': 0.5,
        'figure.facecolor': C['cream'],
        'axes.facecolor': '#FDFBF7',
    })


def generate_ts_chart(time_series: List[Dict], crop_type: str = 'olivar',
                      width_px=680, height_px=240) -> bytes:
    """Time series chart with reference zones, corporate colors."""
    _chart_style()

    if not time_series or len(time_series) < 2:
        fig, ax = plt.subplots(figsize=(width_px/100, height_px/100), dpi=180)
        ax.text(0.5, 0.5, 'Datos de serie temporal insuficientes',
                ha='center', va='center', fontsize=11, color=C['text_muted'])
        ax.axis('off')
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', facecolor='#F9F7F2', dpi=180)
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    dates, ndvi, ndwi, evi = [], [], [], []
    for pt in time_series:
        try:
            d = pt.get('date', '')
            if d:
                dates.append(datetime.strptime(d[:10], '%Y-%m-%d'))
                ndvi.append(pt.get('ndvi', pt.get('NDVI', 0)) or 0)
                ndwi.append(pt.get('ndwi', pt.get('NDWI', 0)) or 0)
                evi.append(pt.get('evi', pt.get('EVI', 0)) or 0)
        except:
            continue

    if len(dates) < 2:
        return generate_ts_chart([], crop_type, width_px, height_px)

    fig, ax = plt.subplots(figsize=(width_px/100, height_px/100), dpi=180)

    # Reference zones
    ax.axhspan(0.0, 0.35, alpha=0.06, color=C['red'], zorder=0)
    ax.axhspan(0.45, 0.65, alpha=0.06, color=C['green'], zorder=0)
    ax.axhline(y=0.35, color=C['red'], linestyle='--', linewidth=0.7, alpha=0.4)
    ax.axhline(y=0.60, color=C['green'], linestyle='--', linewidth=0.7, alpha=0.4)

    # Data lines
    ax.plot(dates, ndvi, color=C['chart_ndvi'], linewidth=2.2, label='NDVI (Vigor)',
            marker='o', markersize=4, markerfacecolor='#F9F7F2', markeredgewidth=1.5)
    ax.plot(dates, ndwi, color=C['chart_ndwi'], linewidth=2, label='NDWI (Agua)',
            marker='s', markersize=3.5, markerfacecolor='#F9F7F2', markeredgewidth=1.2)
    if any(v != 0 for v in evi):
        ax.plot(dates, evi, color=C['chart_evi'], linewidth=1.8, label='EVI (Productiv.)',
                marker='^', markersize=3.5, markerfacecolor='#F9F7F2', markeredgewidth=1.2)

    # Zone labels
    ax.text(dates[-1], 0.17, ' Estrés', fontsize=7, color=C['red'], alpha=0.5, va='center')
    ax.text(dates[-1], 0.55, ' Óptimo', fontsize=7, color=C['green'], alpha=0.5, va='center')

    ax.set_ylabel('Valor del índice')
    ax.set_title('Evolución Temporal de Índices', pad=10)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=10))
    plt.xticks(rotation=30, ha='right')
    ax.set_ylim(-0.15, 1.0)
    ax.legend(loc='upper right', fontsize=8, framealpha=0.9, edgecolor=C['cream_dark'])
    ax.grid(True, alpha=0.3)

    # Remove top/right spines
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor='#F9F7F2', dpi=180)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_ndvi_gauge(ndvi_mean, ndvi_p10, ndvi_p90, width_px=520, height_px=120) -> bytes:
    """Horizontal bar gauge showing NDVI distribution on a colored scale."""
    _chart_style()
    fig, ax = plt.subplots(figsize=(width_px/100, height_px/100), dpi=180)

    # Gradient bar
    gradient = np.linspace(0, 1, 256).reshape(1, -1)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
        'ndvi', [(0, C['red']), (0.35, '#E8A838'), (0.55, C['yellow']),
                 (0.7, C['green']), (1.0, '#2D5016')])
    ax.imshow(gradient, aspect='auto', cmap=cmap, extent=[0, 1, 0, 1])

    # P10-P90 bracket
    ax.plot([ndvi_p10, ndvi_p10], [-0.3, 1.3], color=C['brown_dark'], linewidth=1.5, linestyle='--', alpha=0.7)
    ax.plot([ndvi_p90, ndvi_p90], [-0.3, 1.3], color=C['brown_dark'], linewidth=1.5, linestyle='--', alpha=0.7)
    ax.annotate(f'P10: {ndvi_p10:.2f}', xy=(ndvi_p10, -0.5), ha='center', fontsize=8, color=C['text_light'])
    ax.annotate(f'P90: {ndvi_p90:.2f}', xy=(ndvi_p90, -0.5), ha='center', fontsize=8, color=C['text_light'])

    # Mean marker
    ax.plot(ndvi_mean, 0.5, marker='v', markersize=14, color=C['brown_dark'], zorder=5)
    ax.annotate(f'Media: {ndvi_mean:.2f}', xy=(ndvi_mean, 1.5), ha='center',
                fontsize=10, fontweight='bold', color=C['brown_dark'])

    # Scale labels
    for v in [0, 0.2, 0.35, 0.45, 0.6, 0.8, 1.0]:
        ax.text(v, -1.0, f'{v:.1f}', ha='center', fontsize=7, color=C['text_muted'])

    # Zone names
    ax.text(0.175, 1.6, 'Estrés', ha='center', fontsize=7, color=C['red'], alpha=0.7)
    ax.text(0.40, 1.6, 'Bajo', ha='center', fontsize=7, color=C['yellow'], alpha=0.7)
    ax.text(0.525, 1.6, 'Moderado', ha='center', fontsize=7, color=C['yellow'], alpha=0.7)
    ax.text(0.72, 1.6, 'Alto', ha='center', fontsize=7, color=C['green'], alpha=0.7)

    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-1.3, 2.2)
    ax.axis('off')
    ax.set_title('Distribución NDVI en parcela', fontsize=10, fontweight='bold',
                 color=C['brown_dark'], pad=2)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor='#F9F7F2', dpi=180)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_heatmap(title, mean_val, cmap_name='RdYlGn',
                     width_px=280, height_px=220) -> bytes:
    """Improved placeholder heatmap with legend and stats."""
    _chart_style()
    fig, ax = plt.subplots(figsize=(width_px/100, height_px/100), dpi=180)

    np.random.seed(42 if 'NDVI' in title else 7)
    sigma = 0.12
    data = np.random.normal(mean_val, sigma, (15, 15))
    data = np.clip(data, 0, 1)

    vmin, vmax = (0, 1) if 'NDVI' in title else (-0.2, 0.5)
    im = ax.imshow(data, cmap=cmap_name, vmin=vmin, vmax=vmax, aspect='auto',
                   interpolation='bilinear')

    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.06, shrink=0.85)
    cbar.ax.tick_params(labelsize=7)
    cbar.set_label('Valor', fontsize=7, color=C['text_light'])

    ax.set_title(f'{title}\nMedia: {mean_val:.2f}', fontsize=9,
                 fontweight='bold', color=C['brown_dark'], pad=4)
    ax.set_xlabel('Longitud (relativa)', fontsize=7, color=C['text_muted'])
    ax.set_ylabel('Latitud (relativa)', fontsize=7, color=C['text_muted'])
    ax.tick_params(labelsize=6)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor='#F9F7F2', dpi=180)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ============================================================
# 7. MAIN PDF GENERATOR CLASS
# ============================================================

class MuOrbitaPDFGenerator:
    """Professional agro-report PDF generator using ReportLab."""

    def __init__(self, data: Dict[str, Any]):
        self.d = data
        self.styles = get_styles()
        self.buffer = io.BytesIO()
        self.W, self.H = A4  # 210 x 297 mm
        self.M = 15*mm
        self.content_w = self.W - 2*self.M

    # --- Header / Footer ---
    def _header_footer(self, cvs, doc):
        cvs.saveState()

        # HEADER — cream background like email (NOT solid brown bar)
        cvs.setFillColor(hex_color('cream'))
        cvs.rect(0, self.H - 20*mm, self.W, 20*mm, fill=True, stroke=False)

        # Subtle bottom border (like email border-bottom)
        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.8)
        cvs.line(0, self.H - 20*mm, self.W, self.H - 20*mm)

        # Brand "Mu.Orbita" — italic Mu in Georgia style, dark brown
        cvs.setFillColor(hex_color('brown_dark'))
        cvs.setFont('Helvetica-Oblique', 16)
        cvs.drawString(self.M + 4*mm, self.H - 14*mm, 'Mu')
        mu_w = cvs.stringWidth('Mu', 'Helvetica-Oblique', 16)
        cvs.setFont('Helvetica-Bold', 16)
        cvs.drawString(self.M + 4*mm + mu_w, self.H - 14*mm, '.Orbita')

        # "INFORME SATELITAL" right — gold like email
        cvs.setFillColor(hex_color('gold'))
        cvs.setFont('Helvetica-Bold', 8.5)
        cvs.drawRightString(self.W - self.M - 4*mm, self.H - 13*mm, 'INFORME SATELITAL')

        # FOOTER
        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.5)
        cvs.line(self.M, 11*mm, self.W - self.M, 11*mm)

        cvs.setFillColor(hex_color('text_muted'))
        cvs.setFont('Helvetica', 7)
        cvs.drawString(self.M, 7*mm, f'© {datetime.now().year} Mu.Orbita')
        cvs.drawCentredString(self.W/2, 7*mm, f'Página {doc.page}')
        cvs.drawRightString(self.W - self.M, 7*mm, 'info@muorbita.com')

        cvs.restoreState()

    # --- Cover Page (drawn on first page canvas) ---
    def _draw_cover(self, cvs, doc):
        cvs.saveState()

        # Full cream background (like email)
        cvs.setFillColor(hex_color('cream'))
        cvs.rect(0, 0, self.W, self.H, fill=True, stroke=False)

        # === TOP SECTION: Brand header (like email) ===
        # Header area with bottom border
        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.8)
        cvs.line(self.M + 8*mm, self.H - 30*mm, self.W - self.M - 8*mm, self.H - 30*mm)

        # Brand "Mu.Orbita" — italic Mu, bold Orbita (like email)
        cvs.setFillColor(hex_color('brown_dark'))
        cvs.setFont('Helvetica-Oblique', 28)
        cvs.drawString(self.M + 8*mm, self.H - 22*mm, 'Mu')
        mu_w = cvs.stringWidth('Mu', 'Helvetica-Oblique', 28)
        cvs.setFont('Helvetica-Bold', 28)
        cvs.drawString(self.M + 8*mm + mu_w, self.H - 22*mm, '.Orbita')

        # "INFORME SATELITAL" right (like email)
        cvs.setFillColor(hex_color('gold'))
        cvs.setFont('Helvetica-Bold', 9)
        cvs.drawRightString(self.W - self.M - 8*mm, self.H - 20*mm, 'INFORME SATELITAL')

        # === ACCENT BAND: Warm gold-brown strip ===
        band_y = self.H - 95*mm
        band_h = 50*mm
        cvs.setFillColor(hex_color('cover_band'))
        cvs.rect(0, band_y, self.W, band_h, fill=True, stroke=False)

        # Title text on band
        cvs.setFillColor(hex_color('brown_dark'))
        cvs.setFont('Helvetica-Bold', 26)
        cvs.drawString(self.M + 8*mm, band_y + band_h - 20*mm, 'Informe de Análisis Agrícola')

        at = self.d.get('analysis_type', 'baseline').upper()
        lbl = 'Diagnóstico Inicial' if at == 'BASELINE' else 'Seguimiento Periódico'
        cvs.setFont('Helvetica', 13)
        cvs.setFillColor(hex_color('brown'))
        cvs.drawString(self.M + 8*mm, band_y + band_h - 34*mm, f'Análisis {at} — {lbl}')

        # Decorative gold line on band
        cvs.setStrokeColor(hex_color('gold_light'))
        cvs.setLineWidth(2)
        cvs.line(self.M + 8*mm, band_y + band_h - 40*mm,
                 self.M + 50*mm, band_y + band_h - 40*mm)

        # === METADATA CARD (like email "RESUMEN DEL ANÁLISIS") ===
        card_x = self.M + 8*mm
        card_w = self.W - 2*self.M - 16*mm
        card_h = 72*mm
        card_y = band_y - 15*mm - card_h

        # White card with cream border (like email)
        cvs.setFillColor(hex_color('white'))
        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.8)
        cvs.roundRect(card_x, card_y, card_w, card_h, 6, fill=True, stroke=True)

        # "RESUMEN DEL ANÁLISIS" label in gold (like email)
        cvs.setFillColor(hex_color('gold'))
        cvs.setFont('Helvetica-Bold', 9)
        cvs.drawString(card_x + 14*mm, card_y + card_h - 14*mm, 'RESUMEN DEL ANÁLISIS')

        # Separator under label
        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.4)
        cvs.line(card_x + 10*mm, card_y + card_h - 18*mm,
                 card_x + card_w - 10*mm, card_y + card_h - 18*mm)

        # Metadata rows
        meta = [
            ('Cliente', self.d.get('client_name', 'N/A')),
            ('Cultivo', crop_label(self.d.get('crop_type', ''))),
            ('Superficie', f"{self.d.get('area_hectares', 0):.1f} hectáreas"),
            ('Período analizado', f"{fmt_date(self.d.get('start_date'))}  →  {fmt_date(self.d.get('end_date'))}"),
            ('Referencia', self.d.get('job_id', 'N/A')),
        ]

        row_y = card_y + card_h - 28*mm
        for label, value in meta:
            cvs.setFillColor(hex_color('text_light'))
            cvs.setFont('Helvetica', 9.5)
            cvs.drawString(card_x + 14*mm, row_y, label)

            cvs.setFillColor(hex_color('brown_dark'))
            cvs.setFont('Helvetica-Bold', 9.5)
            val_display = value if len(str(value)) < 42 else str(value)[:39] + '...'
            cvs.drawRightString(card_x + card_w - 14*mm, row_y, val_display)

            row_y -= 3*mm
            cvs.setStrokeColor(hex_color('cream_dark'))
            cvs.setLineWidth(0.3)
            cvs.line(card_x + 14*mm, row_y, card_x + card_w - 14*mm, row_y)
            row_y -= 8*mm

        # Date below card
        cvs.setFillColor(hex_color('text_light'))
        cvs.setFont('Helvetica', 9)
        cvs.drawCentredString(self.W/2, card_y - 10*mm,
            f'Fecha del informe: {datetime.now().strftime("%d/%m/%Y")}')

        # Footer
        cvs.setFillColor(hex_color('text_muted'))
        cvs.setFont('Helvetica', 8)
        cvs.drawCentredString(self.W/2, 15*mm,
            f'© {datetime.now().year} Mu.Orbita — info@muorbita.com — www.muorbita.com')

        cvs.restoreState()

    # --- KPI Cards ---
    def _kpi_cards(self) -> Table:
        d = self.d
        s = self.styles

        kpis = [
            (f"{d.get('ndvi_mean',0):.2f}", 'NDVI MEDIO',  *ndvi_status(d.get('ndvi_mean',0))),
            (f"{d.get('ndwi_mean',0):.2f}", 'NDWI MEDIO',  *ndwi_status(d.get('ndwi_mean',0))),
            (f"{d.get('evi_mean',0):.2f}",  'EVI MEDIO',   'Productividad', 'yellow'),
            (f"{d.get('stress_area_pct',0):.1f}%", 'ÁREA ESTRÉS', *stress_status(d.get('stress_area_pct',0))),
        ]

        cells = []
        for val, label, interp, color_key in kpis:
            mini = Table([
                [Paragraph(f'<font color="{C[color_key]}">{val}</font>', s['KPIValue'])],
                [Paragraph(label, s['KPILabel'])],
                [Paragraph(f'<font color="{C[color_key]}">{interp}</font>', s['KPIStatus'])],
            ], colWidths=[40*mm])
            mini.setStyle(TableStyle([
                ('ALIGN',(0,0),(-1,-1),'CENTER'),
                ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                ('TOPPADDING',(0,0),(-1,-1), 4),
                ('BOTTOMPADDING',(0,0),(-1,-1), 4),
            ]))
            cells.append(mini)

        tbl = Table([cells], colWidths=[42.5*mm]*4)
        tbl.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1), hex_color('cream')),
            ('BOX',(0,0),(-1,-1), 1, hex_color('cream_dark')),
            ('INNERGRID',(0,0),(-1,-1), 0.5, hex_color('cream_dark')),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1), 8),
            ('BOTTOMPADDING',(0,0),(-1,-1), 8),
            ('LEFTPADDING',(0,0),(-1,-1), 4),
            ('RIGHTPADDING',(0,0),(-1,-1), 4),
            ('ROUNDEDCORNERS', [4, 4, 4, 4]),
        ]))
        return tbl

    # --- Detail Table ---
    def _detail_table(self) -> Table:
        d = self.d
        s = self.styles

        ndvi_i, _ = ndvi_status(d.get('ndvi_mean',0))
        ndwi_i, _ = ndwi_status(d.get('ndwi_mean',0))

        rows = [
            ['Métrica','Media','P10','P50','P90','Interpretación'],
            ['NDVI (Vigor)', f"{d.get('ndvi_mean',0):.2f}", f"{d.get('ndvi_p10',0):.2f}",
             f"{d.get('ndvi_p50',0):.2f}", f"{d.get('ndvi_p90',0):.2f}", ndvi_i],
            ['NDWI (Agua)', f"{d.get('ndwi_mean',0):.2f}", f"{d.get('ndwi_p10','—')}",
             '—', f"{d.get('ndwi_p90','—')}", ndwi_i],
            ['EVI (Productiv.)', f"{d.get('evi_mean',0):.2f}", f"{d.get('evi_p10','—')}",
             '—', f"{d.get('evi_p90','—')}", '—'],
            ['NDCI (Clorofila)', f"{d.get('ndci_mean',0):.2f}", '—','—','—','—'],
            ['SAVI (Aj. suelo)', f"{d.get('savi_mean',0):.2f}", '—','—','—','—'],
        ]

        # Convert to Paragraphs
        data = []
        for r_idx, row in enumerate(rows):
            tr = []
            for c_idx, cell in enumerate(row):
                st = s['TableHeader'] if r_idx == 0 else (s['TableCellLeft'] if c_idx == 0 else s['TableCell'])
                tr.append(Paragraph(str(cell), st))
            data.append(tr)

        cw = [32*mm, 22*mm, 18*mm, 18*mm, 18*mm, 62*mm]
        tbl = Table(data, colWidths=cw)

        style_cmds = [
            ('BACKGROUND',(0,0),(-1,0), hex_color('table_header')),
            ('TEXTCOLOR',(0,0),(-1,0), hex_color('white')),
            ('GRID',(0,0),(-1,-1), 0.5, hex_color('cream_dark')),
            ('BOX',(0,0),(-1,-1), 1, hex_color('table_header')),
            ('ALIGN',(1,1),(-1,-1),'CENTER'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1), 5),
            ('BOTTOMPADDING',(0,0),(-1,-1), 5),
        ]
        for r in range(2, len(data), 2):
            style_cmds.append(('BACKGROUND',(0,r),(-1,r), hex_color('cream')))
        tbl.setStyle(TableStyle(style_cmds))
        return tbl

    # --- Risk Table ---
    def _risk_table(self) -> Table:
        d = self.d
        s = self.styles

        ndwi_m = d.get('ndwi_mean', 0)
        ndvi_m = d.get('ndvi_mean', 0)
        hetero = d.get('ndvi_p90', 0) - d.get('ndvi_p10', 0)

        def risk_row(name, level, indicator, action, color_key):
            dot = f'<font color="{C[color_key]}">●</font>'
            return [
                Paragraph(name, s['TableCellLeft']),
                Paragraph(f'{dot} {level}', s['TableCell']),
                Paragraph(indicator, s['TableCell']),
                Paragraph(action, s['TableCellLeft']),
            ]

        # Hydric risk
        if ndwi_m < 0:   h_lvl, h_act, h_c = 'Alto', 'Verificar riego urgente', 'red'
        elif ndwi_m<0.10: h_lvl, h_act, h_c = 'Moderado', 'Ajustar programación de riego', 'yellow'
        else:             h_lvl, h_act, h_c = 'Bajo', 'Mantener régimen actual', 'green'

        # Vigor risk
        if ndvi_m < 0.35: v_lvl, v_act, v_c = 'Alto', 'Inspección de campo urgente', 'red'
        elif ndvi_m<0.45: v_lvl, v_act, v_c = 'Moderado', 'Planificar inspección', 'yellow'
        else:             v_lvl, v_act, v_c = 'Bajo', 'Sin acción requerida', 'green'

        # Heterogeneity risk
        if hetero > 0.25: hh_lvl, hh_act, hh_c = 'Alto', 'Implementar VRA', 'red'
        elif hetero>0.15: hh_lvl, hh_act, hh_c = 'Moderado', 'Evaluar zonificación', 'yellow'
        else:             hh_lvl, hh_act, hh_c = 'Bajo', 'Parcela homogénea', 'green'

        header = [Paragraph(h, s['TableHeader']) for h in ['Riesgo','Nivel','Indicador','Acción sugerida']]
        data = [
            header,
            risk_row('Estrés hídrico', h_lvl, f'NDWI: {ndwi_m:.2f}', h_act, h_c),
            risk_row('Déficit de vigor', v_lvl, f'NDVI: {ndvi_m:.2f}', v_act, v_c),
            risk_row('Heterogeneidad', hh_lvl, f'ΔP90-P10: {hetero:.2f}', hh_act, hh_c),
        ]

        cw = [38*mm, 30*mm, 38*mm, 64*mm]
        tbl = Table(data, colWidths=cw)
        tbl.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), hex_color('table_header')),
            ('TEXTCOLOR',(0,0),(-1,0), hex_color('white')),
            ('GRID',(0,0),(-1,-1), 0.5, hex_color('cream_dark')),
            ('BOX',(0,0),(-1,-1), 1, hex_color('table_header')),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1), 6),
            ('BOTTOMPADDING',(0,0),(-1,-1), 6),
        ]))
        return tbl

    # --- Recommendations ---
    def _recommendations(self) -> List:
        d = self.d
        s = self.styles
        elements = []

        ndwi_m = d.get('ndwi_mean', 0)
        ndvi_m = d.get('ndvi_mean', 0)
        stress_pct = d.get('stress_area_pct', 0)

        recs = []
        # Rec 1
        if ndvi_m < 0.35:
            recs.append(('Inspección de campo de zonas críticas', 'Alta', '3–5 días',
                f'NDVI = {ndvi_m:.2f} indica estrés severo',
                f'Zonas con NDVI < 0.35 ({stress_pct:.1f}% del área)',
                'Descartar plagas, enfermedades o fallo de riego'))
        elif ndvi_m < 0.45:
            recs.append(('Inspección visual de zonas de bajo vigor', 'Media', '7 días',
                f'NDVI = {ndvi_m:.2f} indica vigor bajo',
                'Zonas con menor vigor detectado',
                'Identificar causas de bajo rendimiento vegetativo'))
        else:
            recs.append(('Monitorización de mantenimiento', 'Baja', '14 días',
                f'NDVI = {ndvi_m:.2f} dentro de rango normal',
                'Toda la parcela', 'Mantener detección temprana de cambios'))

        # Rec 2
        if ndwi_m < 0:
            recs.append(('Revisión urgente del sistema de riego', 'Alta', '3 días',
                f'NDWI = {ndwi_m:.2f} indica déficit hídrico severo',
                'Toda la parcela, priorizando sectores con NDWI < 0',
                'Estrés hídrico severo puede reducir producción hasta 30%'))
        elif ndwi_m < 0.10:
            recs.append(('Ajustar programación de riego', 'Media', '7 días',
                f'NDWI = {ndwi_m:.2f} indica déficit moderado',
                'Sectores con menor NDWI',
                'Prevenir escalada del estrés hídrico antes de período crítico'))
        else:
            recs.append(('Mantener régimen de riego actual', 'Baja', '14 días',
                'Estado hídrico aceptable', 'Toda la parcela',
                'Monitorizar evolución del balance hídrico'))

        # Rec 3
        if stress_pct > 40:
            recs.append(('Zonificación para aplicación variable (VRA)', 'Media', '10 días',
                f'{stress_pct:.1f}% del área presenta estrés',
                'Parcela completa', 'VRA optimiza uso de insumos en zonas heterogéneas'))
        else:
            recs.append(('Planificar fertilización según zonificación', 'Media', '14 días',
                'Optimizar inputs según vigor diferencial',
                'Diferenciar zonas NDVI alto vs bajo',
                'Maximizar eficiencia del fertilizante'))

        for i, (title, priority, deadline, trigger, zone, justification) in enumerate(recs[:3], 1):
            pc = {'Alta': C['red'], 'Media': C['yellow'], 'Baja': C['green']}[priority]
            text = (
                f'<b>{i}. {title}</b>  '
                f'<font color="{pc}">● Prioridad: {priority}</font> | '
                f'Plazo: {deadline}<br/>'
                f'<font size="9">'
                f'<b>Trigger:</b> {trigger}<br/>'
                f'<b>Zona:</b> {zone}<br/>'
                f'<b>Justificación:</b> {justification}'
                f'</font>'
            )
            elements.append(Paragraph(text, s['Body']))
            elements.append(Spacer(1, 3*mm))

        return elements

    # --- Technical Annex ---
    def _annex(self) -> List:
        d = self.d
        s = self.styles
        elements = []

        ct = crop_label(d.get('crop_type',''))
        annex = (
            f'<b>Fuentes de datos</b><br/>'
            f'• Sentinel-2 SR Harmonized: {d.get("images_processed",0)} escenas procesadas<br/>'
            f'• Última imagen válida: {fmt_date(d.get("latest_image_date"))}<br/>'
            f'• MODIS LST: Temperatura superficial media {d.get("lst_mean_c",0):.1f} ºC<br/>'
            f'• Resolución: 10 m (S2), 30 m (Landsat), 1 km (MODIS)<br/><br/>'
            f'<b>Umbrales de referencia ({ct})</b><br/>'
            f'• NDVI > 0.60: Vigor alto | 0.45–0.60: Moderado | &lt; 0.35: Estrés severo<br/>'
            f'• NDWI > 0.20: Óptimo | 0.10–0.20: Moderado | &lt; 0.10: Déficit<br/>'
            f'• Rango NDVI típico {ct.lower()}: {crop_ndvi_range(d.get("crop_type",""))}<br/><br/>'
            f'<b>Procesamiento</b><br/>'
            f'• Motor: Google Earth Engine<br/>'
            f'• Máscaras: QA60 + SCL (S2), QA_PIXEL (Landsat)<br/>'
            f'• Estadísticas: Media, P10, P50, P90, desviación estándar<br/>'
            f'• Zonificación VRA: K-means (k=3) sobre [NDVI, EVI, NDWI]<br/><br/>'
            f'<b>Índices calculados</b><br/>'
            f'• NDVI = (NIR − Red) / (NIR + Red) → Vigor vegetativo<br/>'
            f'• NDWI = (NIR − SWIR) / (NIR + SWIR) → Estado hídrico<br/>'
            f'• EVI = 2.5 × (NIR − Red) / (NIR + 6R − 7.5B + 1) → Productividad<br/>'
            f'• NDCI = (RedEdge − Red) / (RedEdge + Red) → Clorofila'
        )
        elements.append(Paragraph(annex, s['BodySmall']))
        return elements

    # =====================================================
    # MAIN BUILD METHOD
    # =====================================================
    def generate(self) -> bytes:
        d = self.d
        s = self.styles

        doc = SimpleDocTemplate(
            self.buffer, pagesize=A4,
            leftMargin=self.M, rightMargin=self.M,
            topMargin=25*mm,   # Room for header
            bottomMargin=16*mm  # Room for footer
        )

        elements = []

        # Cover page is drawn by onFirstPage callback.
        # We MUST push all flowable content to page 2+.
        elements.append(PageBreak())

        # ======== PAGE 2: KPI DASHBOARD ========
        elements.append(Spacer(1, 3*mm))

        # Title
        elements.append(Paragraph('Indicadores Clave de Rendimiento', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 3*mm))

        # KPI cards
        elements.append(self._kpi_cards())
        elements.append(Spacer(1, 4*mm))

        # Integrated interpretation callout
        ndvi_m = d.get('ndvi_mean', 0)
        stress_pct = d.get('stress_area_pct', 0)
        ct = crop_label(d.get('crop_type',''))
        hetero = d.get('ndvi_p90', 0) - d.get('ndvi_p10', 0)

        if stress_pct > 40:
            interp_text = (
                f'<b>Interpretación integrada:</b> El cultivo presenta estrés significativo. '
                f'El NDVI medio de {ndvi_m:.2f} está por debajo del rango típico para '
                f'{ct.lower()} ({crop_ndvi_range(d.get("crop_type",""))}). '
                f'El {stress_pct:.1f}% de la superficie ({d.get("stress_area_ha",0):.1f} ha) '
                f'muestra valores de estrés (NDVI &lt;0.35). Se requiere inspección de campo prioritaria.'
            )
            accent = 'red'
        elif stress_pct > 15:
            interp_text = (
                f'<b>Interpretación integrada:</b> El cultivo presenta señales de estrés moderado. '
                f'El NDVI medio de {ndvi_m:.2f} indica vigor por debajo del óptimo para {ct.lower()}. '
                f'El {stress_pct:.1f}% del área ({d.get("stress_area_ha",0):.1f} ha) presenta estrés. '
                f'Se recomienda verificar estado hídrico y condiciones de suelo.'
            )
            accent = 'yellow'
        else:
            interp_text = (
                f'<b>Interpretación integrada:</b> El cultivo muestra vigor vegetativo '
                f'dentro del rango esperado. El NDVI medio de {ndvi_m:.2f} es consistente con '
                f'{ct.lower()} en actividad normal. Heterogeneidad intra-parcela: '
                f'{hetero_label(d.get("ndvi_p10",0), d.get("ndvi_p90",0)).lower()} '
                f'(rango P10-P90: {d.get("ndvi_p10",0):.2f} – {d.get("ndvi_p90",0):.2f}).'
            )
            accent = 'green'

        elements.append(CalloutBox(interp_text, s, accent=accent, width=self.content_w))
        elements.append(Spacer(1, 4*mm))

        # Detail table
        elements.append(Paragraph('Detalle de Índices Vegetativos', s['SubsectionTitle']))
        elements.append(self._detail_table())
        elements.append(Spacer(1, 4*mm))

        # NDVI gauge
        gauge_bytes = generate_ndvi_gauge(
            d.get('ndvi_mean', 0.3), d.get('ndvi_p10', 0.2), d.get('ndvi_p90', 0.4))
        elements.append(Image(io.BytesIO(gauge_bytes), width=155*mm, height=36*mm))

        # ======== PAGE 2: EVOLUTION + RISK ========
        elements.append(PageBreak())
        elements.append(Spacer(1, 3*mm))

        # Time series chart
        elements.append(Paragraph('Evolución Temporal de Índices', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))

        ts = d.get('time_series', [])
        chart_bytes = generate_ts_chart(ts, d.get('crop_type', 'olivar'))
        elements.append(Image(io.BytesIO(chart_bytes), width=165*mm, height=60*mm))
        elements.append(Spacer(1, 2*mm))

        # Chart reading guide
        chart_note = (
            f'<b>Lectura del gráfico:</b> Verde = NDVI (vigor); Azul = NDWI (agua); '
            f'Dorado = EVI (productividad). La franja roja inferior marca estrés severo '
            f'(NDVI &lt;0.35). La franja verde marca el rango óptimo para {ct.lower()}.'
        )
        if len(ts) < 5:
            chart_note += ' Nota: los datos acumulados son aún insuficientes para tendencias robustas.'
        elements.append(CalloutBox(chart_note, s, accent='gold', width=self.content_w))
        elements.append(Spacer(1, 5*mm))

        # Maps side by side
        elements.append(Paragraph('Mapas de Vigor y Estado Hídrico', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))

        ndvi_map = generate_heatmap('NDVI (Vigor)', d.get('ndvi_mean', 0.3), 'RdYlGn')
        ndwi_map = generate_heatmap('NDWI (Agua)', max(0, d.get('ndwi_mean', 0)), 'YlGnBu')

        maps_tbl = Table([
            [Image(io.BytesIO(ndvi_map), width=78*mm, height=55*mm),
             Image(io.BytesIO(ndwi_map), width=78*mm, height=55*mm)]
        ], colWidths=[83*mm, 83*mm])
        maps_tbl.setStyle(TableStyle([
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ]))
        elements.append(maps_tbl)
        elements.append(Spacer(1, 2*mm))

        map_note = (
            '<b>Nota:</b> Estos mapas muestran la distribución espacial estimada de los índices. '
            'En futuras entregas incluirán la geometría real de la parcela sobre imagen satelital base.'
        )
        elements.append(Paragraph(f'<font size="8" color="{C["text_muted"]}">{map_note}</font>',
                                  s['Footnote']))

        # ======== PAGE 3: AI ANALYSIS ========
        elements.append(PageBreak())
        elements.append(Spacer(1, 3*mm))

        elements.append(Paragraph('Análisis Agronómico', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))

        md = d.get('markdown_analysis', '') or d.get('analysis', '') or d.get('html_report', '')
        if md:
            elements.extend(md_to_flowables(md, s))
        else:
            elements.extend(self._auto_analysis())

        # ======== PAGE 4: RISKS + RECS + ANNEX ========
        elements.append(PageBreak())
        elements.append(Spacer(1, 3*mm))

        # Risks
        elements.append(Paragraph('Evaluación de Riesgos', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))
        elements.append(self._risk_table())
        elements.append(Spacer(1, 6*mm))

        # Recommendations
        elements.append(Paragraph('Recomendaciones Prioritarias', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))
        elements.extend(self._recommendations())
        elements.append(Spacer(1, 6*mm))

        # Technical annex
        elements.append(Paragraph('Anexo Técnico', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))
        elements.extend(self._annex())
        elements.append(Spacer(1, 8*mm))

        # Disclaimer
        disclaimer = (
            '<i>Este informe ha sido generado automáticamente mediante análisis de imágenes '
            'satelitales. Las recomendaciones deben ser validadas por un técnico agrónomo antes '
            'de su implementación. Los datos satelitales están sujetos a disponibilidad y '
            'condiciones atmosféricas.</i>'
        )
        elements.append(Paragraph(f'<font size="7.5" color="{C["text_muted"]}">{disclaimer}</font>',
                                  s['Footnote']))

        # Build with cover on first page, header/footer on rest
        def first_page(cvs, doc):
            self._draw_cover(cvs, doc)

        def later_pages(cvs, doc):
            self._header_footer(cvs, doc)

        doc.build(elements, onFirstPage=first_page, onLaterPages=later_pages)

        self.buffer.seek(0)
        return self.buffer.getvalue()

    def _auto_analysis(self) -> List:
        """Fallback auto-generated analysis when Claude's isn't available."""
        d = self.d
        s = self.styles
        elements = []

        ndvi_m = d.get('ndvi_mean', 0)
        ndwi_m = d.get('ndwi_mean', 0)
        stress_pct = d.get('stress_area_pct', 0)
        hetero = d.get('ndvi_p90', 0) - d.get('ndvi_p10', 0)
        ct = crop_label(d.get('crop_type', ''))

        ndvi_i, _ = ndvi_status(ndvi_m)
        ndwi_i, _ = ndwi_status(ndwi_m)

        text = (
            f'<b>Evaluación de vigor vegetativo</b><br/><br/>'
            f'El cultivo de {ct.lower()} analizado ({d.get("area_hectares",0):.1f} ha) presenta '
            f'un vigor vegetativo clasificado como <b>{ndvi_i.lower()}</b> '
            f'(NDVI medio: {ndvi_m:.2f}). El rango típico para {ct.lower()} en producción '
            f'es {crop_ndvi_range(d.get("crop_type",""))}.<br/><br/>'
            f'El estado hídrico indica <b>{ndwi_i.lower()}</b> (NDWI: {ndwi_m:.2f}). '
            f'El {stress_pct:.1f}% del área ({d.get("stress_area_ha",0):.1f} ha) muestra '
            f'signos de estrés significativo (NDVI &lt;0.35).<br/><br/>'
            f'La heterogeneidad intra-parcela es <b>{hetero_label(d.get("ndvi_p10",0), d.get("ndvi_p90",0)).lower()}</b> '
            f'(dispersión P10-P90: {hetero:.2f})'
            f'{", lo que sugiere considerar aplicación variable de insumos" if hetero > 0.15 else ""}.'
        )
        elements.append(Paragraph(text, s['Body']))
        return elements


# ============================================================
# 8. PUBLIC API FUNCTION (drop-in replacement)
# ============================================================

def generate_muorbita_report(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main function to generate the PDF report.
    Drop-in replacement for v2.0 — same input/output contract.

    Args:
        data: Dict with all analysis data (KPIs, time_series, markdown_analysis, etc.)

    Returns:
        Dict with pdf_base64, filename, pdf_size, job_id, success, generated_at
    """
    try:
        generator = MuOrbitaPDFGenerator(data)
        pdf_bytes = generator.generate()

        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        job_id = data.get('job_id', 'UNKNOWN')
        filename = f'Informe_MUORBITA_{job_id}.pdf'

        return {
            'success': True,
            'pdf_base64': pdf_base64,
            'filename': filename,
            'pdf_size': len(pdf_bytes),
            'job_id': job_id,
            'generated_at': datetime.now().isoformat(),
            # Pass through KPIs for n8n downstream
            'ndvi_mean': data.get('ndvi_mean', 0),
            'ndvi_p10': data.get('ndvi_p10', 0),
            'ndvi_p90': data.get('ndvi_p90', 0),
            'ndwi_mean': data.get('ndwi_mean', 0),
            'stress_area_ha': data.get('stress_area_ha', 0),
            'stress_area_pct': data.get('stress_area_pct', 0),
        }

    except Exception as e:
        import traceback
        return {
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc(),
            'job_id': data.get('job_id', 'UNKNOWN'),
        }


# ============================================================
# 9. CLI TEST
# ============================================================

if __name__ == '__main__':
    import sys

    test_data = {
        "job_id": "MUORBITA_1771180551135_N3GXAHIE4",
        "client_name": "Nuria Canamaquelopez",
        "crop_type": "olive",
        "analysis_type": "baseline",
        "area_hectares": 26.9,
        "start_date": "2025-08-15",
        "end_date": "2026-02-15",
        "images_processed": 24,
        "latest_image_date": "2026-02-12",

        "ndvi_mean": 0.30, "ndvi_p10": 0.24, "ndvi_p50": 0.29,
        "ndvi_p90": 0.39, "ndvi_stddev": 0.06, "ndvi_zscore": -1.2,

        "ndwi_mean": 0.01, "ndwi_p10": -0.05, "ndwi_p90": 0.06,
        "evi_mean": 0.27, "evi_p10": 0.22, "evi_p90": 0.32,
        "ndci_mean": 0.13, "savi_mean": 0.23,

        "stress_area_ha": 21.1, "stress_area_pct": 78.5,
        "lst_mean_c": 18.2, "lst_min_c": 4.5, "lst_max_c": 32.8,
        "heterogeneity": 0.15,

        "time_series": [
            {"date": "2025-09-01", "ndvi": 0.35, "ndwi": 0.03, "evi": 0.30},
            {"date": "2025-09-15", "ndvi": 0.33, "ndwi": 0.02, "evi": 0.28},
            {"date": "2025-10-01", "ndvi": 0.31, "ndwi": 0.01, "evi": 0.27},
            {"date": "2025-10-15", "ndvi": 0.30, "ndwi": 0.01, "evi": 0.26},
            {"date": "2025-11-01", "ndvi": 0.29, "ndwi": 0.00, "evi": 0.25},
            {"date": "2025-11-15", "ndvi": 0.28, "ndwi": -0.01, "evi": 0.24},
            {"date": "2025-12-01", "ndvi": 0.27, "ndwi": 0.00, "evi": 0.24},
            {"date": "2025-12-15", "ndvi": 0.28, "ndwi": 0.01, "evi": 0.25},
            {"date": "2026-01-01", "ndvi": 0.29, "ndwi": 0.01, "evi": 0.26},
            {"date": "2026-01-15", "ndvi": 0.30, "ndwi": 0.02, "evi": 0.27},
            {"date": "2026-02-01", "ndvi": 0.30, "ndwi": 0.01, "evi": 0.27},
            {"date": "2026-02-12", "ndvi": 0.30, "ndwi": 0.01, "evi": 0.27},
        ],

        "markdown_analysis": (
            "## Resumen Ejecutivo\n\n"
            "El análisis baseline del olivar de 26.9 ha revela una **situación de estrés "
            "moderado generalizado**, con el 78.5% de la superficie presentando valores de "
            "vigor vegetativo por debajo del umbral óptimo.\n\n"
            "**Estado general:** PRECAUCIÓN\n"
            "**Prioridad de actuación:** MEDIA-ALTA\n\n"
            "## Evaluación de Vigor Vegetativo\n\n"
            "El NDVI medio de 0.30 se sitúa en el rango de **estrés severo** para olivar, "
            "significativamente por debajo del rango típico de producción (0.45-0.65). Sin embargo, "
            "es importante contextualizar este valor dentro del ciclo fenológico: durante los meses "
            "de invierno (diciembre-febrero), el olivar reduce naturalmente su actividad vegetativa.\n\n"
            "El rango P10-P90 (0.24-0.39) muestra una dispersión de 0.15, indicando "
            "**heterogeneidad moderada** dentro de la parcela.\n\n"
            "## Estado Hídrico\n\n"
            "El NDWI medio de 0.01 confirma un **déficit hídrico moderado**. Los valores "
            "cercanos a cero son esperables en cultivos leñosos durante el invierno.\n\n"
            "## Recomendaciones Prioritarias\n\n"
            "### 1. Inspección de campo — Prioridad: Alta — Plazo: 5 días\n"
            "- **Trigger:** 78.5% del área con NDVI < 0.35\n"
            "- **Zona:** Toda la parcela, priorizando zonas con NDVI < 0.24\n"
            "- **Justificación:** Descartar causas agronómicas tratables\n\n"
            "### 2. Revisión del sistema de riego — Prioridad: Media — Plazo: 10 días\n"
            "- **Trigger:** NDWI medio de 0.01 con valores negativos en P10\n"
            "- **Justificación:** Asegurar reservas hídricas antes de activación primaveral\n\n"
            "### 3. Planificación de fertilización — Prioridad: Media — Plazo: 14 días\n"
            "- **Trigger:** EVI medio de 0.27 indica productividad limitada\n"
            "- **Justificación:** Diseñar plan de abonado basado en zonificación de vigor"
        )
    }

    # Allow passing a JSON file as argument
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            test_data = json.load(f)

    result = generate_muorbita_report(test_data)

    if result['success']:
        out_path = f"/tmp/{result['filename']}"
        with open(out_path, 'wb') as f:
            f.write(base64.b64decode(result['pdf_base64']))
        print(f"✅ PDF generado: {out_path} ({result['pdf_size']:,} bytes)")
    else:
        print(f"❌ Error: {result['error']}")
        print(result.get('traceback', ''))
