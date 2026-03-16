"""
Mu.Orbita PDF Report Generator v7.0
====================================
v7.0: Soporte bisemanal completo. Layout diferenciado por analysis_type.
      Tabla de cambios vs período anterior, forecast alert, nuevos riesgos.
      Baseline 100% idéntico a v6.0.

Changelog:
- v3.2: Key aliases para mapeo GEE → PDF
- v4.0: Carga imágenes desde BD por job_id
- v5.0: Nuevo orden de secciones, 4 mapas, fix gauge
- v6.0: ELIMINADA sección "Análisis Agronómico" duplicada.
        Narrativas Claude distribuidas en cada sección visual.
        Nueva tabla clima ERA5. Riesgos con texto interpretativo.
        Recomendaciones estructuradas desde JSON. VRA analysis.
        PDF de 10 → 7 páginas.
- v7.0: Soporte bisemanal. Nuevos métodos: _delta_table, _forecast_alert_box,
        _biweekly_changes_section. generate() ramifica por analysis_type.
        Baseline path idéntico a v6.0.

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
    """Format numérico seguro — devuelve fallback si es None/NaN/0."""
    if val is None or val == 0:
        return fallback
    try:
        return f"{float(val):.{decimals}f}{suffix}"
    except:
        return fallback


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
        # Background
        c.setFillColor(hex_color('white'))
        c.setStrokeColor(hex_color('cream_dark'))
        c.setLineWidth(0.5)
        c.roundRect(0, 0, w, h, 3, fill=True, stroke=True)
        # Left accent bar
        c.setFillColor(self.border_color)
        c.rect(0, 0, 3*mm, h, fill=True, stroke=False)
        # Text
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
    ax.set_title('Evolución Temporal de Índices', pad=10)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=10))
    plt.xticks(rotation=30, ha='right')
    ax.set_ylim(-0.15, 1.0)
    ax.legend(loc='upper right', fontsize=8, framealpha=0.9, edgecolor=C['cream_dark'])
    ax.grid(True, alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()
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
            # Fallback: campos sueltos en data
            for key in ['executive_summary', 'integrated_interpretation',
                        'map_ndvi', 'map_ndwi', 'map_evi', 'map_ndci',
                        'temporal_analysis', 'climate_assessment',
                        'risk_hydric_level', 'risk_hydric_text',
                        'risk_thermal_level', 'risk_thermal_text',
                        'risk_heterogeneity_level', 'risk_heterogeneity_text',
                        'vra_analysis', 'recommendations', 'conclusion']:
                if key in data and data[key]:
                    self.narratives[key] = data[key]

        if self.narratives:
            print(f"✅ PDF v7.0: {len(self.narratives)} narrative fields from Claude")
        else:
            print("⚠️ PDF v7.0: No narratives — using auto-generated text")

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
            print(f"✅ PDF v7.0: png_map con {len(self.png_map)} imágenes: {list(self.png_map.keys())}")
        else:
            print("⚠️ PDF v7.0: png_map VACÍO — se usarán gráficos matplotlib")

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
        """Obtiene narrativa de Claude con fallback."""
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

        card_x = self.M + 8*mm
        card_w = self.W - 2*self.M - 16*mm
        card_h = 80*mm
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
            row_y -= 9*mm

        cvs.setFillColor(hex_color('text_light'))
        cvs.setFont('Helvetica', 9)
        cvs.drawCentredString(self.W/2, card_y - 10*mm,
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

        # ── Helper: format value or show '—' if missing/zero ──
        def fv(val, decimals=2):
            """Format value: show number or '—' if None/0/missing."""
            if val is None or val == 0 or val == '—':
                return '—'
            try:
                return f"{float(val):.{decimals}f}"
            except (ValueError, TypeError):
                return '—'

        # ── EVI interpretation ──
        evi_m = d.get('evi_mean', 0) or 0
        if evi_m >= 0.35:
            evi_interp = 'Productividad alta'
        elif evi_m >= 0.25:
            evi_interp = 'Productividad moderada'
        elif evi_m > 0:
            evi_interp = 'Productividad baja'
        else:
            evi_interp = '—'

        # ── NDCI interpretation ──
        ndci_m = d.get('ndci_mean', 0) or 0
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

        # Buscar datos en múltiples ubicaciones posibles
        tmax = d.get('weather_tmax_mean') or self.narratives.get('weather_tmax_mean')
        precip = d.get('weather_precip_total') or self.narratives.get('weather_precip_total')
        balance = d.get('weather_water_balance') or self.narratives.get('weather_water_balance')
        gdd = d.get('weather_gdd') or d.get('weather_gdd_base10')
        heat = d.get('weather_heat_days', 0)
        frost = d.get('weather_frost_days', 0)
        et = d.get('weather_et_total')
        rain_days = d.get('weather_rain_days', 0)
        lst = d.get('lst_mean_c', 0)

        # Si no hay ningún dato ERA5, solo mostrar LST
        has_era5 = any(v is not None and v != 0 for v in [tmax, precip, balance, gdd])

        rows_data = [
            ['Parámetro', 'Valor', 'Interpretación'],
        ]

        if lst:
            rows_data.append(['LST media (MODIS)', f'{lst:.1f} ºC', 'Temperatura superficial del cultivo'])

        if has_era5:
            if tmax:
                rows_data.append(['Tmax media (ERA5)', f'{float(tmax):.1f} ºC', 'Temperatura máxima promedio aire'])
            if precip:
                rows_data.append(['Precipitación total', f'{float(precip):.1f} mm ({rain_days} días)', 'Aporte hídrico del período'])
            if et:
                rows_data.append(['Evapotranspiración', f'{float(et):.1f} mm', 'Demanda hídrica del cultivo'])
            if balance is not None:
                bal_val = float(balance)
                bal_interp = 'Superávit hídrico' if bal_val > 0 else 'Déficit hídrico'
                rows_data.append(['Balance hídrico (P-ET)', f'{bal_val:+.1f} mm', bal_interp])
            if heat > 0:
                rows_data.append(['Días Tmax ≥ 35 ºC', str(heat), 'Estrés térmico acumulado'])
            if frost > 0:
                rows_data.append(['Días helada (Tmin ≤ 0 ºC)', str(frost), 'Riesgo de daño por frío'])
            if gdd:
                rows_data.append(['GDD acumulados (base 10 ºC)', f'{float(gdd):.0f}', 'Desarrollo fenológico acumulado'])

        if len(rows_data) < 2:
            return None

        data = []
        for r_idx, row in enumerate(rows_data):
            tr = []
            for c_idx, cell in enumerate(row):
                st = s['TableHeader'] if r_idx == 0 else (s['TableCellLeft'] if c_idx in [0, 2] else s['TableCell'])
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

    # ── v6.0: Risk Table with narrative texts ──
    def _risk_table(self) -> Table:
        d = self.d
        s = self.styles

        ndwi_m = d.get('ndwi_mean', 0)
        ndvi_m = d.get('ndvi_mean', 0)
        hetero = d.get('ndvi_p90', 0) - d.get('ndvi_p10', 0)

        # Get levels from Claude narratives or auto-calculate
        h_lvl = self._get_narrative('risk_hydric_level', '')
        t_lvl = self._get_narrative('risk_thermal_level', '')
        hh_lvl = self._get_narrative('risk_heterogeneity_level', '')

        # Auto-calculate if no narratives
        if not h_lvl:
            if ndwi_m < 0:    h_lvl = 'Alto'
            elif ndwi_m<0.10: h_lvl = 'Moderado'
            else:             h_lvl = 'Bajo'

        if not t_lvl:
            heat = d.get('weather_heat_days', 0)
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

        h_text = self._get_narrative('risk_hydric_text', f'NDWI: {ndwi_m:.2f}')
        t_text = self._get_narrative('risk_thermal_text', f'LST: {d.get("lst_mean_c",0):.1f} ºC')
        hh_text = self._get_narrative('risk_heterogeneity_text', f'ΔP90-P10: {hetero:.2f}')

        header = [Paragraph(h, s['TableHeader']) for h in ['Riesgo', 'Nivel', 'Indicador', 'Evaluación']]
        data = [
            header,
            risk_row('Estrés hídrico', h_lvl, f'NDWI: {ndwi_m:.2f}', h_text),
            risk_row('Estrés térmico', t_lvl, f'LST: {d.get("lst_mean_c",0):.1f} ºC', t_text),
            risk_row('Heterogeneidad', hh_lvl, f'Δ: {hetero:.2f}', hh_text),
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
            # Fallback: generar recomendaciones automáticas
            elements.extend(self._auto_recommendations())

        return elements

    def _auto_recommendations(self) -> List:
        """Recomendaciones automáticas cuando Claude no devuelve JSON."""
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
        """Sección VRA con tabla + narrativa."""
        d = self.d
        s = self.styles
        elements = []

        vra_stats = d.get('vra_stats', [])
        vra_text = self._get_narrative('vra_analysis', '')

        if not vra_stats and not vra_text:
            return elements

        elements.append(Paragraph('Zonificación VRA (Aplicación Variable)', s['SubsectionTitle']))

        if vra_stats and isinstance(vra_stats, list) and len(vra_stats) > 0:
            header = [Paragraph(h, s['TableHeader']) for h in ['Zona', 'Superficie', 'NDVI medio', 'NDWI medio', 'Recomendación']]
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
            f'• MODIS LST: Temperatura superficial media {d.get("lst_mean_c",0):.1f} ºC<br/>'
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

    # ════════════════════════════════════════════════════════
    # v7.0: MÉTODOS BISEMANALES (no afectan baseline)
    # ════════════════════════════════════════════════════════

    def _delta_table(self) -> Optional[Table]:
        """
        Tabla de cambios vs período anterior para informes bisemanales.
        Retorna None si no hay datos de período anterior.
        """
        d = self.d
        s = self.styles

        prev_ndvi   = d.get('prev_ndvi_mean')
        prev_ndwi   = d.get('prev_ndwi_mean')
        prev_stress = d.get('prev_stress_pct')

        if prev_ndvi is None and prev_ndwi is None and prev_stress is None:
            return None

        curr_ndvi   = d.get('ndvi_mean', 0)
        curr_ndwi   = d.get('ndwi_mean', 0)
        curr_stress = d.get('stress_area_pct', 0)
        curr_evi    = d.get('evi_mean', 0)
        area_ha     = d.get('area_hectares', 0)

        def delta_fmt(curr, prev, decimals=2, is_pct=False):
            if prev is None or prev == 0:
                return '—', '—', 'black'
            delta     = curr - prev
            delta_pct = (delta / abs(prev)) * 100 if prev != 0 else 0
            sign      = '+' if delta >= 0 else ''
            trend     = '⬆' if delta > 0.005 else ('⬇' if delta < -0.005 else '➡')
            color     = 'green' if delta >= 0 else 'red'
            if is_pct:
                color = 'red' if delta > 0.5 else ('green' if delta < -0.5 else 'black')
            fmt_delta = f"{sign}{delta:.{decimals}f} ({sign}{delta_pct:.1f}%)"
            return fmt_delta, trend, color

        ndvi_delta,   ndvi_trend,   ndvi_color   = delta_fmt(curr_ndvi,   prev_ndvi)
        ndwi_delta,   ndwi_trend,   ndwi_color   = delta_fmt(curr_ndwi,   prev_ndwi, 3)
        stress_delta, stress_trend, stress_color = delta_fmt(curr_stress, prev_stress, 1, is_pct=True)

        def fv(val, decimals=2):
            if val is None: return '—'
            try: return f"{float(val):.{decimals}f}"
            except: return '—'

        rows_data = [
            ['Métrica', 'Período Anterior', 'Período Actual', 'Cambio', ''],
            ['NDVI (Vigor)',
             fv(prev_ndvi), fv(curr_ndvi), ndvi_delta, ndvi_trend],
            ['NDWI (Agua)',
             fv(prev_ndwi, 3), fv(curr_ndwi, 3), ndwi_delta, ndwi_trend],
            [f'Área estrés ({area_ha:.0f} ha)',
             f"{fv(prev_stress, 1)}%", f"{fv(curr_stress, 1)}%", stress_delta, stress_trend],
            ['EVI (Productiv.)',
             '—', fv(curr_evi, 3), '—', '—'],
        ]

        data = []
        for r_idx, row in enumerate(rows_data):
            tr = []
            for c_idx, cell in enumerate(row):
                if r_idx == 0:
                    st = s['TableHeader']
                elif c_idx == 0:
                    st = s['TableCellLeft']
                elif c_idx == 3:
                    color_map = {1: ndvi_color, 2: ndwi_color, 3: stress_color}
                    color = color_map.get(r_idx, 'black')
                    st = ParagraphStyle('DeltaCell',
                        parent=s['TableCell'],
                        textColor=colors.HexColor('#228B22') if color == 'green'
                                  else (colors.HexColor('#CC3300') if color == 'red'
                                  else colors.HexColor('#3E2B1D')),
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
        tbl.setStyle(TableStyle(style_cmds))
        return tbl

    def _forecast_alert_box(self) -> Optional[CalloutBox]:
        """
        Callout de alertas meteorológicas para los próximos 7 días.
        Retorna None si no hay alertas activas.
        """
        d = self.d
        s = self.styles

        forecast = d.get('forecast_summary') or d.get('narratives', {}).get('forecast_summary')
        if not forecast:
            return None

        alerts = []
        if forecast.get('heat_wave_risk'):  alerts.append('🌡️ Ola de calor prevista')
        if forecast.get('frost_risk'):      alerts.append('❄️ Riesgo de helada')
        if forecast.get('drought_risk'):    alerts.append('🏜️ Condiciones de sequía')
        if forecast.get('heavy_rain_risk'): alerts.append('🌧️ Lluvias intensas previstas')

        if not alerts:
            return None

        tmax    = forecast.get('temp_max_7d', 'N/A')
        tmin    = forecast.get('temp_min_7d', 'N/A')
        precip  = forecast.get('precip_7d_mm', 0)
        summary = forecast.get('summary', '')

        text = (
            f'<b>⚠️ ALERTAS METEOROLÓGICAS — PRÓXIMOS 7 DÍAS:</b> '
            + ' | '.join(alerts)
            + f'  ·  Tmax: {tmax} ºC · Tmin: {tmin} ºC · Precip: {precip} mm'
        )
        if summary:
            text += f'<br/>{summary}'

        return CalloutBox(text, s, accent='red', width=self.content_w)

    def _biweekly_changes_section(self) -> List:
        """
        Sección completa de cambios bisemanales:
        tabla de deltas + interpretación de Claude + nuevos riesgos + forecast.
        """
        d = self.d
        s = self.styles
        elements = []

        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Cambios vs Período Anterior', s['SubsectionTitle']))
        elements.append(Spacer(1, 2*mm))

        # Tabla de deltas
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

        # Interpretación de cambios (Claude)
        changes_text = self._get_narrative('changes_interpretation', '')
        if changes_text:
            elements.append(CalloutBox(
                f'<b>Interpretación de cambios:</b> {changes_text}',
                s, accent='green', width=self.content_w
            ))
            elements.append(Spacer(1, 3*mm))

        # Nuevos riesgos
        new_risks_text = self._get_narrative('new_risks', '')
        if new_risks_text and 'No se han detectado' not in new_risks_text:
            elements.append(Paragraph('Nuevos Riesgos Detectados', s['SubsectionTitle']))
            elements.append(Spacer(1, 1*mm))
            elements.append(CalloutBox(
                f'<b>⚠️ Nuevos riesgos:</b> {new_risks_text}',
                s, accent='red', width=self.content_w
            ))
            elements.append(Spacer(1, 3*mm))
        else:
            elements.append(Paragraph(
                f'<font color="{C["green"]}">✅ No se han detectado nuevos riesgos significativos en este período.</font>',
                s['Body']
            ))
            elements.append(Spacer(1, 3*mm))

        # Forecast alert
        forecast_box = self._forecast_alert_box()
        if forecast_box:
            elements.append(Paragraph('Previsión Meteorológica — Próximos 7 días', s['SubsectionTitle']))
            elements.append(Spacer(1, 1*mm))
            elements.append(forecast_box)

            forecast_narrative = self._get_narrative('forecast_narrative', '')
            if forecast_narrative:
                elements.append(Spacer(1, 2*mm))
                elements.append(CalloutBox(
                    f'<b>Impacto agronómico previsto:</b> {forecast_narrative}',
                    s, accent='yellow', width=self.content_w
                ))
            elements.append(Spacer(1, 3*mm))

        return elements

    # =====================================================
    # MAIN BUILD METHOD — v7.0
    # Baseline path idéntico a v6.0. Biweekly añade
    # sección de cambios en página 2 y omite VRA.
    # =====================================================
    def generate(self) -> bytes:
        """
        v7.0: Layout diferenciado por analysis_type.
        - BASELINE:  estructura completa idéntica a v6.0
        - BIWEEKLY:  página 2 incluye sección de cambios y forecast;
                     página 5 omite VRA
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
        # PAGE 2: RESUMEN EJECUTIVO
        # ════════════════════════════════════════════════════
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Indicadores Clave de Rendimiento', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 3*mm))
        elements.append(self._kpi_cards())
        elements.append(Spacer(1, 4*mm))

        exec_summary = self._get_narrative('executive_summary', '')
        if exec_summary:
            elements.append(CalloutBox(
                f'<b>Resumen ejecutivo:</b> {exec_summary}',
                s, accent='gold', width=self.content_w
            ))
            elements.append(Spacer(1, 3*mm))

        if is_biweekly:
            # ── BIWEEKLY: sección de cambios justo tras el resumen ──
            elements.extend(self._biweekly_changes_section())
            elements.append(PageBreak())
        else:
            # ── BASELINE: interpretación integrada (igual que v6.0) ──
            integrated = self._get_narrative('integrated_interpretation', '')
            if integrated:
                elements.append(CalloutBox(
                    f'<b>Interpretación integrada:</b> {integrated}',
                    s, accent='green', width=self.content_w
                ))
            else:
                # Fallback auto-generado — idéntico a v6.0
                ndvi_m    = d.get('ndvi_mean', 0)
                stress_pct= d.get('stress_area_pct', 0)
                hetero    = d.get('ndvi_p90', 0) - d.get('ndvi_p10', 0)

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

        # Detalle de Índices (ambos tipos)
        elements.append(Paragraph('Detalle de Índices Vegetativos', s['SubsectionTitle']))
        elements.append(self._detail_table())
        elements.append(Spacer(1, 4*mm))

        # Gauge NDVI (ambos tipos)
        gauge_bytes = generate_ndvi_gauge(
            d.get('ndvi_mean', 0.3), d.get('ndvi_p10', 0.2), d.get('ndvi_p90', 0.4))
        elements.append(self._real_or_generated('NDVI_DISTRIBUTION', gauge_bytes, 155, 42))

        # ════════════════════════════════════════════════════
        # PAGE 3: MAPAS CON INTERPRETACIÓN
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

        # Interpretación inline NDVI + NDWI
        map_ndvi_text = self._get_narrative('map_ndvi', '')
        map_ndwi_text = self._get_narrative('map_ndwi', '')
        if map_ndvi_text or map_ndwi_text:
            captions_row1 = []
            captions_row1.append(
                Paragraph(f'<b>NDVI:</b> {map_ndvi_text}' if map_ndvi_text else '',
                          s['MapCaption'])
            )
            captions_row1.append(
                Paragraph(f'<b>NDWI:</b> {map_ndwi_text}' if map_ndwi_text else '',
                          s['MapCaption'])
            )
            cap_tbl1 = Table([captions_row1], colWidths=[83*mm, 83*mm])
            cap_tbl1.setStyle(TableStyle([
                ('VALIGN',(0,0),(-1,-1),'TOP'),
                ('TOPPADDING',(0,0),(-1,-1), 1),
            ]))
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

        # Interpretación inline EVI + NDCI
        map_evi_text  = self._get_narrative('map_evi', '')
        map_ndci_text = self._get_narrative('map_ndci', '')
        if map_evi_text or map_ndci_text:
            captions_row2 = []
            captions_row2.append(
                Paragraph(f'<b>EVI:</b> {map_evi_text}'   if map_evi_text  else '', s['MapCaption'])
            )
            captions_row2.append(
                Paragraph(f'<b>NDCI:</b> {map_ndci_text}' if map_ndci_text else '', s['MapCaption'])
            )
            cap_tbl2 = Table([captions_row2], colWidths=[83*mm, 83*mm])
            cap_tbl2.setStyle(TableStyle([
                ('VALIGN',(0,0),(-1,-1),'TOP'),
                ('TOPPADDING',(0,0),(-1,-1), 1),
            ]))
            elements.append(cap_tbl2)

        elements.append(Spacer(1, 2*mm))

        # Map source note
        has_real_maps = any(
            alias in self.png_map
            for aliases in [self.KEY_ALIASES.get('NDVI_MAP', []), self.KEY_ALIASES.get('NDWI_MAP', [])]
            for alias in aliases
        )
        map_note = (
            '<b>Nota:</b> Mapas generados por Google Earth Engine sobre imagen satelital Sentinel-2 '
            'con la geometría real de la parcela.'
            if has_real_maps else
            '<b>Nota:</b> Mapas sintéticos de distribución espacial estimada. '
            'Contacte a soporte si no aparecen las imágenes satelitales reales.'
        )
        elements.append(Paragraph(f'<font size="8" color="{C["text_muted"]}">{map_note}</font>',
                                  s['Footnote']))

        # ════════════════════════════════════════════════════
        # PAGE 4: EVOLUCIÓN TEMPORAL + CLIMA
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
        # PAGE 5: RIESGOS + VRA (VRA solo en baseline)
        # ════════════════════════════════════════════════════
        elements.append(PageBreak())
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Evaluación de Riesgos', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))
        elements.append(self._risk_table())
        elements.append(Spacer(1, 5*mm))

        if not is_biweekly:
            # VRA solo en baseline
            vra_elements = self._vra_section()
            if vra_elements:
                elements.extend(vra_elements)
                elements.append(Spacer(1, 5*mm))

        # ════════════════════════════════════════════════════
        # PAGE 6: RECOMENDACIONES
        # ════════════════════════════════════════════════════
        elements.append(Paragraph('Recomendaciones Prioritarias', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))

        if is_biweekly:
            forecast = d.get('forecast_summary')
            if forecast and (forecast.get('heat_wave_risk') or forecast.get('frost_risk')
                             or forecast.get('drought_risk') or forecast.get('heavy_rain_risk')):
                elements.append(Paragraph(
                    f'<font color="{C["yellow"]}"><b>ℹ️ Las recomendaciones siguientes incorporan '
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
        # LAST PAGE: ANEXO TÉCNICO
        # ════════════════════════════════════════════════════
        elements.append(PageBreak())
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Anexo Técnico', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))
        elements.extend(self._annex())
        elements.append(Spacer(1, 8*mm))

        disclaimer = (
            '<i>Este informe ha sido generado automáticamente mediante análisis de imágenes '
            'satelitales. Las recomendaciones deben ser validadas por un técnico agrónomo antes '
            'de su implementación. Los datos satelitales están sujetos a disponibilidad y '
            'condiciones atmosféricas.</i>'
        )
        elements.append(Paragraph(f'<font size="7.5" color="{C["text_muted"]}">{disclaimer}</font>',
                                  s['Footnote']))

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
            'version': '7.0',
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
        "job_id": "MUORBITA_TEST_V7",
        "client_name": "Jairo Mejías Reyes",
        "crop_type": "viñedo",
        "analysis_type": "baseline",
        "area_hectares": 16.5,
        "start_date": "2025-09-14",
        "end_date": "2026-03-14",
        "images_processed": 43,
        "latest_image_date": "2026-03-11",
        "ndvi_mean": 0.60, "ndvi_p10": 0.50, "ndvi_p50": 0.60,
        "ndvi_p90": 0.68, "ndvi_stddev": 0.076, "ndvi_zscore": 2.27,
        "ndwi_mean": 0.08, "ndwi_p10": 0.024, "ndwi_p90": 0.138,
        "evi_mean": 0.31, "evi_p10": 0.259, "evi_p90": 0.363,
        "ndci_mean": 0.28, "savi_mean": 0.32,
        "stress_area_ha": 0.1, "stress_area_pct": 0.4,
        "lst_mean_c": 13.8, "lst_min_c": 13.7, "lst_max_c": 13.8,
        "heterogeneity": 0.18,

        # Weather ERA5
        "weather_tmax_mean": 18.5,
        "weather_tmin_mean": 6.2,
        "weather_heat_days": 0,
        "weather_frost_days": 3,
        "weather_gdd": 842.5,
        "weather_precip_total": 285.0,
        "weather_et_total": 195.0,
        "weather_water_balance": 90.0,
        "weather_rain_days": 28,

        # VRA stats
        "vra_stats": [
            {"zone": 0, "label": "Bajo vigor", "recommendation": "Dosis alta", "area_ha": 3.2, "ndvi_mean": 0.52, "ndwi_mean": 0.04, "evi_mean": 0.26},
            {"zone": 1, "label": "Vigor medio", "recommendation": "Dosis media", "area_ha": 7.8, "ndvi_mean": 0.60, "ndwi_mean": 0.08, "evi_mean": 0.31},
            {"zone": 2, "label": "Alto vigor", "recommendation": "Dosis baja", "area_ha": 5.5, "ndvi_mean": 0.68, "ndwi_mean": 0.12, "evi_mean": 0.36},
        ],

        # Claude narratives
        "narratives": {
            "executive_summary": "El viñedo de 16.5 ha presenta un estado vegetativo excelente con NDVI de 0.60, en el límite superior del rango típico para viñedo (0.40–0.60). Solo 0.1 ha (0.4%) muestra estrés. El NDWI de 0.08 indica déficit hídrico moderado que requiere ajuste de riego antes de primavera. Acción prioritaria: revisión del sistema de riego en los sectores con NDWI más bajo.",
            "integrated_interpretation": "Todos los índices son coherentes: el NDVI alto (0.60) se confirma con EVI robusto (0.31) y buen contenido de clorofila (NDCI 0.28). La única discrepancia es el NDWI moderado (0.08), que sugiere que pese al buen vigor actual, el contenido hídrico foliar empieza a descender. Con un balance hídrico positivo de +90 mm en el período, la reserva del suelo ha sido suficiente, pero la evapotranspiración creciente de primavera podría invertir esta situación.",
            "map_ndvi": "El vigor se distribuye de forma relativamente homogénea, con las zonas de mayor NDVI (0.68) concentradas en el sector central-norte de la parcela. El sector sur muestra valores más bajos (P10: 0.50), posiblemente asociados a diferencias de suelo o exposición.",
            "map_ndwi": "El estado hídrico muestra un patrón espacial similar al NDVI pero más marcado: las zonas con menor contenido de agua (NDWI 0.024) coinciden con las de menor vigor en el sector sur. No se detectan zonas con déficit severo (NDWI < 0).",
            "map_evi": "La productividad fotosintética (EVI 0.31) confirma el patrón de vigor del NDVI. Las zonas con EVI más alto (0.36) coinciden con las de mayor NDVI, confirmando un viñedo con buena capacidad productiva.",
            "map_ndci": "El contenido de clorofila (NDCI 0.28) es adecuado para la fase actual. No se detectan patrones de deficiencia nutricional significativa.",
            "temporal_analysis": "La serie temporal de 43 observaciones muestra una tendencia estable-ascendente desde septiembre 2025. El NDVI pasó de 0.55 en otoño a 0.60 actual, coherente con la activación vegetativa post-parada invernal.",
            "climate_assessment": "El período analizado acumuló 285 mm de precipitación frente a 195 mm de evapotranspiración, dejando un balance hídrico positivo de +90 mm. Se registraron 3 días de helada, sin impacto visible en el vigor.",
            "risk_hydric_level": "Moderado",
            "risk_hydric_text": "NDWI de 0.08 por debajo del umbral óptimo (0.20). Balance hídrico positivo (+90 mm) pero contenido hídrico foliar en descenso.",
            "risk_thermal_level": "Bajo",
            "risk_thermal_text": "Sin días de calor extremo y solo 3 heladas leves. LST media de 13.8 ºC normal para la época.",
            "risk_heterogeneity_level": "Media",
            "risk_heterogeneity_text": "Rango P10-P90 de 0.18 indica heterogeneidad moderada. Zona sur con menor vigor (NDVI 0.52) requiere atención diferenciada.",
            "vra_analysis": "Tres zonas: 5.5 ha alto vigor (sector norte, NDVI 0.68), 7.8 ha vigor medio (central, NDVI 0.60), 3.2 ha bajo vigor (sur, NDVI 0.52). La zona sur coincide con menor NDWI (0.04).",
            "recommendations": [
                {
                    "title": "Revisión y ajuste del riego en sector sur",
                    "priority": "Media",
                    "deadline_days": 7,
                    "trigger": "NDWI = 0.04 en zona de bajo vigor (3.2 ha, sector sur)",
                    "zone": "Sector sur — zona VRA 'Bajo vigor'",
                    "justification": "El déficit hídrico moderado puede agravarse con el aumento de temperaturas primaverales"
                },
                {
                    "title": "Fertilización diferenciada según zonificación VRA",
                    "priority": "Media",
                    "deadline_days": 14,
                    "trigger": "Heterogeneidad P90-P10 = 0.18 con 3 zonas diferenciadas",
                    "zone": "Toda la parcela — dosis según mapa VRA",
                    "justification": "Maximizar eficiencia del fertilizante según vigor diferencial"
                },
                {
                    "title": "Monitorización de brotación y estado hídrico",
                    "priority": "Baja",
                    "deadline_days": 14,
                    "trigger": "Inicio de fase vegetativa activa (842 GDD acumulados)",
                    "zone": "Toda la parcela",
                    "justification": "La transición a brotación es período crítico donde el vigor debe mantenerse"
                }
            ],
            "conclusion": "El viñedo está en excelente estado para afrontar la campaña 2026. Principal punto de atención: déficit hídrico moderado en sector sur. Próxima revisión en 14 días."
        },

        "time_series": [
            {"date": "2025-04-01", "ndvi": 0.35, "ndwi": 0.05, "evi": 0.20},
            {"date": "2025-05-01", "ndvi": 0.50, "ndwi": 0.10, "evi": 0.28},
            {"date": "2025-06-01", "ndvi": 0.62, "ndwi": 0.15, "evi": 0.33},
            {"date": "2025-07-01", "ndvi": 0.70, "ndwi": 0.18, "evi": 0.36},
            {"date": "2025-08-01", "ndvi": 0.65, "ndwi": 0.12, "evi": 0.34},
            {"date": "2025-09-01", "ndvi": 0.55, "ndwi": 0.08, "evi": 0.29},
            {"date": "2025-10-01", "ndvi": 0.48, "ndwi": 0.06, "evi": 0.25},
            {"date": "2025-11-01", "ndvi": 0.42, "ndwi": 0.05, "evi": 0.22},
            {"date": "2025-12-01", "ndvi": 0.40, "ndwi": 0.04, "evi": 0.21},
            {"date": "2026-01-01", "ndvi": 0.45, "ndwi": 0.06, "evi": 0.24},
            {"date": "2026-02-01", "ndvi": 0.55, "ndwi": 0.07, "evi": 0.28},
            {"date": "2026-03-11", "ndvi": 0.60, "ndwi": 0.08, "evi": 0.31},
        ],

        "png_images": [],
        "markdown_analysis": ""
    }

    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            test_data = json.load(f)

    result = generate_muorbita_report(test_data)

    if result['success']:
        out_path = f"/tmp/{result['filename']}"
        with open(out_path, 'wb') as f:
            f.write(base64.b64decode(result['pdf_base64']))
        print(f"✅ PDF v7.0 generado: {out_path} ({result['pdf_size']:,} bytes)")
        print(f"   Imágenes: {result['images_used']}")
        print(f"   Narrativas: {result['has_narratives']} ({len(result['narrative_fields'])} campos)")
    else:
        print(f"❌ Error: {result['error']}")
        print(result.get('traceback', ''))
