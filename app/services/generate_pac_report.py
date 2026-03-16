"""
Mu.Orbita PAC Report Generator v1.0
=====================================
Genera informes de conformidad PAC (Política Agrícola Común).
Completamente separado del generate_pdf_report.py — no afecta informes agronómicos.

Tipos de informe PAC:
  - pac_inspeccion: Generado bajo demanda para inspecciones
  - pac_anual: Generado automáticamente en febrero

Autor: Mu.Orbita
Fecha: 2026-03
"""

import io
import base64
from datetime import datetime, date
from typing import Optional, List, Dict, Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, Flowable
)


# ── Corporate palette (same as main PDF) ──
C = {
    'brown_dark':   '#3E2B1D',
    'brown':        '#5C4033',
    'gold':         '#9E7E46',
    'gold_light':   '#C4A265',
    'cream':        '#F9F7F2',
    'cream_dark':   '#E6DDD0',
    'white':        '#FFFFFF',
    'text':         '#3E2B1D',
    'text_light':   '#7A7A7A',
    'text_muted':   '#AAAAAA',
    'green':        '#4B7F3A',
    'green_bg':     '#E8F0E4',
    'yellow':       '#B8860B',
    'red':          '#A63D2F',
    'table_header': '#8B7B62',
    'cover_band':   '#EDE6DA',
    'pac_green':    '#2E7D32',
    'pac_green_bg': '#E8F5E9',
    'pac_red':      '#C62828',
    'pac_red_bg':   '#FFEBEE',
    'pac_yellow':   '#F57F17',
    'pac_yellow_bg':'#FFFDE7',
    'pac_blue':     '#1565C0',
    'pac_blue_bg':  '#E3F2FD',
}

def hex_color(key):
    return colors.HexColor(C[key])

def fmt_date(d):
    if not d: return '—'
    try:
        if isinstance(d, (date, datetime)):
            return d.strftime('%d/%m/%Y')
        return datetime.strptime(str(d)[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
    except:
        return str(d)

def crop_label(ct):
    m = {'olive':'Olivar','olivar':'Olivar','olivo':'Olivar',
         'vineyard':'Viñedo','viña':'Viñedo','vid':'Viñedo','viñedo':'Viñedo',
         'almond':'Almendro','almendro':'Almendro'}
    return m.get(str(ct).lower(), str(ct).capitalize() if ct else 'Cultivo')


# ─────────────────────────────────────────────
# CUSTOM FLOWABLES
# ─────────────────────────────────────────────

class SectionDivider(Flowable):
    def __init__(self, width=170*mm, color='gold_light'):
        Flowable.__init__(self)
        self._width = width
        self._color = color
    def wrap(self, aw, ah): return self._width, 1.5*mm
    def draw(self):
        self.canv.setStrokeColor(hex_color(self._color))
        self.canv.setLineWidth(1.5)
        self.canv.line(0, 0, self._width, 0)


class PacConditionCard(Flowable):
    """Tarjeta PAC con resultado CONFORME / NO CONFORME / SIN DATOS."""

    STATUS_CONFIG = {
        'conforme':     {'label': '✓ CONFORME',      'text_color': '#2E7D32', 'bg': '#E8F5E9', 'border': '#2E7D32'},
        'no_conforme':  {'label': '✗ NO CONFORME',   'text_color': '#C62828', 'bg': '#FFEBEE', 'border': '#C62828'},
        'advertencia':  {'label': '⚠ ADVERTENCIA',   'text_color': '#F57F17', 'bg': '#FFFDE7', 'border': '#F57F17'},
        'sin_datos':    {'label': '— SIN DATOS',      'text_color': '#7A7A7A', 'bg': '#F9F7F2', 'border': '#AAAAAA'},
    }

    def __init__(self, number, condition_name, status, value_str,
                 detail, regulation_ref, styles, width=170*mm):
        Flowable.__init__(self)
        cfg = self.STATUS_CONFIG.get(status, self.STATUS_CONFIG['sin_datos'])
        self._width = width
        self._cfg = cfg

        text = (
            f'<b>{number}. {condition_name}</b>  '
            f'<font color="{cfg["text_color"]}"><b>{cfg["label"]}</b></font><br/>'
            f'<font size="9">'
            f'<b>Valor observado:</b> {value_str}<br/>'
            f'<b>Evaluación:</b> {detail}<br/>'
            f'<b>Referencia normativa:</b> {regulation_ref}'
            f'</font>'
        )
        self._para = Paragraph(text, styles['Body'])
        w, h = self._para.wrap(width - 12*mm, 500*mm)
        self._height = h + 10*mm

    def wrap(self, aw, ah):
        return self._width, self._height

    def draw(self):
        c = self.canv
        w, h = self._width, self._height
        c.setFillColor(colors.HexColor(self._cfg['bg']))
        c.setStrokeColor(colors.HexColor(self._cfg['border']))
        c.setLineWidth(1)
        c.roundRect(0, 0, w, h, 4, fill=True, stroke=True)
        c.setFillColor(colors.HexColor(self._cfg['border']))
        c.rect(0, 0, 3.5*mm, h, fill=True, stroke=False)
        self._para.wrap(w - 12*mm, h)
        self._para.drawOn(c, 6*mm, 4*mm)


# ─────────────────────────────────────────────
# STYLES
# ─────────────────────────────────────────────

def get_pac_styles():
    base = getSampleStyleSheet()

    def _add(name, **kw):
        if name in [s.name for s in base.byName.values()]:
            return
        parent = kw.pop('parent', 'Normal')
        base.add(ParagraphStyle(name, parent=base[parent], **kw))

    _add('PacTitle', fontName='Helvetica-Bold', fontSize=22,
         textColor=hex_color('brown_dark'), alignment=TA_LEFT, leading=28)
    _add('PacSubtitle', fontName='Helvetica', fontSize=13,
         textColor=hex_color('brown'), alignment=TA_LEFT, leading=16)
    _add('SectionTitle', fontName='Helvetica-Bold', fontSize=13,
         textColor=hex_color('brown_dark'), spaceBefore=7*mm, spaceAfter=3*mm)
    _add('SubsectionTitle', fontName='Helvetica-Bold', fontSize=10.5,
         textColor=hex_color('brown'), spaceBefore=4*mm, spaceAfter=2*mm)
    _add('Body', fontName='Helvetica', fontSize=10,
         textColor=hex_color('text'), leading=15, alignment=TA_JUSTIFY, spaceAfter=3*mm)
    _add('BodySmall', fontName='Helvetica', fontSize=9,
         textColor=hex_color('text'), leading=13, spaceAfter=2*mm)
    _add('Footnote', fontName='Helvetica', fontSize=7.5,
         textColor=hex_color('text_muted'), leading=10, alignment=TA_LEFT)
    _add('TableHeader', fontName='Helvetica-Bold', fontSize=9,
         textColor=hex_color('white'), alignment=TA_CENTER)
    _add('TableCell', fontName='Helvetica', fontSize=9,
         textColor=hex_color('text'), alignment=TA_CENTER)
    _add('TableCellLeft', fontName='Helvetica', fontSize=9,
         textColor=hex_color('text'), alignment=TA_LEFT)
    _add('SignatureLabel', fontName='Helvetica', fontSize=9,
         textColor=hex_color('text_light'), alignment=TA_CENTER)
    _add('PacBadge', fontName='Helvetica-Bold', fontSize=11,
         alignment=TA_CENTER, leading=14)
    _add('Disclaimer', fontName='Helvetica-Oblique', fontSize=8,
         textColor=hex_color('text_muted'), leading=11, alignment=TA_JUSTIFY)

    return base


# ─────────────────────────────────────────────
# MAIN GENERATOR
# ─────────────────────────────────────────────

class PacReportGenerator:

    def __init__(self, data: Dict[str, Any]):
        self.d = data
        self.styles = get_pac_styles()
        self.buffer = io.BytesIO()
        self.W, self.H = A4
        self.M = 15*mm
        self.content_w = self.W - 2*self.M

    # ── Header / Footer ──
    def _header_footer(self, cvs, doc):
        cvs.saveState()
        # Header bar
        cvs.setFillColor(hex_color('cream'))
        cvs.rect(0, self.H - 20*mm, self.W, 20*mm, fill=True, stroke=False)
        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.8)
        cvs.line(0, self.H - 20*mm, self.W, self.H - 20*mm)
        # Logo
        cvs.setFillColor(hex_color('brown_dark'))
        cvs.setFont('Helvetica-Oblique', 15)
        cvs.drawString(self.M + 4*mm, self.H - 14*mm, 'Mu')
        mu_w = cvs.stringWidth('Mu', 'Helvetica-Oblique', 15)
        cvs.setFont('Helvetica-Bold', 15)
        cvs.drawString(self.M + 4*mm + mu_w, self.H - 14*mm, '.Orbita')
        # Right: PAC badge
        cvs.setFillColor(hex_color('pac_green'))
        cvs.setFont('Helvetica-Bold', 8)
        cvs.drawRightString(self.W - self.M - 4*mm, self.H - 13*mm, 'INFORME CONFORMIDAD PAC')
        # Footer
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
        d = self.d

        # Background
        cvs.setFillColor(hex_color('cream'))
        cvs.rect(0, 0, self.W, self.H, fill=True, stroke=False)

        # Top line
        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.8)
        cvs.line(self.M + 8*mm, self.H - 30*mm, self.W - self.M - 8*mm, self.H - 30*mm)

        # Logo
        cvs.setFillColor(hex_color('brown_dark'))
        cvs.setFont('Helvetica-Oblique', 26)
        cvs.drawString(self.M + 8*mm, self.H - 22*mm, 'Mu')
        mu_w = cvs.stringWidth('Mu', 'Helvetica-Oblique', 26)
        cvs.setFont('Helvetica-Bold', 26)
        cvs.drawString(self.M + 8*mm + mu_w, self.H - 22*mm, '.Orbita')

        # PAC badge top right
        cvs.setFillColor(hex_color('pac_green'))
        badge_x = self.W - self.M - 8*mm - 55*mm
        cvs.roundRect(badge_x, self.H - 26*mm, 55*mm, 10*mm, 3, fill=True, stroke=False)
        cvs.setFillColor(hex_color('white'))
        cvs.setFont('Helvetica-Bold', 9)
        cvs.drawCentredString(badge_x + 27.5*mm, self.H - 20*mm, 'DOCUMENTO PAC')

        # Green band
        band_y = self.H - 95*mm
        band_h = 55*mm
        cvs.setFillColor(colors.HexColor('#2E7D32'))
        cvs.rect(0, band_y, self.W, band_h, fill=True, stroke=False)

        cvs.setFillColor(hex_color('white'))
        cvs.setFont('Helvetica-Bold', 24)
        cvs.drawString(self.M + 8*mm, band_y + band_h - 18*mm, 'Informe de Conformidad PAC')

        report_type = d.get('report_type', 'pac_inspeccion')
        year = d.get('year', datetime.now().year)
        subtype_label = f'Inspección Bajo Demanda — {year}' if report_type == 'pac_inspeccion' else f'Informe Anual PAC — {year}'
        cvs.setFont('Helvetica', 13)
        cvs.setFillColor(colors.Color(1, 1, 1, 0.85))
        cvs.drawString(self.M + 8*mm, band_y + band_h - 34*mm, subtype_label)

        cvs.setStrokeColor(colors.Color(1, 1, 1, 0.4))
        cvs.setLineWidth(2)
        cvs.line(self.M + 8*mm, band_y + band_h - 40*mm, self.M + 55*mm, band_y + band_h - 40*mm)

        # Data card
        card_x = self.M + 8*mm
        card_w = self.W - 2*self.M - 16*mm
        card_h = 85*mm
        card_y = band_y - 12*mm - card_h

        cvs.setFillColor(hex_color('white'))
        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.8)
        cvs.roundRect(card_x, card_y, card_w, card_h, 6, fill=True, stroke=True)

        cvs.setFillColor(hex_color('gold'))
        cvs.setFont('Helvetica-Bold', 8.5)
        cvs.drawString(card_x + 14*mm, card_y + card_h - 13*mm, 'DATOS DE LA EXPLOTACIÓN')

        cvs.setStrokeColor(hex_color('cream_dark'))
        cvs.setLineWidth(0.4)
        cvs.line(card_x + 10*mm, card_y + card_h - 17*mm,
                 card_x + card_w - 10*mm, card_y + card_h - 17*mm)

        meta = [
            ('Titular', d.get('client_name', 'N/A')),
            ('Parcela', d.get('parcel_name', 'N/A')),
            ('Cultivo', crop_label(d.get('crop_type', ''))),
            ('Superficie', f"{d.get('area_hectares', 0):.1f} ha"),
            ('Municipio', d.get('municipality', d.get('province', 'Andalucía, España'))),
            ('Período evaluado', f"{fmt_date(d.get('period_start'))}  →  {fmt_date(d.get('period_end'))}"),
            ('Referencia informe', d.get('report_ref', 'N/A')),
        ]

        row_y = card_y + card_h - 27*mm
        for label, value in meta:
            cvs.setFillColor(hex_color('text_light'))
            cvs.setFont('Helvetica', 9)
            cvs.drawString(card_x + 14*mm, row_y, label)
            cvs.setFillColor(hex_color('brown_dark'))
            cvs.setFont('Helvetica-Bold', 9)
            val_str = value if len(str(value)) < 50 else str(value)[:47] + '...'
            cvs.drawRightString(card_x + card_w - 14*mm, row_y, val_str)
            row_y -= 2.5*mm
            cvs.setStrokeColor(hex_color('cream_dark'))
            cvs.setLineWidth(0.3)
            cvs.line(card_x + 14*mm, row_y, card_x + card_w - 14*mm, row_y)
            row_y -= 8*mm

        # Date and reference bottom
        cvs.setFillColor(hex_color('text_light'))
        cvs.setFont('Helvetica', 8.5)
        cvs.drawCentredString(self.W/2, card_y - 10*mm,
            f'Generado el {datetime.now().strftime("%d/%m/%Y")} por Mu.Orbita Inteligencia Satelital')

        cvs.setFillColor(hex_color('text_muted'))
        cvs.setFont('Helvetica', 7.5)
        cvs.drawCentredString(self.W/2, 15*mm,
            f'© {datetime.now().year} Mu.Orbita · info@muorbita.com · www.muorbita.com')

        cvs.restoreState()

    # ── KPI History Table ──
    def _kpi_history_table(self) -> Optional[Table]:
        s = self.styles
        kpi_records = self.d.get('kpi_records', [])
        if not kpi_records:
            return None

        def ndvi_label(v):
            if v is None: return '—'
            if v >= 0.45: return f'{v:.3f} ✓'
            if v >= 0.25: return f'{v:.3f} ⚠'
            return f'{v:.3f} ✗'

        def ndwi_label(v):
            if v is None: return '—'
            if v >= 0.10: return f'{v:.3f} ✓'
            return f'{v:.3f} ⚠'

        header = [Paragraph(h, s['TableHeader']) for h in
                  ['Fecha observación', 'NDVI', 'NDWI', 'Estrés área (%)', 'Fuente']]
        rows = [header]
        for k in kpi_records:
            ndvi_v = float(k['ndvi_mean']) if k.get('ndvi_mean') else None
            ndwi_v = float(k['ndwi_mean']) if k.get('ndwi_mean') else None
            stress = float(k['stress_area_pct']) if k.get('stress_area_pct') else None

            rows.append([
                Paragraph(fmt_date(k.get('observation_date', '')), s['TableCell']),
                Paragraph(ndvi_label(ndvi_v), s['TableCell']),
                Paragraph(ndwi_label(ndwi_v), s['TableCell']),
                Paragraph(f'{stress:.1f}%' if stress is not None else '—', s['TableCell']),
                Paragraph(k.get('satellite_source', 'Sentinel-2'), s['TableCell']),
            ])

        cw = [38*mm, 28*mm, 28*mm, 32*mm, 44*mm]
        tbl = Table(rows, colWidths=cw)
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), hex_color('table_header')),
            ('TEXTCOLOR', (0, 0), (-1, 0), hex_color('white')),
            ('GRID', (0, 0), (-1, -1), 0.5, hex_color('cream_dark')),
            ('BOX', (0, 0), (-1, -1), 1, hex_color('table_header')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]
        for r in range(2, len(rows), 2):
            style_cmds.append(('BACKGROUND', (0, r), (-1, r), hex_color('cream')))
        tbl.setStyle(TableStyle(style_cmds))
        return tbl

    # ── PAC Conditions Section ──
    def _pac_conditions(self) -> List:
        s = self.styles
        elements = []
        conditions = self.d.get('pac_conditions', [])

        if not conditions:
            elements.append(Paragraph(
                'No se han evaluado condiciones PAC — datos insuficientes.',
                s['Body']
            ))
            return elements

        for i, cond in enumerate(conditions, 1):
            status = cond.get('status', 'sin_datos')  # conforme | no_conforme | advertencia | sin_datos
            elements.append(PacConditionCard(
                number=i,
                condition_name=cond.get('name', ''),
                status=status,
                value_str=cond.get('value_str', '—'),
                detail=cond.get('detail', ''),
                regulation_ref=cond.get('regulation_ref', ''),
                styles=s,
                width=self.content_w,
            ))
            elements.append(Spacer(1, 4*mm))

        # Summary table
        total = len(conditions)
        conformes = sum(1 for c in conditions if c.get('status') == 'conforme')
        advertencias = sum(1 for c in conditions if c.get('status') == 'advertencia')
        no_conformes = sum(1 for c in conditions if c.get('status') == 'no_conforme')

        overall = 'CONFORME' if no_conformes == 0 and advertencias == 0 else \
                  ('CON ADVERTENCIAS' if no_conformes == 0 else 'NO CONFORME')
        overall_color = C['pac_green'] if overall == 'CONFORME' else \
                        (C['pac_yellow'] if 'ADVERTENCIAS' in overall else C['pac_red'])

        summary_text = (
            f'<b>Resultado global: <font color="{overall_color}">{overall}</font></b>  ·  '
            f'{conformes} condiciones conformes  ·  '
            f'{advertencias} advertencias  ·  '
            f'{no_conformes} no conformes'
        )
        from reportlab.platypus import Flowable as _F

        class SummaryBox(_F):
            def __init__(self_, text, w):
                _F.__init__(self_)
                self_._para = Paragraph(text, s['Body'])
                self_._width = w
                _, h = self_._para.wrap(w - 10*mm, 500*mm)
                self_._height = h + 8*mm
            def wrap(self_, aw, ah): return self_._width, self_._height
            def draw(self_):
                c = self_.canv
                w, h = self_._width, self_._height
                c.setFillColor(hex_color('cream'))
                c.roundRect(0, 0, w, h, 3, fill=True, stroke=False)
                c.setFillColor(colors.HexColor(overall_color))
                c.rect(0, 0, 3*mm, h, fill=True, stroke=False)
                self_._para.wrap(w - 10*mm, h)
                self_._para.drawOn(c, 5*mm, 3*mm)

        elements.append(SummaryBox(summary_text, self.content_w))
        return elements

    # ── Signature Section ──
    def _signature_section(self) -> List:
        s = self.styles
        elements = []

        sig_status  = self.d.get('signature_status', 'not_requested')
        sig_name    = self.d.get('agronomist_name', '')
        sig_college = self.d.get('agronomist_college', '')
        sig_date    = self.d.get('signature_date', '')
        report_ref  = self.d.get('report_ref', '')
        client_name = self.d.get('client_name', '')
        parcel_name = self.d.get('parcel_name', '')

        elements.append(Spacer(1, 6*mm))
        elements.append(Paragraph('Declaración de Conformidad', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 3*mm))

        declaration = (
            f'El presente informe de conformidad PAC (Ref. {report_ref}) ha sido generado '
            f'mediante análisis automatizado de imágenes satelitales Sentinel-2 de la parcela '
            f'<b>{parcel_name}</b>, titularidad de <b>{client_name}</b>, para el período '
            f'indicado en la portada. Los datos presentados provienen de Google Earth Engine '
            f'con resolución espacial de 10 m y han sido procesados mediante los algoritmos '
            f'certificados de Mu.Orbita Inteligencia Satelital.'
        )
        elements.append(Paragraph(declaration, s['Body']))
        elements.append(Spacer(1, 5*mm))

        # Signature area (3 columns: client, agronomist, Mu.Orbita seal)
        sig_col_w = self.content_w / 3 - 3*mm

        def sig_box(title, name='', subtitle='', signed=False):
            lines = [
                Paragraph(f'<b>{title}</b>', s['SignatureLabel']),
                Spacer(1, 12*mm),
            ]
            if signed and name:
                lines.append(Paragraph(f'<b>{name}</b>', s['SignatureLabel']))
                if subtitle:
                    lines.append(Paragraph(subtitle, s['SignatureLabel']))
            else:
                # Draw signature line placeholder
                lines.append(Paragraph('_' * 28, s['SignatureLabel']))
                lines.append(Paragraph(name or '(Firma y sello)', s['SignatureLabel']))
            return lines

        if sig_status == 'signed' and sig_name:
            agro_lines = sig_box(
                'Técnico Agrónomo', sig_name,
                f'Nº Colegiado: {sig_college}' if sig_college else 'Colegio Oficial Ingenieros Agrónomos',
                signed=True
            )
            agro_date = f'Firmado: {fmt_date(sig_date)}' if sig_date else ''
            sig_status_html = f'<font color="{C["pac_green"]}">✓ FIRMADO DIGITALMENTE</font>'
        elif sig_status == 'pending':
            agro_lines = sig_box('Técnico Agrónomo (pendiente)')
            agro_date = 'Firma pendiente — Mu.Orbita'
            sig_status_html = f'<font color="{C["pac_yellow"]}">⏳ FIRMA SOLICITADA</font>'
        else:
            agro_lines = sig_box('Técnico Agrónomo')
            agro_date = ''
            sig_status_html = f'<font color="{C["text_muted"]}">Firma no solicitada</font>'

        client_sig = Table([
            [Paragraph('<b>Titular de la explotación</b>', s['SignatureLabel'])],
            [Spacer(1, 12*mm)],
            [Paragraph('_' * 28, s['SignatureLabel'])],
            [Paragraph(client_name[:30], s['SignatureLabel'])],
            [Paragraph(f'Fecha: {datetime.now().strftime("%d/%m/%Y")}', s['SignatureLabel'])],
        ], colWidths=[sig_col_w])

        agro_sig = Table(
            [[el] for el in agro_lines] + [[Paragraph(agro_date, s['SignatureLabel'])]],
            colWidths=[sig_col_w]
        )

        seal_lines = [
            Paragraph('<b>Sello Mu.Orbita</b>', s['SignatureLabel']),
            Spacer(1, 3*mm),
            Paragraph(
                f'<font color="{C["pac_green"]}" size="11"><b>Mu.Orbita</b></font><br/>'
                f'<font size="8">Inteligencia Satelital Agrícola</font><br/>'
                f'<font size="8">info@muorbita.com</font>',
                s['SignatureLabel']
            ),
            Spacer(1, 3*mm),
            Paragraph(f'<font size="8">{sig_status_html}</font>', s['SignatureLabel']),
            Paragraph(f'<font size="7" color="{C["text_muted"]}">Ref: {report_ref}</font>', s['SignatureLabel']),
        ]
        seal_col = Table([[el] for el in seal_lines], colWidths=[sig_col_w])

        for tbl in [client_sig, agro_sig, seal_col]:
            tbl.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]))

        sig_table = Table(
            [[client_sig, agro_sig, seal_col]],
            colWidths=[sig_col_w + 3*mm, sig_col_w + 3*mm, sig_col_w + 3*mm]
        )
        sig_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.8, hex_color('cream_dark')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, hex_color('cream_dark')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(sig_table)

        elements.append(Spacer(1, 5*mm))
        disclaimer = (
            'Este informe ha sido generado automáticamente mediante análisis de imágenes '
            'satelitales y no constituye por sí solo una declaración oficial PAC. '
            'Para valor legal ante la Administración, debe ser complementado con la '
            'firma de un técnico agrónomo colegiado. Mu.Orbita ofrece este servicio '
            'a través de su red de agrónomos colaboradores — contacte info@muorbita.com.'
        )
        elements.append(Paragraph(disclaimer, s['Disclaimer']))

        return elements

    # ── Main Build ──
    def generate(self) -> bytes:
        d = self.d
        s = self.styles

        doc = SimpleDocTemplate(
            self.buffer, pagesize=A4,
            leftMargin=self.M, rightMargin=self.M,
            topMargin=25*mm, bottomMargin=16*mm
        )

        elements = []
        elements.append(PageBreak())

        # ─── PAGE 2: Datos históricos ───
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Historial de Observaciones Satelitales', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph(
            f'Período evaluado: <b>{fmt_date(d.get("period_start"))} — {fmt_date(d.get("period_end"))}</b>  ·  '
            f'Imágenes procesadas: <b>{len(d.get("kpi_records", []))}</b>  ·  '
            f'Fuente: <b>Sentinel-2 SR Harmonized (Google Earth Engine)</b>',
            s['BodySmall']
        ))
        elements.append(Spacer(1, 3*mm))

        kpi_tbl = self._kpi_history_table()
        if kpi_tbl:
            elements.append(kpi_tbl)
        else:
            elements.append(Paragraph('No hay registros de KPIs disponibles para el período.', s['Body']))

        elements.append(Spacer(1, 4*mm))
        elements.append(Paragraph(
            '✓ = dentro del umbral óptimo  ·  ⚠ = zona de atención  ·  ✗ = por debajo del umbral PAC',
            s['Footnote']
        ))

        # ─── PAGE 3: Evaluación PAC ───
        elements.append(PageBreak())
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph('Evaluación de Condiciones PAC', s['SectionTitle']))
        elements.append(SectionDivider(self.content_w))
        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph(
            'Las siguientes condiciones han sido evaluadas automáticamente a partir de '
            'los índices satelitales del período de referencia.',
            s['Body']
        ))
        elements.append(Spacer(1, 3*mm))
        elements.extend(self._pac_conditions())

        # ─── PAGE 4: Firma ───
        elements.append(PageBreak())
        elements.extend(self._signature_section())

        # ─── Technical annex (same page as signature if space) ───
        elements.append(Spacer(1, 6*mm))
        elements.append(Paragraph('Información Técnica', s['SubsectionTitle']))
        elements.append(SectionDivider(self.content_w, 'gold_light'))
        elements.append(Spacer(1, 2*mm))
        annex_text = (
            f'<b>Satélite:</b> Sentinel-2 SR Harmonized (ESA/Copernicus)  ·  '
            f'<b>Resolución:</b> 10 m (bandas B4, B8, B11, B5)  ·  '
            f'<b>Motor:</b> Google Earth Engine  ·  '
            f'<b>Máscara de nubes:</b> QA60 + SCL<br/>'
            f'<b>NDVI</b> = (NIR − Red) / (NIR + Red)  —  Umbral abandono: 0.25  —  Umbral eco-esquema olivar: 0.30<br/>'
            f'<b>NDWI</b> = (NIR − SWIR) / (NIR + SWIR)  —  Umbral estrés hídrico severo: 0.10<br/>'
            f'Ref. normativa: Reglamento (UE) 2021/2115 — Plan Estratégico PAC España 2023-2027'
        )
        elements.append(Paragraph(annex_text, s['BodySmall']))

        # Build
        def first_page(cvs, doc):
            self._draw_cover(cvs, doc)

        def later_pages(cvs, doc):
            self._header_footer(cvs, doc)

        doc.build(elements, onFirstPage=first_page, onLaterPages=later_pages)
        self.buffer.seek(0)
        return self.buffer.getvalue()


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def _evaluate_pac_conditions(kpi_records: List[Dict], crop_type: str) -> List[Dict]:
    """Evalúa las 3 condiciones PAC y devuelve lista de resultados."""
    if not kpi_records:
        return []

    # Sort by date, get last 2
    sorted_records = sorted(kpi_records, key=lambda x: str(x.get('observation_date', '')), reverse=True)
    latest   = sorted_records[0] if sorted_records else {}
    previous = sorted_records[1] if len(sorted_records) > 1 else None

    ndvi_latest  = float(latest.get('ndvi_mean', 0) or 0)
    ndwi_latest  = float(latest.get('ndwi_mean', 0) or 0)
    ndvi_prev    = float(previous.get('ndvi_mean', 0) or 0) if previous else None
    obs_date     = fmt_date(latest.get('observation_date', ''))
    is_olivar    = any(x in str(crop_type).lower() for x in ['oliv', 'olive'])

    conditions = []

    # ── Condición 1: Abandono de cultivo (NDVI < 0.25) ──
    two_consecutive = (ndvi_prev is not None and ndvi_prev < 0.25 and ndvi_latest < 0.25)
    if ndvi_latest < 0.25:
        status = 'no_conforme' if two_consecutive else 'advertencia'
        detail = (
            f'NDVI de {ndvi_latest:.3f} por debajo del umbral de actividad mínima (0.25). '
            + (f'El registro anterior ({ndvi_prev:.3f}) también fue inferior — patrón persistente.' if two_consecutive
               else 'Primera detección en este período.')
        )
    else:
        status = 'conforme'
        detail = f'NDVI de {ndvi_latest:.3f} supera el umbral mínimo de actividad (0.25). Cultivo activo confirmado.'

    conditions.append({
        'name': 'Actividad mínima del cultivo (anti-abandono)',
        'status': status,
        'value_str': f'NDVI = {ndvi_latest:.3f} (observación: {obs_date})',
        'detail': detail,
        'regulation_ref': 'Art. 31 Reg. (UE) 2021/2115 — Condicionalidad reforzada BCAM 1'
    })

    # ── Condición 2: Eco-esquema cubierta vegetal (solo olivar, NDVI < 0.30) ──
    if is_olivar:
        if ndvi_latest < 0.30:
            status = 'no_conforme'
            detail = (
                f'NDVI de {ndvi_latest:.3f} indica insuficiencia de cubierta vegetal entre filas '
                f'(umbral: 0.30). Puede comprometer la ayuda eco-esquema por cubierta.'
            )
        else:
            status = 'conforme'
            detail = f'NDVI de {ndvi_latest:.3f} confirma presencia de cubierta vegetal entre filas.'

        conditions.append({
            'name': 'Cubierta vegetal entre filas (olivar)',
            'status': status,
            'value_str': f'NDVI = {ndvi_latest:.3f}',
            'detail': detail,
            'regulation_ref': 'Eco-esquema 1 — PEPAC España 2023-2027 (olivar)'
        })

    # ── Condición 3: Anomalía hídrica (NDWI < 0.10) ──
    if ndwi_latest < 0.10:
        status = 'no_conforme' if ndwi_latest < 0.00 else 'advertencia'
        detail = (
            f'NDWI de {ndwi_latest:.3f} indica estrés hídrico '
            + ('severo (NDWI < 0.00).' if ndwi_latest < 0.00 else 'significativo (NDWI < 0.10).')
            + ' Verificar coherencia con volúmenes de riego declarados.'
        )
    else:
        status = 'conforme'
        detail = f'NDWI de {ndwi_latest:.3f} es coherente con el estado hídrico esperado para este período.'

    conditions.append({
        'name': 'Gestión hídrica (coherencia con riego declarado)',
        'status': status,
        'value_str': f'NDWI = {ndwi_latest:.3f}',
        'detail': detail,
        'regulation_ref': 'BCAM 4 — Reg. (UE) 2021/2115 — Gestión mínima del suelo'
    })

    return conditions


def generate_pac_report(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Genera informe PAC completo. Llamado desde el endpoint FastAPI.

    data debe incluir:
      - client_name, parcel_name, crop_type, area_hectares
      - municipality / province
      - period_start, period_end
      - kpi_records: List[{observation_date, ndvi_mean, ndwi_mean, stress_area_pct, satellite_source}]
      - report_type: "pac_inspeccion" | "pac_anual"
      - report_ref: string de referencia
      - signature_status: "not_requested" | "pending" | "signed"
      - agronomist_name, agronomist_college, signature_date (si signed)
      - year: int
    """
    try:
        # Evaluar condiciones PAC automáticamente
        kpi_records = data.get('kpi_records', [])
        crop_type   = data.get('crop_type', '')
        data['pac_conditions'] = _evaluate_pac_conditions(kpi_records, crop_type)

        generator = PacReportGenerator(data)
        pdf_bytes = generator.generate()
        pdf_b64   = base64.b64encode(pdf_bytes).decode('utf-8')

        report_ref = data.get('report_ref', 'PAC-UNKNOWN')
        filename   = f'InformePAC_{report_ref}.pdf'

        # Determine overall status
        conditions = data['pac_conditions']
        no_conf = sum(1 for c in conditions if c['status'] == 'no_conforme')
        warns   = sum(1 for c in conditions if c['status'] == 'advertencia')
        overall = 'no_conforme' if no_conf > 0 else ('advertencia' if warns > 0 else 'conforme')

        return {
            'success':         True,
            'pdf_base64':      pdf_b64,
            'filename':        filename,
            'pdf_size':        len(pdf_bytes),
            'report_ref':      report_ref,
            'pac_status':      overall,
            'conditions_count': len(conditions),
            'no_conforme_count': no_conf,
            'generated_at':    datetime.now().isoformat(),
            'version':         '1.0'
        }

    except Exception as e:
        import traceback
        return {
            'success':    False,
            'error':      str(e),
            'traceback':  traceback.format_exc(),
        }
