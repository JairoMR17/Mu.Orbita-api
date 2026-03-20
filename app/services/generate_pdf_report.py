"""
Mu.Orbita PDF Report Generator v8.2
====================================
Changelog vs v8.1:
───────────────────
FIX:  Chart legend overlap — title removed (redundant with SectionTitle), bbox/rect adjusted
NEW:  VRA map image in _vra_section() when available from GEE
NEW:  VRA section renders in BOTH baseline and biweekly (was baseline-only)
NEW:  _reading_guide() — "Guía de Lectura" for non-technical readers after Annex
NEW:  _signature_block() — professional technical signature + improved disclaimer
NEW:  Cover page includes parcel_name and sigpac_ref when available
NEW:  Delta table header shows date of previous report
IMPROVED: Map note per-index (real vs synthetic) in both report types

Changelog v8.0 vs v7.1:
───────────────────
FIX:  _sanitize_index() captura el bug ×1000 de valores upstream (prev_ndvi=588 → 0.588)
FIX:  _safe_fmt() ya NO trata 0.0 como missing — solo None es fallback
FIX:  fv() en _detail_table — misma corrección: 0.0 es valor válido
FIX:  LST 0.0 ºC en _risk_table → fallback a ERA5 Tmax o "N/D"
FIX:  Página en blanco antes de anexo → CondPageBreak reemplaza PageBreak forzado
FIX:  _delta_table: delta_fmt ya no divide por 0 cuando prev==0; sanitiza valores >2
FIX:  Forecast label siempre dice "7 días" (no depende de days_ahead upstream)
FIX:  _weather_table incluye Tmin media/mínima cuando están disponibles
NEW:  Semáforo de estado general en portada (🟢🟡🔴 + texto)
NEW:  Executive summary bisemanal como lista de bullets (no párrafo)
NEW:  _forecast_table() — tabla estructurada de previsión 7 días
NEW:  Comparativa vs baseline original en _delta_table (fila extra si hay dato)
IMPROVED: Mejor flujo de páginas bisemanal (forecast con clima, no en pág. 2)
IMPROVED: Nota explícita cuando EVI/NDCI usan mapa sintético vs satélite real

Autor: Mu.Orbita
Fecha: 2026-03
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
    Image, PageBreak, KeepTogether, HRFlowable, Flowable,
    CondPageBreak
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
# ============================================================

C = {
    'header':       '#F9F7F2',
    'header_border':'#E6DDD0',
    'brown_dark':   '#3E2B1D',
    'brown':        '#5C4033',
    'gold':         '#9E7E46',
    'gold_light':   '#C4A265',
    'cream':        '#F9F7F2',
    'cream_dark':   '#E6DDD0',
    'white':        '#FFFFFF',
    'bg_light':     '#FEFCF9',
    'text':         '#3E2B1D',
    'text_light':   '#7A7A7A',
    'text_muted':   '#AAAAAA',
    'green':        '#4B7F3A',
    'green_bg':     '#E8F0E4',
    'yellow':       '#B8860B',
    'yellow_bg':    '#FFF8E7',
    'red':          '#A63D2F',
    'red_bg':       '#FDEDEC',
    'chart_ndvi':   '#4B7F3A',
    'chart_ndwi':   '#3B7DD8',
    'chart_evi':    '#C4A265',
    'cover_band':   '#EDE6DA',
    'table_header': '#8B7B62',
}

def hex_color(key):
    return colors.HexColor(C[key])


# ============================================================
# 2. CUSTOM STYLES
# ============================================================

def get_styles():
    base = getSampleStyleSheet()

    def _add(name, **kw):
        if name in [s.name for s in base.byName.values()]:
            return
        parent = kw.pop('parent', 'Normal')
        base.add(ParagraphStyle(name, parent=base[parent], **kw))

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
    _add('SectionTitle',  fontName='Helvetica-Bold', fontSize=14,
         textColor=hex_color('brown_dark'), spaceBefore=8*mm, spaceAfter=4*mm,
         borderPadding=(0, 0, 2, 0))
    _add('SubsectionTitle', fontName='Helvetica-Bold', fontSize=11,
         textColor=hex_color('brown'), spaceBefore=5*mm, spaceAfter=3*mm)
    _add('Body',          fontName='Helvetica', fontSize=10,
         textColor=hex_color('text'), leading=15, alignment=TA_JUSTIFY, spaceAfter=3*mm)
    _add('BodySmall',     fontName='Helvetica', fontSize=9,
         textColor=hex_color('text'), leading=13, spaceAfter=2*mm)
    _add('BodySmallItalic', fontName='Helvetica-Oblique', fontSize=8.5,
         textColor=hex_color('text_light'), leading=12, spaceAfter=2*mm)
    _add('BulletBody',    fontName='Helvetica', fontSize=9.5,
         textColor=hex_color('text'), leading=14, spaceAfter=1.5*mm,
         leftIndent=6*mm, bulletIndent=2*mm)
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
    _add('TableCellWrap', fontName='Helvetica', fontSize=8.5,
         textColor=hex_color('text'), alignment=TA_LEFT, leading=12)
    _add('MapCaption',    fontName='Helvetica-Oblique', fontSize=8.5,
         textColor=hex_color('brown'), leading=12, alignment=TA_JUSTIFY,
         spaceBefore=1*mm, spaceAfter=1*mm)

    return base


# ============================================================
# 3. INTERPRETATION & SANITIZATION FUNCTIONS
# ============================================================

def _sanitize_index(val, name: str = '') -> Optional[float]:
    """
    v8.0: Sanitiza valores de índices vegetativos.
    Detecta el bug ×1000 de upstream (p.ej. prev_ndvi=588 → 0.588).
    NDVI, NDWI, EVI, SAVI, NDCI siempre están en rango [-1, 1].
    """
    if val is None:
        return None
    try:
        v = float(val)
    except (ValueError, TypeError):
        return None
    # Detectar valores ×1000 — índices nunca exceden ±2
    idx_names = ['ndvi', 'ndwi', 'evi', 'savi', 'ndci']
    if any(n in name.lower() for n in idx_names):
        if abs(v) > 2.0:
            v = v / 1000.0
    return v


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
         'vineyard':'Viñedo','viña':'Viñedo','vid':'Viñedo','viñedo':'Viñedo',
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

def _safe_fmt(val, decimals=1, suffix='', fallback='N/A'):
    """
    v8.0 FIX: Format numérico seguro.
    Solo None es fallback — 0.0 ES un valor válido.
    """
    if val is None:
        return fallback
    try:
        return f"{float(val):.{decimals}f}{suffix}"
    except (ValueError, TypeError):
        return fallback


def fv(val, decimals=2, fallback='—'):
    """
    v8.0: Format value global — 0.0 ES válido, solo None/missing → fallback.
    """
    if val is None or val == '—' or val == '':
        return fallback
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return fallback


def _calc_general_status(d: Dict) -> str:
    """v8.0: Calcula estado general para semáforo de portada."""
    ndvi_m = d.get('ndvi_mean', 0) or 0
    stress_pct = d.get('stress_area_pct', 0) or 0
    balance = d.get('weather_water_balance')

    if ndvi_m < 0.35 or stress_pct > 30:
        return 'critico'
    if ndvi_m < 0.45 or stress_pct > 15:
        return 'atencion'
    if balance is not None and float(balance) < -50:
        return 'atencion'
    return 'normal'


# ============================================================
# 4. CUSTOM FLOWABLES
# ============================================================

class CalloutBox(Flowable):
    def __init__(self, text, styles, accent='gold', width=170*mm):
        Flowable.__init__(self)
        self.text = text
        self.styles = styles
        self.accent = accent
        self._width = width
        self._para = Paragraph(text, styles['Callout'])
        w, h = self._para.wrap(width - 10*mm, 500*mm)
        self._height = h + 8*mm

    def wrap(self, availWidth, availHeight):
        return self._width, self._height

    def draw(self):
        c = self.canv
        w, h = self._width, self._height
        c.setFillColor(hex_color('cream'))
        c.roundRect(0, 0, w, h, 3, fill=True, stroke=False)
        c.setFillColor(hex_color(self.accent))
        c.rect(0, 0, 3*mm, h, fill=True, stroke=False)
        self._para.wrap(w - 10*mm, h)
        self._para.drawOn(c, 5*mm, 3*mm)


class SectionDivider(Flowable):
    def __init__(self, width=170*mm):
        Flowable.__init__(self)
        self._width = width
    def wrap(self, aw, ah):
        return self._width, 1*mm
    def draw(self):
        self.canv.setStrokeColor(hex_color('gold_light'))
        self.canv.setLineWidth(1.5)
        self.canv.line(0, 0, self._width, 0)


class RecommendationCard(Flowable):
    """Card visual para una recomendación con borde lateral coloreado."""
    def __init__(self, number, title, priority, deadline, trigger, zone,
                 justification, styles, width=170*mm):
        Flowable.__init__(self)
        self.number = number
        self.title = title
        self.priority = priority
        self.deadline = deadline
        self.trigger = trigger
        self.zone = zone
        self.justification = justification
        self.styles = styles
        self._width = width

        pc = {'Alta': C['red'], 'Media': C['gold'], 'Baja': C['green']}.get(priority, C['gold'])
        self.border_color = colors.HexColor(pc)

        text = (
            f'<b>{number}. {title}</b>  '
            f'<font color="{pc}">● Prioridad: {priority}</font> | '
            f'Plazo: {deadline}<br/>'
            f'<font size="9">'
            f'<b>Trigger:</b> {trigger}<br/>'
            f'<b>Zona:</b> {zone}<br/>'
            f'<b>Justificación:</b> {justification}'
            f'</font>'
        )
        self._para = Paragraph(text, styles['Body'])
        w, h = self._para.wrap(width - 10*mm, 500*mm)
        self._height = h + 8*mm

    def wrap(self, availWidth, availHeight):
        return self._width, self._height

    def draw(self):
        c = self.canv
        w, h = self._width, self._height
        c.setFillColor(hex_color('white'))
        c.setStrokeColor(hex_color('cream_dark'))
        c.setLineWidth(0.5)
        c.roundRect(0, 0, w, h, 3, fill=True, stroke=True)
        c.setFillColor(self.border_color)
        c.rect(0, 0, 3*mm, h, fill=True, stroke=False)
        self._para.wrap(w - 10*mm, h)
        self._para.drawOn(c, 5*mm, 3*mm)


class FollowupCard(Flowable):
    """v8.1: Card para seguimiento de recomendación anterior."""
    STATUS_CONFIG = {
        'Completada':    {'color': '#4B7F3A', 'icon': '✓'},
        'En curso':      {'color': '#B8860B', 'icon': '⟳'},
        'No iniciada':   {'color': '#A63D2F', 'icon': '✗'},
        'No evaluable':  {'color': '#7A7A7A', 'icon': '?'},
    }

    def __init__(self, number, title, status_label, observed_result,
                 next_step, styles, width=170*mm):
        Flowable.__init__(self)
        self._width = width
        cfg = self.STATUS_CONFIG.get(status_label, self.STATUS_CONFIG['No evaluable'])
        sc = cfg['color']

        text = (
            f'<b>{number}. {title}</b><br/>'
            f'<font size="9">'
            f'<b>Estado:</b> <font color="{sc}"><b>{cfg["icon"]} {status_label}</b></font><br/>'
            f'<b>Resultado observado:</b> {observed_result}<br/>'
            f'<b>Siguiente paso:</b> {next_step}'
            f'</font>'
        )
        self._para = Paragraph(text, styles['Body'])
        w, h = self._para.wrap(width - 10*mm, 500*mm)
        self._height = h + 8*mm
        self.border_color = colors.HexColor(sc)

    def wrap(self, availWidth, availHeight):
        return self._width, self._height

    def draw(self):
        c = self.canv
        w, h = self._width, self._height
        c.setFillColor(hex_color('white'))
        c.setStrokeColor(hex_color('cream_dark'))
        c.setLineWidth(0.5)
        c.roundRect(0, 0, w, h, 3, fill=True, stroke=True)
        c.setFillColor(self.border_color)
        c.rect(0, 0, 3*mm, h, fill=True, stroke=False)
        self._para.wrap(w - 10*mm, h)
        self._para.drawOn(c, 5*mm, 3*mm)


# ============================================================
# 5. CHART GENERATION (matplotlib, corporate palette)
# ============================================================

def _chart_style():
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

    ax.axhspan(0.0, 0.35, alpha=0.06, color=C['red'], zorder=0)
    ax.axhspan(0.45, 0.65, alpha=0.06, color=C['green'], zorder=0)
    ax.axhline(y=0.35, color=C['red'], linestyle='--', linewidth=0.7, alpha=0.4)
    ax.axhline(y=0.60, color=C['green'], linestyle='--', linewidth=0.7, alpha=0.4)

    ax.plot(dates, ndvi, color=C['chart_ndvi'], linewidth=2.2, label='NDVI (Vigor)',
            marker='o', markersize=4, markerfacecolor='#F9F7F2', markeredgewidth=1.5)
    ax.plot(dates, ndwi, color=C['chart_ndwi'], linewidth=2, label='NDWI (Agua)',
            marker='s', markersize=3.5, markerfacecolor='#F9F7F2', markeredgewidth=1.2)
    if any(v != 0 for v in evi):
        ax.plot(dates, evi, color=C['chart_evi'], linewidth=1.8, label='EVI (Productiv.)',
                marker='^', markersize=3.5, markerfacecolor='#F9F7F2', markeredgewidth=1.2)

    ax.text(dates[-1], 0.17, ' Estrés', fontsize=7, color=C['red'], alpha=0.5, va='center')
    ax.text(dates[-1], 0.55, ' Óptimo', fontsize=7, color=C['green'], alpha=0.5, va='center')

    ax.set_ylabel('Valor del índice')
    # v8.2: Título eliminado — el PDF ya tiene SectionTitle
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=10))
    plt.xticks(rotation=30, ha='right')
    ax.set_ylim(-0.15, 1.0)
    ax.legend(loc='lower center', bbox_to_anchor=(0.5, 1.0), ncol=3,
              fontsize=8, framealpha=0.9, edgecolor=C['cream_dark'],
              borderpad=0.4, columnspacing=1.5)
    ax.grid(True, alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor='#F9F7F2', dpi=180)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_ndvi_gauge(ndvi_mean, ndvi_p10, ndvi_p90, width_px=520, height_px=140) -> bytes:
    _chart_style()
    fig, ax = plt.subplots(figsize=(width_px/100, height_px/100), dpi=180)

    gradient = np.linspace(0, 1, 256).reshape(1, -1)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
        'ndvi', [(0, C['red']), (0.35, '#E8A838'), (0.55, C['yellow']),
                 (0.7, C['green']), (1.0, '#2D5016')])
    ax.imshow(gradient, aspect='auto', cmap=cmap, extent=[0, 1, 0, 1])

    ax.plot([ndvi_p10, ndvi_p10], [-0.3, 1.3], color=C['brown_dark'],
            linewidth=1.5, linestyle='--', alpha=0.7)
    ax.plot([ndvi_p90, ndvi_p90], [-0.3, 1.3], color=C['brown_dark'],
            linewidth=1.5, linestyle='--', alpha=0.7)
    ax.annotate(f'P10: {ndvi_p10:.2f}', xy=(ndvi_p10, -0.5),
                ha='center', fontsize=8, color=C['text_light'])
    ax.annotate(f'P90: {ndvi_p90:.2f}', xy=(ndvi_p90, -0.5),
                ha='center', fontsize=8, color=C['text_light'])

    ax.plot(ndvi_mean, 0.5, marker='v', markersize=14, color=C['brown_dark'], zorder=5)
    ax.annotate(f'Media: {ndvi_mean:.2f}', xy=(ndvi_mean, 1.6), ha='center',
                fontsize=10, fontweight='bold', color=C['brown_dark'])

    for v in [0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]:
        ax.text(v, -1.0, f'{v:.1f}', ha='center', fontsize=7, color=C['text_muted'])

    ax.text(0.10, 2.5, 'Estrés', ha='center', fontsize=7.5, color=C['red'], alpha=0.8)
    ax.text(0.375, 2.5, 'Bajo', ha='center', fontsize=7.5, color='#E8A838', alpha=0.8)
    ax.text(0.525, 2.5, 'Moderado', ha='center', fontsize=7.5, color=C['yellow'], alpha=0.8)
    ax.text(0.72, 2.5, 'Alto', ha='center', fontsize=7.5, color=C['green'], alpha=0.8)

    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-1.3, 3.2)
    ax.axis('off')
    ax.set_title('Distribución NDVI en parcela', fontsize=10, fontweight='bold',
                 color=C['brown_dark'], pad=10)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor='#F9F7F2', dpi=180)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_heatmap(title, mean_val, cmap_name='RdYlGn',
                     width_px=280, height_px=220) -> bytes:
    """FALLBACK ONLY — solo se usa si NO hay composite de GEE."""
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
# 6. MAIN PDF GENERATOR CLASS
# ============================================================

class MuOrbitaPDFGenerator:

    KEY_ALIASES = {
        'NDVI_MAP':          ['NDVI_MAP', 'NDVI', 'ndvi', 'ndvi_map'],
        'NDWI_MAP':          ['NDWI_MAP', 'NDWI', 'ndwi', 'ndwi_map'],
        'EVI_MAP':           ['EVI_MAP', 'EVI', 'evi', 'evi_map'],
        'NDCI_MAP':          ['NDCI_MAP', 'NDCI', 'ndci'],
        'SAVI_MAP':          ['SAVI_MAP', 'SAVI', 'savi'],
        'VRA_MAP':           ['VRA_MAP', 'VRA', 'vra'],
        'LST_MAP':           ['LST_MAP', 'LST', 'lst'],
        'RGB':               ['RGB', 'rgb', 'RGB_MAP'],
        'TIME_SERIES':       ['TIME_SERIES', 'time_series'],
        'NDVI_DISTRIBUTION': ['NDVI_DISTRIBUTION', 'ndvi_distribution'],
        'KPI_SUMMARY':       ['KPI_SUMMARY', 'kpi_summary'],
    }

    def __init__(self, data: Dict[str, Any]):
        self.d = data
        self.styles = get_styles()
        self.buffer = io.BytesIO()
        self.W, self.H = A4
        self.M = 15*mm
        self.content_w = self.W - 2*self.M

        # v6.0: Extraer narrativas de Claude (JSON estructurado)
        self.narratives = data.get('narratives', {})
        if not self.narratives:
            for key in ['executive_summary', 'integrated_interpretation',
                        'map_ndvi', 'map_ndwi', 'map_evi', 'map_ndci',
                        'temporal_analysis', 'climate_assessment',
                        'risk_hydric_level', 'risk_hydric_text',
                        'risk_thermal_level', 'risk_thermal_text',
                        'risk_heterogeneity_level', 'risk_heterogeneity_text',
                        'vra_analysis', 'recommendations', 'conclusion',
                        # v7.0 biweekly keys
                        'changes_interpretation', 'new_risks',
                        'forecast_narrative',
                        # v8.1 followup key
                        'prev_actions_followup']:
                if key in data and data[key]:
                    self.narratives[key] = data[key]

        if self.narratives:
            print(f"✅ PDF v8.2: {len(self.narratives)} narrative fields from Claude")
        else:
            print("⚠️ PDF v8.2: No narratives — using auto-generated text")

        # ── Build png_map con PRIORIDAD BD ──
        self.png_map = {}
        job_id = data.get('job_id', '')

        if job_id:
            self._load_images_from_db(job_id)

        if not self.png_map:
            for img in data.get('png_images', []) or []:
                name = img.get('name', '')
                b64 = img.get('base64', '')
                if name and b64 and not b64.startswith('['):
                    self.png_map[name] = b64

            for name, b64 in (data.get('images_base64', {}) or {}).items():
                if name and b64 and isinstance(b64, str) and not b64.startswith('['):
                    if name not in self.png_map:
                        self.png_map[name] = b64

        if self.png_map:
            print(f"✅ PDF v8.2: png_map con {len(self.png_map)} imágenes: {list(self.png_map.keys())}")
        else:
            print("⚠️ PDF v8.2: png_map VACÍO — se usarán gráficos matplotlib")

    def _load_images_from_db(self, job_id: str):
        try:
            from app.services.image_provider import get_image_provider
            provider = get_image_provider()
            self.png_map = provider.load_all_as_map(job_id)
            if self.png_map:
                print(f"✅ Loaded {len(self.png_map)} images from DB for {job_id}")
            else:
                print(f"⚠️ No images found in DB for {job_id}")
        except ImportError:
            self._load_images_from_db_direct(job_id)
        except Exception as e:
            print(f"⚠️ Could not load images from DB: {e}")

    def _load_images_from_db_direct(self, job_id: str):
        try:
            from app.database import SessionLocal
            from app.models.gee_image import GEEImage
            db = SessionLocal()
            try:
                images = db.query(
                    GEEImage.index_type, GEEImage.png_base64
                ).filter(
                    GEEImage.job_id == job_id,
                    GEEImage.png_base64.isnot(None)
                ).all()
                for index_type, b64 in images:
                    if b64 and isinstance(b64, str) and not b64.startswith('['):
                        self.png_map[index_type] = b64
            finally:
                db.close()
        except Exception as e:
            print(f"⚠️ Direct DB load failed: {e}")

    def _has_real_map(self, name: str) -> bool:
        """v8.0: Comprueba si existe mapa real de GEE (no fallback matplotlib)."""
        if name in self.png_map:
            return True
        aliases = self.KEY_ALIASES.get(name, [])
        return any(alias in self.png_map for alias in aliases)

    def _real_or_generated(self, name: str, fallback_bytes: bytes,
                           width_mm: float, height_mm: float) -> Image:
        if name in self.png_map:
            img_bytes = base64.b64decode(self.png_map[name])
            return Image(io.BytesIO(img_bytes), width=width_mm*mm, height=height_mm*mm)

        aliases = self.KEY_ALIASES.get(name, [])
        for alias in aliases:
            if alias in self.png_map:
                img_bytes = base64.b64decode(self.png_map[alias])
                return Image(io.BytesIO(img_bytes), width=width_mm*mm, height=height_mm*mm)

        return Image(io.BytesIO(fallback_bytes), width=width_mm*mm, height=height_mm*mm)

    def _get_narrative(self, key: str, fallback: str = '') -> str:
        return self.narratives.get(key, fallback) or fallback

    # ── Header / Footer ──
    def _header_footer(self, cvs, doc):
        cvs.saveState()

        cvs.setFillColor(hex_color('cream'))
        cvs.rect(0, self.H - 20*mm, self.W, 20*mm, fill=True, stroke=False)
        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.8)
        cvs.line(0, self.H - 20*mm, self.W, self.H - 20*mm)

        cvs.setFillColor(hex_color('brown_dark'))
        cvs.setFont('Helvetica-Oblique', 16)
        cvs.drawString(self.M + 4*mm, self.H - 14*mm, 'Mu')
        mu_w = cvs.stringWidth('Mu', 'Helvetica-Oblique', 16)
        cvs.setFont('Helvetica-Bold', 16)
        cvs.drawString(self.M + 4*mm + mu_w, self.H - 14*mm, '.Orbita')

        cvs.setFillColor(hex_color('gold'))
        cvs.setFont('Helvetica-Bold', 8.5)
        cvs.drawRightString(self.W - self.M - 4*mm, self.H - 13*mm, 'INFORME SATELITAL')

        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.5)
        cvs.line(self.M, 11*mm, self.W - self.M, 11*mm)

        cvs.setFillColor(hex_color('text_muted'))
        cvs.setFont('Helvetica', 7)
        cvs.drawString(self.M, 7*mm, f'© {datetime.now().year} Mu.Orbita')
        cvs.drawCentredString(self.W/2, 7*mm, f'Página {doc.page}')
        cvs.drawRightString(self.W - self.M, 7*mm, 'info@muorbita.com')

        cvs.restoreState()

    # ── Cover Page ──
    def _draw_cover(self, cvs, doc):
        cvs.saveState()

        cvs.setFillColor(hex_color('cream'))
        cvs.rect(0, 0, self.W, self.H, fill=True, stroke=False)

        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.8)
        cvs.line(self.M + 8*mm, self.H - 30*mm, self.W - self.M - 8*mm, self.H - 30*mm)

        cvs.setFillColor(hex_color('brown_dark'))
        cvs.setFont('Helvetica-Oblique', 28)
        cvs.drawString(self.M + 8*mm, self.H - 22*mm, 'Mu')
        mu_w = cvs.stringWidth('Mu', 'Helvetica-Oblique', 28)
        cvs.setFont('Helvetica-Bold', 28)
        cvs.drawString(self.M + 8*mm + mu_w, self.H - 22*mm, '.Orbita')

        cvs.setFillColor(hex_color('gold'))
        cvs.setFont('Helvetica-Bold', 9)
        cvs.drawRightString(self.W - self.M - 8*mm, self.H - 20*mm, 'INFORME SATELITAL')

        band_y = self.H - 95*mm
        band_h = 50*mm
        cvs.setFillColor(hex_color('cover_band'))
        cvs.rect(0, band_y, self.W, band_h, fill=True, stroke=False)

        cvs.setFillColor(hex_color('brown_dark'))
        cvs.setFont('Helvetica-Bold', 26)
        cvs.drawString(self.M + 8*mm, band_y + band_h - 20*mm, 'Informe de Análisis Agrícola')

        at = self.d.get('analysis_type', 'baseline').upper()
        lbl = 'Diagnóstico Inicial' if at == 'BASELINE' else 'Seguimiento Periódico'
        cvs.setFont('Helvetica', 13)
        cvs.setFillColor(hex_color('brown'))
        cvs.drawString(self.M + 8*mm, band_y + band_h - 34*mm, f'Análisis {at} — {lbl}')

        cvs.setStrokeColor(hex_color('gold_light'))
        cvs.setLineWidth(2)
        cvs.line(self.M + 8*mm, band_y + band_h - 40*mm,
                 self.M + 50*mm, band_y + band_h - 40*mm)

        # ── Metadata card ──
        meta = [
            ('Cliente', self.d.get('client_name', 'N/A')),
            ('Cultivo', crop_label(self.d.get('crop_type', ''))),
            ('Superficie', f"{self.d.get('area_hectares', 0):.1f} hectáreas"),
            ('Período analizado', f"{fmt_date(self.d.get('start_date'))}  →  {fmt_date(self.d.get('end_date'))}"),
            ('Referencia', self.d.get('job_id', 'N/A')),
        ]
        # v8.2: Añadir parcela y SIGPAC si disponibles
        parcel_name = self.d.get('parcel_name', '')
        if parcel_name:
            meta.insert(2, ('Parcela', parcel_name))
        sigpac = self.d.get('sigpac_ref', '')
        if sigpac:
            idx = 3 if parcel_name else 2
            meta.insert(idx, ('Ref. SIGPAC', sigpac))

        card_x = self.M + 8*mm
        card_w = self.W - 2*self.M - 16*mm
        # v8.2: Dynamic height based on number of meta fields
        card_h = max(80*mm, (len(meta) * 12 + 18) * mm)
        card_y = band_y - 15*mm - card_h

        cvs.setFillColor(hex_color('white'))
        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.8)
        cvs.roundRect(card_x, card_y, card_w, card_h, 6, fill=True, stroke=True)

        cvs.setFillColor(hex_color('gold'))
        cvs.setFont('Helvetica-Bold', 9)
        cvs.drawString(card_x + 14*mm, card_y + card_h - 14*mm, 'RESUMEN DEL ANÁLISIS')

        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.4)
        cvs.line(card_x + 10*mm, card_y + card_h - 18*mm,
                 card_x + card_w - 10*mm, card_y + card_h - 18*mm)

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
            row_y -= 9*mm

        # ════════════════════════════════════════════
        # v8.0 NEW: Semáforo de estado general
        # ════════════════════════════════════════════
        status = _calc_general_status(self.d)
        status_cfg = {
            'normal':    (C['green'],  'BUEN ESTADO'),
            'atencion':  (C['yellow'], 'REQUIERE ATENCIÓN'),
            'critico':   (C['red'],    'ESTADO CRÍTICO'),
        }
        sem_color_hex, sem_label = status_cfg.get(status, status_cfg['normal'])
        sem_color = colors.HexColor(sem_color_hex)

        sem_y = card_y - 18*mm
        sem_x = self.W / 2

        # Fondo pill
        pill_w = 70*mm
        pill_h = 10*mm
        pill_x = sem_x - pill_w / 2
        cvs.setFillColor(colors.HexColor('#FFFFFF'))
        cvs.setStrokeColor(sem_color)
        cvs.setLineWidth(1.5)
        cvs.roundRect(pill_x, sem_y, pill_w, pill_h, pill_h / 2, fill=True, stroke=True)

        # Círculo de color
        cvs.setFillColor(sem_color)
        cvs.circle(pill_x + 8*mm, sem_y + pill_h / 2, 3*mm, fill=True, stroke=False)

        # Texto
        cvs.setFillColor(colors.HexColor(sem_color_hex))
        cvs.setFont('Helvetica-Bold', 9)
        cvs.drawString(pill_x + 14*mm, sem_y + pill_h / 2 - 1.5*mm, sem_label)

        # ── Footer ──
        cvs.setFillColor(hex_color('text_light'))
        cvs.setFont('Helvetica', 9)
        cvs.drawCentredString(self.W/2, sem_y - 10*mm,
            f'Fecha del informe: {datetime.now().strftime("%d/%m/%Y")}')

        cvs.setFillColor(hex_color('text_muted'))
        cvs.setFont('Helvetica', 8)
        cvs.drawCentredString(self.W/2, 15*mm,
            f'© {datetime.now().year} Mu.Orbita — info@muorbita.com — www.muorbita.com')

        cvs.restoreState()

    # ── KPI Cards ──
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

    # ── Detail Table ──
    def _detail_table(self) -> Table:
        d = self.d
        s = self.styles

        ndvi_i, _ = ndvi_status(d.get('ndvi_mean', 0))
        ndwi_i, _ = ndwi_status(d.get('ndwi_mean', 0))

        # ── EVI interpretation ──
        evi_m = d.get('evi_mean') or 0
        if evi_m >= 0.35:
            evi_interp = 'Productividad alta'
        elif evi_m >= 0.25:
            evi_interp = 'Productividad moderada'
        elif evi_m > 0:
            evi_interp = 'Productividad baja'
        else:
            evi_interp = '—'

        # ── NDCI interpretation ──
        ndci_m = d.get('ndci_mean') or 0
        if ndci_m >= 0.3:
            ndci_interp = 'Clorofila adecuada'
        elif ndci_m >= 0.2:
            ndci_interp = 'Clorofila moderada'
        elif ndci_m > 0:
            ndci_interp = 'Clorofila baja'
        else:
            ndci_interp = '—'

        rows = [
            ['Métrica', 'Media', 'P10', 'P50', 'P90', 'Interpretación'],
            ['NDVI (Vigor)',
                fv(d.get('ndvi_mean')), fv(d.get('ndvi_p10')),
                fv(d.get('ndvi_p50')), fv(d.get('ndvi_p90')), ndvi_i],
            ['NDWI (Agua)',
                fv(d.get('ndwi_mean'), 3), fv(d.get('ndwi_p10'), 3),
                fv(d.get('ndwi_p50'), 3), fv(d.get('ndwi_p90'), 3), ndwi_i],
            ['EVI (Productiv.)',
                fv(d.get('evi_mean'), 3), fv(d.get('evi_p10'), 3),
                fv(d.get('evi_p50'), 3), fv(d.get('evi_p90'), 3), evi_interp],
            ['NDCI (Clorofila)',
                fv(d.get('ndci_mean'), 3), '—', '—', '—', ndci_interp],
            ['SAVI (Aj. suelo)',
                fv(d.get('savi_mean'), 3), '—', '—', '—', '—'],
        ]

        data = []
        for r_idx, row in enumerate(rows):
            tr = []
            for c_idx, cell in enumerate(row):
                st = s['TableHeader'] if r_idx == 0 else (
                    s['TableCellLeft'] if c_idx == 0 else s['TableCell'])
                tr.append(Paragraph(str(cell), st))
            data.append(tr)

        cw = [32*mm, 22*mm, 18*mm, 18*mm, 18*mm, 62*mm]
        tbl = Table(data, colWidths=cw)

        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), hex_color('table_header')),
            ('TEXTCOLOR', (0, 0), (-1, 0), hex_color('white')),
            ('GRID', (0, 0), (-1, -1), 0.5, hex_color('cream_dark')),
            ('BOX', (0, 0), (-1, -1), 1, hex_color('table_header')),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]
        for r in range(2, len(data), 2):
            style_cmds.append(('BACKGROUND', (0, r), (-1, r), hex_color('cream')))
        tbl.setStyle(TableStyle(style_cmds))
        return tbl

    # ── v6.0: Weather ERA5 Table ──
    def _weather_table(self) -> Optional[Table]:
        """Tabla de condiciones climáticas ERA5. Retorna None si no hay datos."""
        d = self.d
        s = self.styles

        tmax  = d.get('weather_tmax_mean')
        tmin  = d.get('weather_tmin_mean')
        tmin_min = d.get('weather_tmin_min')
        precip = d.get('weather_precip_total')
        balance = d.get('weather_water_balance')
        gdd   = d.get('weather_gdd') or d.get('weather_gdd_base10')
        heat  = d.get('weather_heat_days', 0)
        frost = d.get('weather_frost_days', 0)
        et    = d.get('weather_et_total')
        rain_days = d.get('weather_rain_days', 0)
        lst   = d.get('lst_mean_c')
        soil_moisture = d.get('weather_soil_moisture')

        has_era5 = any(v is not None and v != 0 for v in [tmax, precip, balance, gdd])

        # v8.0: Si no hay ERA5 ni LST, no mostrar tabla vacía
        if not has_era5 and not lst:
            return None

        rows_data = [
            ['Parámetro', 'Valor', 'Interpretación'],
        ]

        if has_era5:
            if tmax is not None:
                rows_data.append(['Tmax media (ERA5)', f'{float(tmax):.1f} ºC',
                                  'Temperatura máxima promedio aire'])
            # v8.0 NEW: Tmin
            if tmin is not None:
                tmin_str = f'{float(tmin):.1f} ºC'
                if tmin_min is not None:
                    tmin_str += f' (mín: {float(tmin_min):.1f} ºC)'
                rows_data.append(['Tmin media (ERA5)', tmin_str,
                                  'Temperatura mínima promedio aire'])
            if precip is not None:
                rows_data.append(['Precipitación total',
                                  f'{float(precip):.1f} mm ({rain_days} días)',
                                  'Aporte hídrico del período'])
            if et is not None:
                rows_data.append(['Evapotranspiración',
                                  f'{float(et):.1f} mm',
                                  'Demanda hídrica del cultivo'])
            if balance is not None:
                bal_val = float(balance)
                bal_interp = 'Superávit hídrico' if bal_val > 0 else 'Déficit hídrico'
                rows_data.append(['Balance hídrico (P-ET)',
                                  f'{bal_val:+.1f} mm', bal_interp])
            if heat > 0:
                rows_data.append(['Días Tmax >= 35 ºC', str(heat),
                                  'Estrés térmico acumulado'])
            if frost > 0:
                rows_data.append(['Días helada (Tmin <= 0 ºC)', str(frost),
                                  'Riesgo de daño por frío'])
            if gdd is not None:
                rows_data.append(['GDD acumulados (base 10 ºC)',
                                  f'{float(gdd):.0f}',
                                  'Desarrollo fenológico acumulado'])
            # v8.0: Humedad del suelo con unidad
            if soil_moisture is not None and float(soil_moisture) > 0:
                rows_data.append(['Humedad del suelo (ERA5)',
                                  f'{float(soil_moisture):.2f} m³/m³',
                                  'Contenido volumétrico medio'])

        # LST solo si tiene valor real (>0)
        if lst is not None and float(lst) > 0:
            rows_data.append(['LST media (MODIS)',
                              f'{float(lst):.1f} ºC',
                              'Temperatura superficial del cultivo'])

        if len(rows_data) < 2:
            return None

        data = []
        for r_idx, row in enumerate(rows_data):
            tr = []
            for c_idx, cell in enumerate(row):
                st = s['TableHeader'] if r_idx == 0 else (
                    s['TableCellLeft'] if c_idx in [0, 2] else s['TableCell'])
                tr.append(Paragraph(str(cell), st))
            data.append(tr)

        cw = [45*mm, 40*mm, 85*mm]
        tbl = Table(data, colWidths=cw)
        style_cmds = [
            ('BACKGROUND',(0,0),(-1,0), hex_color('table_header')),
            ('TEXTCOLOR',(0,0),(-1,0), hex_color('white')),
            ('GRID',(0,0),(-1,-1), 0.5, hex_color('cream_dark')),
            ('BOX',(0,0),(-1,-1), 1, hex_color('table_header')),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1), 5),
            ('BOTTOMPADDING',(0,0),(-1,-1), 5),
        ]
        for r in range(2, len(data), 2):
            style_cmds.append(('BACKGROUND',(0,r),(-1,r), hex_color('cream')))
        tbl.setStyle(TableStyle(style_cmds))
        return tbl

    # ── v6.0 → v8.0: Risk Table with narrative texts ──
    def _risk_table(self) -> Table:
        d = self.d
        s = self.styles

        ndwi_m = d.get('ndwi_mean', 0)
        ndvi_m = d.get('ndvi_mean', 0)
        hetero = (d.get('ndvi_p90', 0) or 0) - (d.get('ndvi_p10', 0) or 0)

        h_lvl  = self._get_narrative('risk_hydric_level', '')
        t_lvl  = self._get_narrative('risk_thermal_level', '')
        hh_lvl = self._get_narrative('risk_heterogeneity_level', '')

        if not h_lvl:
            if ndwi_m < 0:    h_lvl = 'Alto'
            elif ndwi_m<0.10: h_lvl = 'Moderado'
            else:             h_lvl = 'Bajo'

        if not t_lvl:
            heat = d.get('weather_heat_days', 0) or 0
            if heat > 5:      t_lvl = 'Alto'
            elif heat > 0:    t_lvl = 'Moderado'
            else:             t_lvl = 'Bajo'

        if not hh_lvl:
            if hetero > 0.25: hh_lvl = 'Alta'
            elif hetero>0.15: hh_lvl = 'Media'
            else:             hh_lvl = 'Baja'

        def color_for_level(lvl):
            ll = str(lvl).lower()
            if ll in ['alto', 'alta']: return 'red'
            if ll in ['moderado', 'media', 'medio']: return 'yellow'
            return 'green'

        def risk_row(name, level, indicator, detail_text):
            c_key = color_for_level(level)
            dot = f'<font color="{C[c_key]}">●</font>'
            return [
                Paragraph(name, s['TableCellLeft']),
                Paragraph(f'{dot} {level}', s['TableCell']),
                Paragraph(indicator, s['TableCell']),
                Paragraph(detail_text if detail_text else '—', s['TableCellWrap']),
            ]

        h_text = self._get_narrative('risk_hydric_text', f'NDWI medio: {ndwi_m:.2f}')

        # ════════════════════════════════════════════
        # v8.0 FIX: LST indicator — fallback a ERA5 Tmax si LST es 0/None
        # ════════════════════════════════════════════
        lst_val = d.get('lst_mean_c')
        tmax_val = d.get('weather_tmax_mean')
        if lst_val is not None and float(lst_val) > 0:
            thermal_indicator = f'LST: {float(lst_val):.1f} ºC'
        elif tmax_val is not None and float(tmax_val) > 0:
            thermal_indicator = f'Tmax: {float(tmax_val):.1f} ºC (ERA5)'
        else:
            thermal_indicator = 'N/D'

        t_text = self._get_narrative('risk_thermal_text', '')
        if not t_text:
            heat = d.get('weather_heat_days', 0) or 0
            frost = d.get('weather_frost_days', 0) or 0
            t_text = f'{thermal_indicator}. {heat} días calor extremo, {frost} días helada.'

        hh_text = self._get_narrative('risk_heterogeneity_text', f'Rango P90-P10: {hetero:.2f}')

        header = [Paragraph(h, s['TableHeader'])
                  for h in ['Riesgo', 'Nivel', 'Indicador', 'Evaluación']]
        data = [
            header,
            risk_row('Estrés hídrico',  h_lvl,  f'NDWI: {ndwi_m:.2f}',  h_text),
            risk_row('Estrés térmico',  t_lvl,  thermal_indicator,        t_text),
            risk_row('Heterogeneidad',  hh_lvl, f'Δ: {hetero:.2f}',      hh_text),
        ]

        cw = [30*mm, 24*mm, 28*mm, 88*mm]
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

    # ── v6.0: Structured Recommendations from Claude JSON ──
    def _recommendations(self) -> List:
        d = self.d
        s = self.styles
        elements = []

        recs_from_claude = self.narratives.get('recommendations', [])

        if recs_from_claude and isinstance(recs_from_claude, list) and len(recs_from_claude) > 0:
            for i, rec in enumerate(recs_from_claude[:3], 1):
                if isinstance(rec, dict):
                    elements.append(RecommendationCard(
                        number=i,
                        title=rec.get('title', 'Acción pendiente'),
                        priority=rec.get('priority', 'Media'),
                        deadline=f"{rec.get('deadline_days', 14)} días",
                        trigger=rec.get('trigger', '—'),
                        zone=rec.get('zone', 'Toda la parcela'),
                        justification=rec.get('justification', '—'),
                        styles=s,
                        width=self.content_w,
                    ))
                    elements.append(Spacer(1, 3*mm))
        else:
            elements.extend(self._auto_recommendations())

        return elements

    def _auto_recommendations(self) -> List:
        d = self.d
        s = self.styles
        elements = []

        ndwi_m = d.get('ndwi_mean', 0)
        ndvi_m = d.get('ndvi_mean', 0)
        stress_pct = d.get('stress_area_pct', 0)

        recs = []
        if ndvi_m < 0.35:
            recs.append(('Inspección de campo de zonas críticas', 'Alta', '3–5 días',
                f'NDVI = {ndvi_m:.2f} indica estrés severo',
                f'Zonas con NDVI < 0.35 ({stress_pct:.1f}% del área)',
                'Descartar plagas, enfermedades o fallo de riego'))
        elif ndvi_m < 0.45:
            recs.append(('Inspección visual de zonas de bajo vigor', 'Media', '7 días',
                f'NDVI = {ndvi_m:.2f} indica vigor bajo', 'Zonas con menor vigor',
                'Identificar causas de bajo rendimiento vegetativo'))
        else:
            recs.append(('Monitorización de mantenimiento', 'Baja', '14 días',
                f'NDVI = {ndvi_m:.2f} dentro de rango normal', 'Toda la parcela',
                'Mantener detección temprana de cambios'))

        if ndwi_m < 0:
            recs.append(('Revisión urgente del sistema de riego', 'Alta', '3 días',
                f'NDWI = {ndwi_m:.2f} indica déficit severo', 'Toda la parcela',
                'Estrés hídrico severo puede reducir producción hasta 30%'))
        elif ndwi_m < 0.10:
            recs.append(('Ajustar programación de riego', 'Media', '7 días',
                f'NDWI = {ndwi_m:.2f} indica déficit moderado', 'Sectores con menor NDWI',
                'Prevenir escalada del estrés hídrico'))
        else:
            recs.append(('Mantener régimen de riego actual', 'Baja', '14 días',
                'Estado hídrico aceptable', 'Toda la parcela', 'Monitorizar evolución'))

        recs.append(('Planificar fertilización según zonificación', 'Media', '14 días',
            'Optimizar inputs según vigor diferencial', 'Zonas NDVI alto vs bajo',
            'Maximizar eficiencia del fertilizante'))

        for i, (title, priority, deadline, trigger, zone, justification) in enumerate(recs[:3], 1):
            elements.append(RecommendationCard(
                number=i, title=title, priority=priority, deadline=deadline,
                trigger=trigger, zone=zone, justification=justification,
                styles=s, width=self.content_w,
            ))
            elements.append(Spacer(1, 3*mm))

        return elements

    # ── VRA Analysis ──
    def _vra_section(self) -> List:
        """v8.2: VRA con mapa real de GEE + tabla + narrativa. Ambos tipos de informe."""
        d = self.d
        s = self.styles
        elements = []

        vra_stats = d.get('vra_stats', [])
        vra_text = self._get_narrative('vra_analysis', '')

        if not vra_stats and not vra_text:
            return elements

        elements.append(Paragraph('Zonificación VRA (Aplicación Variable)', s['SubsectionTitle']))

        # v8.2 NEW: Mapa VRA real de GEE si existe
        if self._has_real_map('VRA_MAP'):
            vra_fallback = generate_heatmap('VRA (Zonas)', 1.0, 'RdYlGn')
            elements.append(self._real_or_generated('VRA_MAP', vra_fallback, 155, 55))
            elements.append(Spacer(1, 3*mm))

        if vra_stats and isinstance(vra_stats, list) and len(vra_stats) > 0:
            header = [Paragraph(h, s['TableHeader'])
                      for h in ['Zona', 'Superficie', 'NDVI medio', 'NDWI medio', 'Recomendación']]
            data = [header]
            zone_colors = {'Bajo vigor': 'red', 'Vigor medio': 'yellow', 'Alto vigor': 'green'}
            for z in vra_stats:
                label = z.get('label', '')
                c_key = zone_colors.get(label, 'yellow')
                dot = f'<font color="{C[c_key]}">●</font>'
                data.append([
                    Paragraph(f'{dot} {label}', s['TableCellLeft']),
                    Paragraph(f'{z.get("area_ha", 0):.1f} ha', s['TableCell']),
                    Paragraph(f'{z.get("ndvi_mean", 0):.3f}', s['TableCell']),
                    Paragraph(f'{z.get("ndwi_mean", 0):.3f}', s['TableCell']),
                    Paragraph(z.get('recommendation', '—'), s['TableCellLeft']),
                ])

            cw = [32*mm, 28*mm, 28*mm, 28*mm, 54*mm]
            tbl = Table(data, colWidths=cw)
            tbl.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0), hex_color('table_header')),
                ('TEXTCOLOR',(0,0),(-1,0), hex_color('white')),
                ('GRID',(0,0),(-1,-1), 0.5, hex_color('cream_dark')),
                ('BOX',(0,0),(-1,-1), 1, hex_color('table_header')),
                ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                ('TOPPADDING',(0,0),(-1,-1), 5),
                ('BOTTOMPADDING',(0,0),(-1,-1), 5),
            ]))
            elements.append(tbl)
            elements.append(Spacer(1, 3*mm))

        if vra_text:
            elements.append(CalloutBox(
                f'<b>Análisis de zonificación:</b> {vra_text}',
                s, accent='gold', width=self.content_w
            ))

        return elements

    # ── Technical Annex ──
    def _annex(self) -> List:
        d = self.d
        s = self.styles
        elements = []

        ct = crop_label(d.get('crop_type',''))
        annex = (
            f'<b>Fuentes de datos</b><br/>'
            f'• Sentinel-2 SR Harmonized: {d.get("images_processed",0)} escenas procesadas<br/>'
            f'• Última imagen válida: {fmt_date(d.get("latest_image_date"))}<br/>'
            f'• MODIS LST: Temperatura superficial media '
            f'{"N/D" if not d.get("lst_mean_c") else str(round(d["lst_mean_c"], 1)) + " ºC"}<br/>'
            f'• ERA5-Land: Datos meteorológicos del período analizado<br/>'
            f'• Resolución: 10 m (S2), 30 m (Landsat), 1 km (MODIS)<br/><br/>'
            f'<b>Umbrales de referencia ({ct})</b><br/>'
            f'• NDVI > 0.60: Vigor alto | 0.45–0.60: Moderado | &lt; 0.35: Estrés severo<br/>'
            f'• NDWI > 0.20: Óptimo | 0.10–0.20: Moderado | &lt; 0.10: Déficit<br/>'
            f'• Rango NDVI típico {ct.lower()}: {crop_ndvi_range(d.get("crop_type",""))}<br/><br/>'
            f'<b>Procesamiento</b><br/>'
            f'• Motor: Google Earth Engine<br/>'
            f'• Máscaras: QA60 + SCL (S2), QA_PIXEL (Landsat)<br/>'
            f'• Estadísticas: Media, P10, P50, P90, desviación estándar<br/>'
            f'• Zonificación VRA: Score compuesto (NDVI 60% + NDWI 25% + EVI 15%)<br/><br/>'
            f'<b>Índices calculados</b><br/>'
            f'• NDVI = (NIR − Red) / (NIR + Red) → Vigor vegetativo<br/>'
            f'• NDWI = (NIR − SWIR) / (NIR + SWIR) → Estado hídrico<br/>'
            f'• EVI = 2.5 × (NIR − Red) / (NIR + 6R − 7.5B + 1) → Productividad<br/>'
            f'• NDCI = (RedEdge − Red) / (RedEdge + Red) → Clorofila'
        )
        elements.append(Paragraph(annex, s['BodySmall']))
        return elements

    # ── v8.2: Guía de Lectura del Informe ──
    def _reading_guide(self) -> List:
        """
        v8.2 NEW: Explicación divulgativa de todos los indicadores para
        lectores no técnicos (agricultores, cooperativas, gestores).
        Colocada después del Anexo Técnico.
        """
        s = self.styles
        elements = []

        ct = crop_label(self.d.get('crop_type', '')).lower()

        guide_text = (
            f'<b>¿Qué es el NDVI?</b><br/>'
            f'El NDVI (Índice de Vegetación) mide la "salud verde" de su cultivo usando '
            f'imágenes de satélite. Un valor alto (>0.60) indica plantas vigorosas y sanas. '
            f'Un valor bajo (&lt;0.35) señala problemas: sequía, enfermedad o suelo desnudo. '
            f'Para {ct}, el rango normal es {crop_ndvi_range(self.d.get("crop_type",""))}.<br/><br/>'

            f'<b>¿Qué es el NDWI?</b><br/>'
            f'El NDWI (Índice de Agua) indica cuánta agua tienen las hojas de sus plantas. '
            f'Valores por encima de 0.20 significan buen estado hídrico. Por debajo de 0.10, '
            f'sus plantas empiezan a "tener sed" y necesitan más riego.<br/><br/>'

            f'<b>¿Qué es el EVI?</b><br/>'
            f'El EVI (Índice de Vegetación Mejorado) mide la productividad fotosintética: '
            f'cuánta energía están produciendo sus plantas. Es similar al NDVI pero más '
            f'preciso en zonas con mucha o poca vegetación.<br/><br/>'

            f'<b>¿Qué es el NDCI?</b><br/>'
            f'El NDCI (Índice de Clorofila) detecta la cantidad de clorofila en las hojas. '
            f'Valores bajos pueden indicar falta de nutrientes (especialmente nitrógeno) '
            f'y ayudan a decidir cuándo y dónde fertilizar.<br/><br/>'

            f'<b>¿Qué es la Zonificación VRA?</b><br/>'
            f'El mapa VRA (Aplicación de Tasa Variable) divide su parcela en zonas según '
            f'su vigor: alto, medio y bajo. Esto permite aplicar fertilizante, riego o '
            f'tratamientos de forma diferenciada — más donde se necesita, menos donde sobra. '
            f'Resultado: ahorra insumos y mejora rendimiento.<br/><br/>'

            f'<b>¿Qué es el Balance Hídrico?</b><br/>'
            f'Es la diferencia entre el agua que recibe su cultivo (lluvia) y el agua que '
            f'pierde (evaporación + transpiración de las plantas). Si es negativo, su cultivo '
            f'está consumiendo más agua de la que recibe y necesita riego adicional.<br/><br/>'

            f'<b>¿Qué son los GDD (Grados-Día)?</b><br/>'
            f'Los Grados-Día de Desarrollo acumulan el calor que recibe el cultivo '
            f'por encima de 10 ºC. Cada cultivo necesita un número concreto de GDD para '
            f'alcanzar cada fase de crecimiento (brotación, floración, maduración). '
            f'Sirven para predecir cuándo llegará cada fase.<br/><br/>'

            f'<b>¿Qué es el Área de Estrés?</b><br/>'
            f'Es el porcentaje de su parcela donde el NDVI es muy bajo (&lt;0.35), indicando '
            f'que las plantas están sufriendo. Si supera el 15%, se recomienda inspección '
            f'de campo urgente para identificar la causa (sequía, plaga, enfermedad, etc.).<br/><br/>'

            f'<b>¿Cómo leer los mapas?</b><br/>'
            f'Los mapas muestran su parcela vista desde el satélite con colores que indican '
            f'el valor de cada índice. En el mapa NDVI: verde intenso = plantas sanas, '
            f'amarillo/rojo = zonas con problemas. En el mapa NDWI: azul = buena hidratación, '
            f'marrón/claro = plantas con sed. Compare las zonas entre mapas para entender '
            f'si un problema de vigor está relacionado con falta de agua o con otra causa.'
        )

        elements.append(Paragraph(guide_text, s['BodySmall']))
        return elements

    # ── v8.2: Bloque de Firma Técnica ──
    def _signature_block(self) -> List:
        """v8.2 NEW: Firma técnica profesional + disclaimer mejorado."""
        s = self.styles
        elements = []

        job_id = self.d.get('job_id', 'N/A')
        at = self.d.get('analysis_type', 'baseline')
        freq = 'quincenal' if at == 'biweekly' else 'inicial (baseline)'

        # Disclaimer mejorado con referencia y frecuencia
        disclaimer = (
            f'<i>Este informe (Ref. {job_id}) ha sido generado automáticamente por '
            f'Mu.Orbita mediante análisis de imágenes satelitales Sentinel-2 y datos '
            f'meteorológicos ERA5-Land. Frecuencia de monitorización: {freq}. '
            f'Las recomendaciones deben ser validadas por un técnico agrónomo cualificado '
            f'antes de su implementación. Los datos satelitales están sujetos a '
            f'disponibilidad y condiciones atmosféricas.</i>'
        )
        elements.append(Paragraph(
            f'<font size="7.5" color="{C["text_muted"]}">{disclaimer}</font>',
            s['Footnote']))
        elements.append(Spacer(1, 6*mm))

        # Firma técnica
        sig = (
            f'<font size="8" color="{C["brown"]}">'
            f'<b>Revisado por el equipo técnico de Mu.Orbita</b><br/>'
            f'Servicio de Agricultura de Precisión Satelital<br/>'
            f'info@muorbita.com · www.muorbita.com'
            f'</font>'
        )
        elements.append(Paragraph(sig, s['Footnote']))

        return elements

    # ════════════════════════════════════════════════════════
    # v7.0 → v8.0: MÉTODOS BISEMANALES
    # ════════════════════════════════════════════════════════

    def _delta_table(self) -> Optional[Table]:
        """
        v8.0 FIX: Tabla de cambios vs período anterior.
        - _sanitize_index() captura bug ×1000 de upstream
        - delta_fmt maneja prev==0 sin dividir por cero
        - Fila extra de comparativa vs baseline original
        """
        d = self.d
        s = self.styles

        # ════════════════════════════════════════════
        # v8.0 FIX: Sanitizar valores previos (×1000 bug)
        # ════════════════════════════════════════════
        prev_ndvi   = _sanitize_index(d.get('prev_ndvi_mean'),  'ndvi')
        prev_ndwi   = _sanitize_index(d.get('prev_ndwi_mean'),  'ndwi')
        prev_stress = d.get('prev_stress_pct')
        prev_evi    = _sanitize_index(d.get('prev_evi_mean'),   'evi')

        if prev_ndvi is None and prev_ndwi is None and prev_stress is None:
            return None

        curr_ndvi   = d.get('ndvi_mean', 0)
        curr_ndwi   = d.get('ndwi_mean', 0)
        curr_stress = d.get('stress_area_pct', 0)
        curr_evi    = d.get('evi_mean', 0)
        area_ha     = d.get('area_hectares', 0)

        def delta_fmt(curr, prev, decimals=2, is_pct=False):
            """v8.0 FIX: No divide por 0; maneja prev==0 correctamente."""
            if prev is None:
                return '—', '—', 'black'
            delta = curr - prev
            if abs(prev) > 0.0001:
                delta_pct = (delta / abs(prev)) * 100
            else:
                delta_pct = 0.0
            sign   = '+' if delta >= 0 else ''
            trend  = '⬆' if delta > 0.005 else ('⬇' if delta < -0.005 else '➡')
            color  = 'green' if delta >= 0 else 'red'
            if is_pct:
                color = 'red' if delta > 0.5 else ('green' if delta < -0.5 else 'black')
            fmt_delta = f"{sign}{delta:.{decimals}f} ({sign}{delta_pct:.1f}%)"
            return fmt_delta, trend, color

        ndvi_delta,   ndvi_trend,   ndvi_color   = delta_fmt(curr_ndvi,   prev_ndvi)
        ndwi_delta,   ndwi_trend,   ndwi_color   = delta_fmt(curr_ndwi,   prev_ndwi, 3)
        stress_delta, stress_trend, stress_color = delta_fmt(curr_stress, prev_stress, 1, is_pct=True)
        evi_delta,    evi_trend,    evi_color    = delta_fmt(curr_evi,    prev_evi, 3)

        # v8.2: Fecha del período anterior en header si disponible
        prev_date = fmt_date(d.get('last_report_date', ''))
        prev_header = f'Anterior ({prev_date})' if prev_date != '—' else 'Período Anterior'

        rows_data = [
            ['Métrica', prev_header, 'Período Actual', 'Cambio', ''],
            ['NDVI (Vigor)',
             fv(prev_ndvi), fv(curr_ndvi), ndvi_delta, ndvi_trend],
            ['NDWI (Agua)',
             fv(prev_ndwi, 3), fv(curr_ndwi, 3), ndwi_delta, ndwi_trend],
            [f'Área estrés ({area_ha:.0f} ha)',
             f"{fv(prev_stress, 1)}%"  if prev_stress is not None else '—',
             f"{fv(curr_stress, 1)}%", stress_delta, stress_trend],
            ['EVI (Productiv.)',
             fv(prev_evi, 3), fv(curr_evi, 3), evi_delta, evi_trend],
        ]

        # v8.0 NEW: Fila de comparativa vs baseline original
        baseline_ndvi = _sanitize_index(d.get('baseline_ndvi'), 'ndvi')
        if baseline_ndvi is not None and abs(baseline_ndvi) <= 1.0:
            bl_delta = curr_ndvi - baseline_ndvi
            bl_pct   = (bl_delta / baseline_ndvi * 100) if baseline_ndvi > 0.0001 else 0
            sign     = '+' if bl_delta >= 0 else ''
            bl_color = 'green' if bl_delta >= 0 else 'red'
            bl_trend = '⬆' if bl_delta > 0.005 else ('⬇' if bl_delta < -0.005 else '➡')
            rows_data.append([
                'NDVI vs Baseline',
                fv(baseline_ndvi),
                fv(curr_ndvi),
                f'{sign}{bl_delta:.2f} ({sign}{bl_pct:.1f}%)',
                bl_trend,
            ])

        # Color mapping for delta column per row
        color_per_row = {
            1: ndvi_color,
            2: ndwi_color,
            3: stress_color,
            4: evi_color,
        }
        if baseline_ndvi is not None:
            color_per_row[5] = bl_color

        data = []
        for r_idx, row in enumerate(rows_data):
            tr = []
            for c_idx, cell in enumerate(row):
                if r_idx == 0:
                    st = s['TableHeader']
                elif c_idx == 0:
                    st = s['TableCellLeft']
                elif c_idx == 3 and r_idx in color_per_row:
                    color = color_per_row[r_idx]
                    st = ParagraphStyle('DeltaCell',
                        parent=s['TableCell'],
                        textColor=(colors.HexColor('#228B22') if color == 'green'
                                   else (colors.HexColor('#CC3300') if color == 'red'
                                   else colors.HexColor('#3E2B1D'))),
                        fontName='Helvetica-Bold',
                        fontSize=9, alignment=1
                    )
                else:
                    st = s['TableCell']
                tr.append(Paragraph(str(cell), st))
            data.append(tr)

        cw = [38*mm, 30*mm, 30*mm, 50*mm, 12*mm]
        tbl = Table(data, colWidths=cw)
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), hex_color('table_header')),
            ('TEXTCOLOR', (0, 0), (-1, 0), hex_color('white')),
            ('GRID', (0, 0), (-1, -1), 0.5, hex_color('cream_dark')),
            ('BOX', (0, 0), (-1, -1), 1, hex_color('table_header')),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]
        for r in range(2, len(data), 2):
            style_cmds.append(('BACKGROUND', (0, r), (-1, r), hex_color('cream')))
        # v8.0: Baseline row con fondo diferenciado
        if baseline_ndvi is not None and len(data) > 5:
            style_cmds.append(('BACKGROUND', (0, 5), (-1, 5),
                               colors.HexColor('#F0EDE5')))
        tbl.setStyle(TableStyle(style_cmds))
        return tbl

    def _forecast_alert_box(self) -> Optional[CalloutBox]:
        """Callout de alertas meteorológicas para los próximos 7 días."""
        d = self.d
        s = self.styles

        forecast = d.get('forecast_summary') or d.get('narratives', {}).get('forecast_summary')
        if not forecast:
            return None

        alerts = []
        if forecast.get('heat_wave_risk'):  alerts.append('OLA DE CALOR prevista')
        if forecast.get('frost_risk'):      alerts.append('RIESGO DE HELADA')
        if forecast.get('drought_risk'):    alerts.append('CONDICIONES DE SEQUÍA')
        if forecast.get('heavy_rain_risk'): alerts.append('LLUVIAS INTENSAS previstas')

        if not alerts:
            return None

        tmax    = forecast.get('temp_max_7d', 'N/A')
        tmin    = forecast.get('temp_min_7d', 'N/A')
        precip  = forecast.get('precip_7d_mm', 0)

        # v8.0 FIX: Siempre "PRÓXIMOS 7 DÍAS" — no depende de days_ahead upstream
        text = (
            f'<b>ALERTAS METEOROLÓGICAS — PRÓXIMOS 7 DÍAS:</b> '
            + ' | '.join(alerts)
            + f'  ·  Tmax: {tmax} ºC · Tmin: {tmin} ºC · Precip: {precip} mm'
        )
        return CalloutBox(text, s, accent='red', width=self.content_w)

    def _forecast_table(self) -> Optional[Table]:
        """
        v8.0 NEW: Tabla estructurada de previsión meteorológica 7 días.
        Separa Tmax pico vs Tmax media para evitar confusión.
        """
        d = self.d
        s = self.styles

        forecast = d.get('forecast_summary')
        if not forecast:
            return None

        tmax_7d = forecast.get('temp_max_7d', 'N/A')
        tmin_7d = forecast.get('temp_min_7d', 'N/A')
        precip  = forecast.get('precip_7d_mm', 0)

        alerts = []
        if forecast.get('heat_wave_risk'):  alerts.append('Ola de calor')
        if forecast.get('frost_risk'):      alerts.append('Helada')
        if forecast.get('drought_risk'):    alerts.append('Sequía')
        if forecast.get('heavy_rain_risk'): alerts.append('Lluvias intensas')
        alert_str = ', '.join(alerts) if alerts else 'Sin alertas'
        alert_color = C['red'] if alerts else C['green']

        rows_data = [
            ['Parámetro', 'Próximos 7 días'],
            ['Tmax prevista', f'{tmax_7d} ºC'],
            ['Tmin prevista', f'{tmin_7d} ºC'],
            ['Precipitación acumulada', f'{precip} mm'],
            ['Alertas activas', alert_str],
        ]

        data = []
        for r_idx, row in enumerate(rows_data):
            tr = []
            for c_idx, cell in enumerate(row):
                if r_idx == 0:
                    st = s['TableHeader']
                elif r_idx == 4 and c_idx == 1:
                    # Color the alert cell
                    st = ParagraphStyle('AlertCell', parent=s['TableCell'],
                         textColor=colors.HexColor(alert_color),
                         fontName='Helvetica-Bold', fontSize=9, alignment=1)
                elif c_idx == 0:
                    st = s['TableCellLeft']
                else:
                    st = s['TableCell']
                tr.append(Paragraph(str(cell), st))
            data.append(tr)

        cw = [55*mm, 55*mm]
        tbl = Table(data, colWidths=cw)
        tbl.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), hex_color('table_header')),
            ('TEXTCOLOR',(0,0),(-1,0), hex_color('white')),
            ('GRID',(0,0),(-1,-1), 0.5, hex_color('cream_dark')),
            ('BOX',(0,0),(-1,-1), 1, hex_color('table_header')),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1), 5),
            ('BOTTOMPADDING',(0,0),(-1,-1), 5),
            ('BACKGROUND',(0,2),(-1,2), hex_color('cream')),
            ('BACKGROUND',(0,4),(-1,4), hex_color('cream')),
        ]))
        return tbl

    def _biweekly_executive_bullets(self) -> List:
        """
        v8.0 NEW: Executive summary bisemanal como lista de bullets
        en vez de párrafo continuo. Más escaneable.
        """
        s = self.styles
        elements = []

        exec_text = self._get_narrative('executive_summary', '')
        if not exec_text:
            return elements

        # Dividir por frases (. seguido de espacio y mayúscula, o salto de línea)
        sentences = re.split(r'(?<=[.!])\s+', exec_text.strip())
        sentences = [sent.strip() for sent in sentences if sent.strip()]

        if len(sentences) <= 1:
            # Si es una sola frase, usar callout normal
            elements.append(CalloutBox(
                f'<b>Resumen ejecutivo:</b> {exec_text}',
                s, accent='gold', width=self.content_w
            ))
        else:
            # Múltiples frases → bullets con callout contenedor
            bullet_html = '<b>Resumen ejecutivo:</b><br/>'
            for sent in sentences[:7]:  # Máximo 7 bullets
                bullet_html += f'• {sent}<br/>'
            elements.append(CalloutBox(bullet_html.rstrip('<br/>'),
                                       s, accent='gold', width=self.content_w))

        return elements

    def _biweekly_changes_section(self) -> List:
        """
        v8.0: Sección de cambios bisemanales — SOLO tabla + interpretación.
        Forecast y nuevos riesgos se mueven a su propia sección.
        """
        d = self.d
        s = self.styles
        elements = []

        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Cambios vs Período Anterior', s['SubsectionTitle']))
        elements.append(Spacer(1, 2*mm))

        delta_tbl = self._delta_table()
        if delta_tbl:
            elements.append(delta_tbl)
            elements.append(Spacer(1, 3*mm))
        else:
            elements.append(Paragraph(
                '<i>Primera actualización bisemanal — sin período anterior para comparar.</i>',
                s['Footnote']
            ))
            elements.append(Spacer(1, 3*mm))

        changes_text = self._get_narrative('changes_interpretation', '')
        if changes_text:
            elements.append(CalloutBox(
                f'<b>Interpretación de cambios:</b> {changes_text}',
                s, accent='green', width=self.content_w
            ))
            elements.append(Spacer(1, 3*mm))

        return elements

    def _biweekly_forecast_risks_section(self) -> List:
        """
        v8.0 NEW: Sección separada para forecast + nuevos riesgos.
        Antes estaba todo apretado en _biweekly_changes_section.
        """
        d = self.d
        s = self.styles
        elements = []

        # ── Previsión meteorológica ──
        forecast = d.get('forecast_summary')
        if forecast:
            elements.append(Paragraph('Previsión Meteorológica — Próximos 7 días',
                                      s['SubsectionTitle']))
            elements.append(Spacer(1, 2*mm))

            # Tabla de forecast
            fc_tbl = self._forecast_table()
            if fc_tbl:
                elements.append(fc_tbl)
                elements.append(Spacer(1, 2*mm))

            # Alert box (solo si hay alertas)
            forecast_box = self._forecast_alert_box()
            if forecast_box:
                elements.append(forecast_box)
                elements.append(Spacer(1, 2*mm))

            # Narrativa de impacto
            forecast_narrative = self._get_narrative('forecast_narrative', '')
            if forecast_narrative:
                elements.append(CalloutBox(
                    f'<b>Impacto agronómico previsto:</b> {forecast_narrative}',
                    s, accent='yellow', width=self.content_w
                ))
            elements.append(Spacer(1, 3*mm))

        # ── Nuevos riesgos ──
        new_risks_text = self._get_narrative('new_risks', '')
        if new_risks_text and 'No se han detectado' not in new_risks_text:
            elements.append(Paragraph('Nuevos Riesgos Detectados', s['SubsectionTitle']))
            elements.append(Spacer(1, 1*mm))
            elements.append(CalloutBox(
                f'<b>Nuevos riesgos:</b> {new_risks_text}',
                s, accent='red', width=self.content_w
            ))
        else:
            elements.append(Paragraph(
                f'<font color="{C["green"]}">✓ No se han detectado nuevos riesgos '
                f'significativos en este período.</font>',
                s['Body']
            ))
        elements.append(Spacer(1, 3*mm))

        return elements

    # ── v8.1: Seguimiento de Recomendaciones Anteriores ──
    def _followup_section(self) -> List:
        """
        v8.1 NEW: Renderiza el seguimiento de recomendaciones del informe anterior.
        Datos vienen de narratives['prev_actions_followup'] (generado por Claude).
        Solo se renderiza si hay datos — no aparece en el primer biweekly sin baseline.
        """
        s = self.styles
        elements = []

        followup = self._get_narrative('prev_actions_followup', '')
        if not followup or not isinstance(followup, list) or len(followup) == 0:
            return elements

        elements.append(Paragraph('Seguimiento de Recomendaciones Anteriores',
                                  s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))

        for i, item in enumerate(followup[:3], 1):
            if not isinstance(item, dict):
                continue
            elements.append(FollowupCard(
                number=i,
                title=item.get('title', 'Recomendación anterior'),
                status_label=item.get('status', 'No evaluable'),
                observed_result=item.get('observed_result',
                                         'Sin datos observables en este período'),
                next_step=item.get('next_step', 'Continuar monitorización'),
                styles=s,
                width=self.content_w,
            ))
            elements.append(Spacer(1, 3*mm))

        return elements

    # =====================================================
    # MAIN BUILD METHOD — v8.1
    # =====================================================
    def generate(self) -> bytes:
        """
        v8.1: Añade sección de seguimiento de recomendaciones anteriores.
        BASELINE: estructura idéntica a v6.0/v7.0/v8.0
        BIWEEKLY: followup section entre riesgos y recomendaciones nuevas
        """
        d = self.d
        s = self.styles
        is_biweekly = d.get('analysis_type', 'baseline').lower() == 'biweekly'

        doc = SimpleDocTemplate(
            self.buffer, pagesize=A4,
            leftMargin=self.M, rightMargin=self.M,
            topMargin=25*mm,
            bottomMargin=16*mm
        )

        elements = []
        elements.append(PageBreak())

        ct = crop_label(d.get('crop_type', ''))

        # ════════════════════════════════════════════════════
        # PAGE 2: KPIs + RESUMEN EJECUTIVO
        # ════════════════════════════════════════════════════
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Indicadores Clave de Rendimiento', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 3*mm))
        elements.append(self._kpi_cards())
        elements.append(Spacer(1, 4*mm))

        if is_biweekly:
            # v8.0: Bullets format para biweekly
            exec_elements = self._biweekly_executive_bullets()
            elements.extend(exec_elements)
            elements.append(Spacer(1, 2*mm))

            # Tabla de cambios (sin forecast — va aparte)
            elements.extend(self._biweekly_changes_section())

            # Detalle de Índices en la misma página si cabe
            elements.append(Paragraph('Detalle de Índices Vegetativos', s['SubsectionTitle']))
            elements.append(self._detail_table())
            elements.append(Spacer(1, 4*mm))

            # Gauge
            gauge_bytes = generate_ndvi_gauge(
                d.get('ndvi_mean', 0.3), d.get('ndvi_p10', 0.2), d.get('ndvi_p90', 0.4))
            elements.append(self._real_or_generated('NDVI_DISTRIBUTION', gauge_bytes, 155, 42))

        else:
            # ── BASELINE: igual que v6.0 ──
            exec_summary = self._get_narrative('executive_summary', '')
            if exec_summary:
                elements.append(CalloutBox(
                    f'<b>Resumen ejecutivo:</b> {exec_summary}',
                    s, accent='gold', width=self.content_w
                ))
                elements.append(Spacer(1, 3*mm))

            integrated = self._get_narrative('integrated_interpretation', '')
            if integrated:
                elements.append(CalloutBox(
                    f'<b>Interpretación integrada:</b> {integrated}',
                    s, accent='green', width=self.content_w
                ))
            else:
                ndvi_m     = d.get('ndvi_mean', 0)
                stress_pct = d.get('stress_area_pct', 0)
                hetero     = d.get('ndvi_p90', 0) - d.get('ndvi_p10', 0)

                if stress_pct > 40:
                    interp_text = (
                        f'<b>Interpretación integrada:</b> El cultivo presenta estrés significativo. '
                        f'El NDVI medio de {ndvi_m:.2f} está por debajo del rango típico para '
                        f'{ct.lower()} ({crop_ndvi_range(d.get("crop_type",""))}). '
                        f'El {stress_pct:.1f}% de la superficie muestra estrés. Se requiere inspección.'
                    )
                    accent = 'red'
                elif stress_pct > 15:
                    interp_text = (
                        f'<b>Interpretación integrada:</b> El cultivo presenta señales de estrés moderado. '
                        f'NDVI medio de {ndvi_m:.2f}, con {stress_pct:.1f}% del área en estrés.'
                    )
                    accent = 'yellow'
                else:
                    interp_text = (
                        f'<b>Interpretación integrada:</b> Vigor vegetativo dentro del rango esperado. '
                        f'NDVI medio de {ndvi_m:.2f}, consistente con {ct.lower()} en actividad normal. '
                        f'Heterogeneidad: {hetero_label(d.get("ndvi_p10",0), d.get("ndvi_p90",0)).lower()} '
                        f'(P10-P90: {d.get("ndvi_p10",0):.2f}–{d.get("ndvi_p90",0):.2f}).'
                    )
                    accent = 'green'
                elements.append(CalloutBox(interp_text, s, accent=accent, width=self.content_w))

            elements.append(Spacer(1, 4*mm))

            # Detalle de Índices (baseline)
            elements.append(Paragraph('Detalle de Índices Vegetativos', s['SubsectionTitle']))
            elements.append(self._detail_table())
            elements.append(Spacer(1, 4*mm))

            # Gauge NDVI (baseline)
            gauge_bytes = generate_ndvi_gauge(
                d.get('ndvi_mean', 0.3), d.get('ndvi_p10', 0.2), d.get('ndvi_p90', 0.4))
            elements.append(self._real_or_generated('NDVI_DISTRIBUTION', gauge_bytes, 155, 42))

        # ════════════════════════════════════════════════════
        # PAGE: MAPAS CON INTERPRETACIÓN
        # ════════════════════════════════════════════════════
        elements.append(PageBreak())
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Mapas de Vigor y Estado Hídrico', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))

        # Row 1: NDVI + NDWI
        ndvi_map_bytes = generate_heatmap('NDVI (Vigor)', d.get('ndvi_mean', 0.3), 'RdYlGn')
        ndwi_map_bytes = generate_heatmap('NDWI (Agua)', max(0, d.get('ndwi_mean', 0)), 'YlGnBu')

        maps_row1 = Table([
            [self._real_or_generated('NDVI_MAP', ndvi_map_bytes, 78, 55),
             self._real_or_generated('NDWI_MAP', ndwi_map_bytes, 78, 55)]
        ], colWidths=[83*mm, 83*mm])
        maps_row1.setStyle(TableStyle([
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ]))
        elements.append(maps_row1)

        map_ndvi_text = self._get_narrative('map_ndvi', '')
        map_ndwi_text = self._get_narrative('map_ndwi', '')
        if map_ndvi_text or map_ndwi_text:
            captions_row1 = [
                Paragraph(f'<b>NDVI:</b> {map_ndvi_text}' if map_ndvi_text else '', s['MapCaption']),
                Paragraph(f'<b>NDWI:</b> {map_ndwi_text}' if map_ndwi_text else '', s['MapCaption']),
            ]
            cap_tbl1 = Table([captions_row1], colWidths=[83*mm, 83*mm])
            cap_tbl1.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                          ('TOPPADDING',(0,0),(-1,-1), 1)]))
            elements.append(cap_tbl1)

        elements.append(Spacer(1, 3*mm))

        # Row 2: EVI + NDCI
        evi_map_bytes  = generate_heatmap('EVI (Productividad)', d.get('evi_mean', 0.25), 'YlOrRd')
        ndci_map_bytes = generate_heatmap('NDCI (Clorofila)',    d.get('ndci_mean', 0.2),  'YlGn')

        maps_row2 = Table([
            [self._real_or_generated('EVI_MAP',  evi_map_bytes,  78, 55),
             self._real_or_generated('NDCI_MAP', ndci_map_bytes, 78, 55)]
        ], colWidths=[83*mm, 83*mm])
        maps_row2.setStyle(TableStyle([
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ]))
        elements.append(maps_row2)

        map_evi_text  = self._get_narrative('map_evi', '')
        map_ndci_text = self._get_narrative('map_ndci', '')
        if map_evi_text or map_ndci_text:
            captions_row2 = [
                Paragraph(f'<b>EVI:</b> {map_evi_text}'   if map_evi_text  else '', s['MapCaption']),
                Paragraph(f'<b>NDCI:</b> {map_ndci_text}' if map_ndci_text else '', s['MapCaption']),
            ]
            cap_tbl2 = Table([captions_row2], colWidths=[83*mm, 83*mm])
            cap_tbl2.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                          ('TOPPADDING',(0,0),(-1,-1), 1)]))
            elements.append(cap_tbl2)

        elements.append(Spacer(1, 2*mm))

        # v8.0: Nota de mapa — distingue real vs sintético por índice
        has_ndvi_real = self._has_real_map('NDVI_MAP')
        has_evi_real  = self._has_real_map('EVI_MAP')

        if has_ndvi_real and has_evi_real:
            map_note = (
                '<b>Nota:</b> Mapas generados por Google Earth Engine sobre imagen satelital '
                'Sentinel-2 con la geometría real de la parcela.'
            )
        elif has_ndvi_real:
            map_note = (
                '<b>Nota:</b> NDVI y NDWI: mapas satelitales reales (GEE + Sentinel-2). '
                'EVI y NDCI: distribución espacial estimada — imágenes satelitales en desarrollo.'
            )
        else:
            map_note = (
                '<b>Nota:</b> Mapas sintéticos de distribución espacial estimada. '
                'Contacte a soporte si no aparecen las imágenes satelitales reales.'
            )
        elements.append(Paragraph(f'<font size="8" color="{C["text_muted"]}">{map_note}</font>',
                                  s['Footnote']))

        # ════════════════════════════════════════════════════
        # PAGE: EVOLUCIÓN TEMPORAL + CLIMA
        # ════════════════════════════════════════════════════
        elements.append(PageBreak())
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Evolución Temporal de Índices', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))

        ts = d.get('time_series', [])
        chart_bytes = generate_ts_chart(ts, d.get('crop_type', 'olivar'))
        elements.append(self._real_or_generated('TIME_SERIES', chart_bytes, 165, 60))
        elements.append(Spacer(1, 2*mm))

        temporal_text = self._get_narrative('temporal_analysis', '')
        if temporal_text:
            elements.append(CalloutBox(
                f'<b>Análisis de tendencia:</b> {temporal_text}',
                s, accent='green', width=self.content_w
            ))
        else:
            chart_note = (
                f'<b>Lectura del gráfico:</b> Verde = NDVI (vigor); Azul = NDWI (agua); '
                f'Dorado = EVI (productividad). La franja roja marca estrés severo '
                f'(NDVI &lt;0.35). La franja verde marca el rango óptimo para {ct.lower()}.'
            )
            if len(ts or []) < 5:
                chart_note += ' Los datos acumulados son aún insuficientes para tendencias robustas.'
            elements.append(CalloutBox(chart_note, s, accent='gold', width=self.content_w))

        elements.append(Spacer(1, 5*mm))

        elements.append(Paragraph('Condiciones Climáticas', s['SubsectionTitle']))
        weather_tbl = self._weather_table()
        if weather_tbl:
            elements.append(weather_tbl)
            elements.append(Spacer(1, 3*mm))

        climate_text = self._get_narrative('climate_assessment', '')
        if climate_text:
            elements.append(CalloutBox(
                f'<b>Evaluación climática:</b> {climate_text}',
                s, accent='gold', width=self.content_w
            ))

        # ════════════════════════════════════════════════════
        # BIWEEKLY: FORECAST + NUEVOS RIESGOS (en su propia sección)
        # ════════════════════════════════════════════════════
        if is_biweekly:
            elements.append(Spacer(1, 3*mm))
            elements.extend(self._biweekly_forecast_risks_section())

        # ════════════════════════════════════════════════════
        # PAGE: RIESGOS + VRA (VRA solo en baseline)
        # ════════════════════════════════════════════════════
        elements.append(PageBreak())
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Evaluación de Riesgos', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))
        elements.append(self._risk_table())
        elements.append(Spacer(1, 5*mm))

        # v8.2: VRA en AMBOS tipos de informe (antes solo baseline)
        vra_elements = self._vra_section()
        if vra_elements:
            elements.extend(vra_elements)
            elements.append(Spacer(1, 5*mm))

        # ════════════════════════════════════════════════════
        # v8.1: SEGUIMIENTO DE RECOMENDACIONES ANTERIORES (solo biweekly)
        # ════════════════════════════════════════════════════
        if is_biweekly:
            followup_elements = self._followup_section()
            if followup_elements:
                elements.extend(followup_elements)
                elements.append(Spacer(1, 3*mm))

        # ════════════════════════════════════════════════════
        # RECOMENDACIONES
        # ════════════════════════════════════════════════════
        elements.append(Paragraph('Recomendaciones Prioritarias', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))

        if is_biweekly:
            forecast = d.get('forecast_summary')
            if forecast and (forecast.get('heat_wave_risk') or forecast.get('frost_risk')
                             or forecast.get('drought_risk') or forecast.get('heavy_rain_risk')):
                elements.append(Paragraph(
                    f'<font color="{C["yellow"]}"><b>Las recomendaciones siguientes incorporan '
                    f'la previsión meteorológica de los próximos 7 días.</b></font>',
                    s['Body']
                ))
                elements.append(Spacer(1, 2*mm))

        elements.extend(self._recommendations())
        elements.append(Spacer(1, 5*mm))

        conclusion = self._get_narrative('conclusion', '')
        if conclusion:
            elements.append(CalloutBox(
                f'<b>Conclusión:</b> {conclusion}',
                s, accent='green', width=self.content_w
            ))
            elements.append(Spacer(1, 3*mm))

        # ════════════════════════════════════════════════════
        # ANEXO TÉCNICO
        # v8.0 FIX: CondPageBreak en vez de PageBreak forzado
        #           para evitar página en blanco
        # ════════════════════════════════════════════════════
        elements.append(CondPageBreak(80*mm))
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Anexo Técnico', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))
        elements.extend(self._annex())
        elements.append(Spacer(1, 5*mm))

        # ════════════════════════════════════════════════════
        # v8.2: GUÍA DE LECTURA (para lectores no técnicos)
        # ════════════════════════════════════════════════════
        elements.append(CondPageBreak(60*mm))
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Guía de Lectura del Informe', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))
        elements.extend(self._reading_guide())
        elements.append(Spacer(1, 5*mm))

        # ════════════════════════════════════════════════════
        # v8.2: FIRMA TÉCNICA + DISCLAIMER MEJORADO
        # ════════════════════════════════════════════════════
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 3*mm))
        elements.extend(self._signature_block())

        # ── Build ──
        def first_page(cvs, doc):
            self._draw_cover(cvs, doc)

        def later_pages(cvs, doc):
            self._header_footer(cvs, doc)

        doc.build(elements, onFirstPage=first_page, onLaterPages=later_pages)
        self.buffer.seek(0)
        return self.buffer.getvalue()


# ============================================================
# 7. PUBLIC API FUNCTION
# ============================================================

def generate_muorbita_report(data: Dict[str, Any]) -> Dict[str, Any]:
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
            'version': '8.2',
            'images_used': list(generator.png_map.keys()) if generator.png_map else ['matplotlib_fallback'],
            'has_narratives': bool(generator.narratives),
            'narrative_fields': list(generator.narratives.keys()) if generator.narratives else [],
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
# 8. CLI TEST
# ============================================================

if __name__ == '__main__':
    import sys

    test_data = {
        "job_id": "BW_TEST_V8",
        "client_name": "Jairo Mejías Reyes",
        "crop_type": "olivar",
        "analysis_type": "biweekly",
        "area_hectares": 20.0,
        "start_date": "2026-02-17",
        "end_date": "2026-03-19",
        "images_processed": 16,
        "latest_image_date": "2026-03-18",
        "ndvi_mean": 0.58, "ndvi_p10": 0.44, "ndvi_p50": 0.60,
        "ndvi_p90": 0.68, "ndvi_stddev": 0.076, "ndvi_zscore": 0.5,
        "ndwi_mean": 0.123, "ndwi_p10": 0.011, "ndwi_p50": 0.142, "ndwi_p90": 0.204,
        "evi_mean": 0.383, "evi_p10": 0.274, "evi_p50": 0.397, "evi_p90": 0.464,
        "ndci_mean": 0.278, "savi_mean": 0.383,
        "stress_area_ha": 0.14, "stress_area_pct": 0.7,
        "lst_mean_c": 0,  # ← BUG: MODIS no devolvió dato
        "heterogeneity": 0.24,

        # Weather ERA5
        "weather_tmax_mean": 18.8,
        "weather_tmax_max": 24.8,
        "weather_tmin_mean": 7.9,
        "weather_tmin_min": 3.2,
        "weather_heat_days": 0,
        "weather_frost_days": 0,
        "weather_gdd": 80,
        "weather_precip_total": 24.3,
        "weather_et_total": 48.1,
        "weather_water_balance": -23.9,
        "weather_rain_days": 6,
        "weather_soil_moisture": 0.39,

        # Deltas — simula el bug ×1000 para verificar fix
        "prev_ndvi_mean": 0.588,  # era 588 antes del fix upstream
        "prev_ndwi_mean": 0.124,
        "prev_stress_pct": 0.7,
        "prev_evi_mean": None,
        "baseline_ndvi": 0.59,

        # Forecast
        "forecast_summary": {
            "temp_max_7d": "24.8",
            "temp_min_7d": "10.2",
            "precip_7d_mm": "12.2",
            "heat_wave_risk": False,
            "frost_risk": False,
            "drought_risk": True,
            "heavy_rain_risk": False,
            "summary": "Tmax prevista 20.8 ºC, precip 12.2 mm en 7 días",
            "days_ahead": 16,  # ← BUG upstream, pero PDF siempre dice "7 días"
        },

        # Claude narratives
        "narratives": {
            "executive_summary": "El olivar mantiene un vigor normal con NDVI de 0.58, sin cambios significativos respecto al período anterior. El área bajo estrés permanece mínima (0.7%). El balance hídrico negativo de -23.9 mm y la previsión de riesgo de sequía requieren atención al manejo del riego. Las condiciones térmicas han sido favorables sin días de calor extremo ni heladas.",
            "changes_interpretation": "El NDVI se mantiene prácticamente estable con una variación mínima de -0.006 (-1.0%) respecto al período anterior, dentro del rango normal esperado para olivar. Esta estabilidad en el índice de vigor es coherente con las condiciones climáticas moderadas del período bisemanal.",
            "new_risks": "Se identifica riesgo de sequía en la previsión meteorológica próxima, con balance hídrico deficitario sostenido que podría intensificarse. No se detectan otros nuevos riesgos significativos en este período.",
            "forecast_narrative": "La previsión de 7 días indica temperaturas máximas de 24.8 ºC y precipitaciones limitadas de 12.2 mm, insuficientes para compensar el déficit hídrico acumulado. El riesgo de sequía confirmado requiere ajustar la estrategia de riego antes de que se intensifique el estrés hídrico en las próximas semanas.",
            "map_ndvi": "La distribución espacial del vigor muestra un patrón homogéneo con NDVI medio de 0.58 y baja heterogeneidad. La concentración del 80% de valores entre 0.44-0.68 indica uniformidad en el estado vegetativo sin cambios significativos respecto al anterior.",
            "map_ndwi": "El estado hídrico con NDWI de 0.12 refleja coherentemente el balance hídrico negativo. La distribución P10-P90 de 0.01-0.20 sugiere variabilidad moderada en el contenido de humedad foliar.",
            "map_evi": "La productividad fotosintética con EVI de 0.38 confirma la tendencia del NDVI, indicando actividad metabólica normal para olivar en esta época.",
            "map_ndci": "El NDCI de 0.28 sugiere niveles adecuados de clorofila, coherentes con el NDVI observado.",
            "temporal_analysis": "Durante el período bisemanal se registraron 16 imágenes válidas con tendencia estable del NDVI entre 0.46-0.62. El máximo de 0.62 el 11 de marzo indica buena respuesta vegetativa, con ligero descenso al final del período asociado al balance hídrico.",
            "climate_assessment": "Las condiciones climáticas han sido moderadas con Tmax de 18.8 ºC y Tmin de 7.9 ºC, sin eventos extremos. Los 80 GDD acumulados son apropiados para la época, aunque el déficit hídrico de -23.9 mm requiere compensación mediante riego.",
            "risk_hydric_level": "Moderado",
            "risk_hydric_text": "El NDWI de 0.12 y balance hídrico negativo indican inicio de estrés hídrico moderado. La previsión de sequía con precipitaciones limitadas (12.2 mm) agravará esta situación si no se incrementa el aporte hídrico artificial.",
            "risk_thermal_level": "Bajo",
            "risk_thermal_text": "Sin días de calor extremo ni heladas en el período analizado. Las temperaturas previstas de 24.8 ºC máximas se mantienen en rangos favorables.",
            "risk_heterogeneity_level": "Baja",
            "risk_heterogeneity_text": "La heterogeneidad P90-P10 de 0.24 indica uniformidad espacial adecuada. Esta homogeneidad facilita el manejo y sugiere condiciones equilibradas en toda la parcela.",
            "recommendations": [
                {
                    "title": "Incrementar frecuencia de riego preventivo",
                    "priority": "Alta",
                    "deadline_days": 3,
                    "trigger": "Balance hídrico -23.9 mm y previsión de riesgo de sequía",
                    "zone": "Toda la parcela",
                    "justification": "El déficit hídrico sostenido requiere compensación antes de que se intensifique el estrés"
                },
                {
                    "title": "Monitoreo semanal de humedad del suelo",
                    "priority": "Media",
                    "deadline_days": 7,
                    "trigger": "Humedad del suelo de 0.39 m³/m³ con tendencia descendente",
                    "zone": "Zonas representativas de la parcela",
                    "justification": "Control preventivo para optimizar la programación del riego"
                },
                {
                    "title": "Planificar análisis foliar nutricional",
                    "priority": "Baja",
                    "deadline_days": 14,
                    "trigger": "NDCI 0.28 estable — ventana de evaluación nutricional",
                    "zone": "Muestreo representativo",
                    "justification": "Aprovechar condiciones estables para evaluación nutricional de base"
                }
            ],
            "conclusion": "El olivar presenta condiciones estables con vigor normal, requiriendo principalmente atención al manejo hídrico preventivo. Recomendamos revisión en 15 días para evaluar respuesta a las medidas de riego implementadas.",
            "prev_actions_followup": [
                {"title": "Incrementar frecuencia de riego preventivo", "status": "En curso", "observed_result": "NDWI estable en 0.12, sin deterioro adicional", "next_step": "Mantener riego incrementado 7 días más"},
                {"title": "Monitoreo semanal de humedad del suelo", "status": "Completada", "observed_result": "Humedad 0.39 m³/m³ confirmada en campo", "next_step": "Ninguna"},
                {"title": "Planificar análisis foliar nutricional", "status": "No iniciada", "observed_result": "Sin datos — pendiente de programar", "next_step": "Programar muestreo en próximos 14 días"}
            ]
        },

        "time_series": [
            {"date": "2026-02-21", "ndvi": 0.48, "ndwi": 0.10, "evi": 0.30},
            {"date": "2026-02-25", "ndvi": 0.50, "ndwi": 0.11, "evi": 0.32},
            {"date": "2026-03-01", "ndvi": 0.54, "ndwi": 0.12, "evi": 0.35},
            {"date": "2026-03-05", "ndvi": 0.56, "ndwi": 0.12, "evi": 0.36},
            {"date": "2026-03-09", "ndvi": 0.60, "ndwi": 0.13, "evi": 0.38},
            {"date": "2026-03-11", "ndvi": 0.62, "ndwi": 0.14, "evi": 0.39},
            {"date": "2026-03-13", "ndvi": 0.60, "ndwi": 0.13, "evi": 0.38},
            {"date": "2026-03-17", "ndvi": 0.58, "ndwi": 0.12, "evi": 0.37},
        ],

        "png_images": [],
    }

    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            test_data = json.load(f)

    result = generate_muorbita_report(test_data)

    if result['success']:
        out_path = f"/tmp/{result['filename']}"
        with open(out_path, 'wb') as f:
            f.write(base64.b64decode(result['pdf_base64']))
        print(f"✅ PDF v8.2 generado: {out_path} ({result['pdf_size']:,} bytes)")
        print(f"   Imágenes: {result['images_used']}")
        print(f"   Narrativas: {result['has_narratives']} ({len(result['narrative_fields'])} campos)")
    else:
        print(f"❌ Error: {result['error']}")
        print(result.get('traceback', ''))
