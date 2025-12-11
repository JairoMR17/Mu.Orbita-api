#!/usr/bin/env python3
"""
Mu.Orbita Professional PDF Report Generator v2.1
Genera informes agronómicos profesionales con diseño corporativo,
gráficos de series temporales y visualizaciones de KPIs.

MODIFICACIÓN v2.1: Soporte para --data-file para evitar problemas con JSON en CLI
"""

import os
import json
import sys
import argparse
from datetime import datetime
from io import BytesIO

# PDF Generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable, KeepTogether
)
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.widgets.markers import makeMarker

# For charts
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import numpy as np

# ============================================================================
# CORPORATE COLORS (extracted from logo)
# ============================================================================
COLORS = {
    'primary_brown': colors.HexColor('#5D4037'),      # Marrón chocolate
    'secondary_gold': colors.HexColor('#C9A962'),     # Dorado
    'accent_cream': colors.HexColor('#F5F0E6'),       # Crema claro
    'background': colors.HexColor('#FDFBF7'),         # Fondo casi blanco
    'text_dark': colors.HexColor('#3E2723'),          # Texto oscuro
    'text_light': colors.HexColor('#8D6E63'),         # Texto secundario
    'success': colors.HexColor('#4CAF50'),            # Verde éxito
    'warning': colors.HexColor('#FF9800'),            # Naranja advertencia
    'danger': colors.HexColor('#F44336'),             # Rojo peligro
    'info': colors.HexColor('#2196F3'),               # Azul info
    'white': colors.white,
    'light_gray': colors.HexColor('#E8E4DF'),
}

# Matplotlib colors
MPL_COLORS = {
    'primary': '#5D4037',
    'secondary': '#C9A962',
    'accent': '#8D6E63',
    'ndvi': '#2E7D32',
    'ndwi': '#1565C0',
    'evi': '#FF6F00',
    'grid': '#E0E0E0',
}

# ============================================================================
# CUSTOM STYLES
# ============================================================================
def create_styles():
    """Create custom paragraph styles for the report"""
    styles = getSampleStyleSheet()
    
    # Title style
    styles.add(ParagraphStyle(
        name='ReportTitle',
        parent=styles['Title'],
        fontName='Helvetica-Bold',
        fontSize=28,
        textColor=COLORS['primary_brown'],
        spaceAfter=6*mm,
        alignment=TA_CENTER,
    ))
    
    # Subtitle
    styles.add(ParagraphStyle(
        name='ReportSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        textColor=COLORS['text_light'],
        spaceAfter=12*mm,
        alignment=TA_CENTER,
        leading=14,
    ))
    
    # Section headers
    styles.add(ParagraphStyle(
        name='SectionHeader',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=14,
        textColor=COLORS['primary_brown'],
        spaceBefore=8*mm,
        spaceAfter=4*mm,
        borderPadding=(0, 0, 2*mm, 0),
    ))
    
    # Subsection headers
    styles.add(ParagraphStyle(
        name='SubsectionHeader',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=11,
        textColor=COLORS['secondary_gold'],
        spaceBefore=5*mm,
        spaceAfter=3*mm,
    ))
    
    # Body text
    styles.add(ParagraphStyle(
        name='CustomBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=COLORS['text_dark'],
        leading=14,
        spaceAfter=3*mm,
        alignment=TA_JUSTIFY,
    ))
    
    # KPI value large
    styles.add(ParagraphStyle(
        name='KPIValue',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        textColor=COLORS['primary_brown'],
        alignment=TA_CENTER,
    ))
    
    # KPI label
    styles.add(ParagraphStyle(
        name='KPILabel',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        textColor=COLORS['text_light'],
        alignment=TA_CENTER,
    ))
    
    # Footer
    styles.add(ParagraphStyle(
        name='Footer',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        textColor=COLORS['text_light'],
        alignment=TA_CENTER,
    ))
    
    # Recommendation text
    styles.add(ParagraphStyle(
        name='RecommendationText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=COLORS['text_dark'],
        leading=13,
        leftIndent=5*mm,
    ))
    
    return styles


# ============================================================================
# CHART GENERATORS
# ============================================================================
def create_ndvi_timeseries_chart(timeseries_data, width=16, height=6):
    """
    Create a professional NDVI time series chart
    Returns a BytesIO object with the PNG image
    """
    fig, ax = plt.subplots(figsize=(width/2.54, height/2.54), dpi=150)
    
    # Style
    ax.set_facecolor('#FDFBF7')
    fig.patch.set_facecolor('#FDFBF7')
    
    if timeseries_data and len(timeseries_data) > 0:
        dates = [d['date'] for d in timeseries_data]
        ndvi = [d.get('NDVI_mean', d.get('ndvi_mean', 0)) or 0 for d in timeseries_data]
        ndwi = [d.get('NDWI_mean', d.get('ndwi_mean', 0)) or 0 for d in timeseries_data]
        evi = [d.get('EVI_mean', d.get('evi_mean', 0)) or 0 for d in timeseries_data]
        
        # Convert dates
        try:
            dates = [datetime.strptime(d, '%Y-%m-%d') if isinstance(d, str) else d for d in dates]
        except:
            dates = list(range(len(ndvi)))
        
        # Plot lines
        ax.plot(dates, ndvi, color=MPL_COLORS['ndvi'], linewidth=2, label='NDVI', marker='o', markersize=4)
        ax.plot(dates, ndwi, color=MPL_COLORS['ndwi'], linewidth=2, label='NDWI', marker='s', markersize=4)
        ax.plot(dates, evi, color=MPL_COLORS['evi'], linewidth=2, label='EVI', marker='^', markersize=4)
        
        # Reference lines
        ax.axhline(y=0.6, color=MPL_COLORS['ndvi'], linestyle='--', alpha=0.3, linewidth=1)
        ax.axhline(y=0.35, color='#F44336', linestyle='--', alpha=0.3, linewidth=1)
        
        # Annotations
        ax.text(dates[-1], 0.6, ' Vigor alto', fontsize=8, color=MPL_COLORS['ndvi'], alpha=0.7, va='center')
        ax.text(dates[-1], 0.35, ' Estrés', fontsize=8, color='#F44336', alpha=0.7, va='center')
        
    else:
        # No data - show placeholder
        ax.text(0.5, 0.5, 'Datos de serie temporal no disponibles', 
                ha='center', va='center', fontsize=12, color=MPL_COLORS['accent'],
                transform=ax.transAxes)
    
    # Styling
    ax.set_ylabel('Valor del Índice', fontsize=10, color=MPL_COLORS['primary'])
    ax.set_xlabel('Fecha', fontsize=10, color=MPL_COLORS['primary'])
    ax.tick_params(colors=MPL_COLORS['primary'], labelsize=8)
    ax.grid(True, linestyle='-', alpha=0.3, color=MPL_COLORS['grid'])
    ax.legend(loc='upper left', framealpha=0.9, fontsize=9)
    ax.set_ylim(-0.1, 1.0)
    
    # Format x-axis dates
    if timeseries_data and len(timeseries_data) > 0:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        plt.xticks(rotation=45, ha='right')
    
    plt.tight_layout()
    
    # Save to BytesIO
    img_buffer = BytesIO()
    plt.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight', 
                facecolor='#FDFBF7', edgecolor='none')
    plt.close()
    img_buffer.seek(0)
    
    return img_buffer


def create_kpi_gauge(value, min_val=0, max_val=1, label='', thresholds=None, width=4, height=3):
    """
    Create a simple horizontal gauge chart for KPI visualization
    """
    if thresholds is None:
        thresholds = [(0.35, '#F44336'), (0.6, '#FF9800'), (1.0, '#4CAF50')]
    
    fig, ax = plt.subplots(figsize=(width, height), dpi=100)
    ax.set_facecolor('#FDFBF7')
    fig.patch.set_facecolor('#FDFBF7')
    
    # Draw background bar
    ax.barh(0, max_val - min_val, height=0.3, left=min_val, color='#E0E0E0', alpha=0.5)
    
    # Draw threshold regions
    prev_thresh = min_val
    for thresh, color in thresholds:
        ax.barh(0, thresh - prev_thresh, height=0.3, left=prev_thresh, color=color, alpha=0.3)
        prev_thresh = thresh
    
    # Draw value indicator
    if value is not None and not np.isnan(value):
        ax.barh(0, value - min_val, height=0.3, left=min_val, color=MPL_COLORS['primary'], alpha=0.9)
        ax.axvline(x=value, color=MPL_COLORS['secondary'], linewidth=3)
        ax.text(value, 0.25, f'{value:.2f}', ha='center', va='bottom', fontsize=14, 
                fontweight='bold', color=MPL_COLORS['primary'])
    
    ax.set_xlim(min_val, max_val)
    ax.set_ylim(-0.3, 0.5)
    ax.axis('off')
    ax.set_title(label, fontsize=11, color=MPL_COLORS['primary'], pad=10)
    
    plt.tight_layout()
    
    img_buffer = BytesIO()
    plt.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight',
                facecolor='#FDFBF7', edgecolor='none')
    plt.close()
    img_buffer.seek(0)
    
    return img_buffer


def create_risk_indicator(risk_level, label=''):
    """
    Create a traffic light style risk indicator
    risk_level: 'low', 'medium', 'high', 'unknown'
    """
    fig, ax = plt.subplots(figsize=(2, 0.8), dpi=100)
    ax.set_facecolor('#FDFBF7')
    fig.patch.set_facecolor('#FDFBF7')
    
    colors_map = {
        'low': ('#4CAF50', 'Bajo'),
        'medium': ('#FF9800', 'Moderado'),
        'high': ('#F44336', 'Alto'),
        'unknown': ('#9E9E9E', 'N/D'),
    }
    
    color, text = colors_map.get(risk_level, colors_map['unknown'])
    
    # Draw circle indicator
    circle = plt.Circle((0.15, 0.5), 0.3, color=color, alpha=0.9)
    ax.add_patch(circle)
    
    # Add text
    ax.text(0.5, 0.5, text, fontsize=10, va='center', ha='left', color=MPL_COLORS['primary'])
    
    ax.set_xlim(0, 1.5)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    plt.tight_layout()
    
    img_buffer = BytesIO()
    plt.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight',
                facecolor='#FDFBF7', edgecolor='none')
    plt.close()
    img_buffer.seek(0)
    
    return img_buffer


# ============================================================================
# PDF DOCUMENT BUILDER
# ============================================================================
class MuOrbitaReportGenerator:
    """Professional PDF report generator for Mu.Orbita"""
    
    def __init__(self, output_path, logo_path=None):
        self.output_path = output_path
        self.logo_path = logo_path
        self.styles = create_styles()
        self.width, self.height = A4
        self.margin = 15*mm
        
    def _header_footer(self, canvas, doc):
        """Add header and footer to each page"""
        canvas.saveState()
        
        # Header line
        canvas.setStrokeColor(COLORS['secondary_gold'])
        canvas.setLineWidth(0.5)
        canvas.line(self.margin, self.height - 12*mm, 
                   self.width - self.margin, self.height - 12*mm)
        
        # Footer
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(COLORS['text_light'])
        
        # Page number
        page_num = canvas.getPageNumber()
        canvas.drawCentredString(self.width/2, 10*mm, f"Página {page_num}")
        
        # Copyright
        canvas.drawString(self.margin, 10*mm, "© 2025 Mu.Orbita")
        canvas.drawRightString(self.width - self.margin, 10*mm, "info@muorbita.com")
        
        canvas.restoreState()
    
    def generate(self, data):
        """Generate the complete PDF report"""
        doc = SimpleDocTemplate(
            self.output_path,
            pagesize=A4,
            leftMargin=self.margin,
            rightMargin=self.margin,
            topMargin=20*mm,
            bottomMargin=20*mm
        )
        
        story = []
        
        # ===== HEADER / TITLE =====
        story.append(Paragraph("Mu.Orbita", self.styles['ReportTitle']))
        story.append(Paragraph(
            "Precision from Orbit — Sustainability from Data",
            self.styles['ReportSubtitle']
        ))
        
        # ===== METADATA TABLE =====
        client_name = data.get('client_name', 'Cliente')
        crop_type = data.get('crop_type', 'Cultivo')
        analysis_type = data.get('analysis_type', 'baseline').upper()
        area = self._fmt(data.get('area_hectares', 0), 1)
        start_date = data.get('start_date', 'N/A')
        end_date = data.get('end_date', 'N/A')
        job_id = data.get('job_id', 'UNKNOWN')
        
        # Truncate job_id for display
        job_id_display = job_id[:12] + '...' if len(job_id) > 12 else job_id
        
        metadata = [
            ['Cliente', client_name, 'Cultivo', crop_type.capitalize()],
            ['Tipo Análisis', analysis_type, 'Área Total', f'{area} ha'],
            ['Período', f'{start_date} — {end_date}', 'Job ID', job_id_display],
        ]
        
        meta_table = Table(metadata, colWidths=[35*mm, 55*mm, 35*mm, 55*mm])
        meta_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), COLORS['secondary_gold']),
            ('TEXTCOLOR', (2, 0), (2, -1), COLORS['secondary_gold']),
            ('TEXTCOLOR', (1, 0), (1, -1), COLORS['text_dark']),
            ('TEXTCOLOR', (3, 0), (3, -1), COLORS['text_dark']),
            ('BACKGROUND', (0, 0), (-1, -1), COLORS['accent_cream']),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3*mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3*mm),
            ('LEFTPADDING', (0, 0), (-1, -1), 3*mm),
            ('GRID', (0, 0), (-1, -1), 0.5, COLORS['light_gray']),
        ]))
        story.append(meta_table)
        story.append(Spacer(1, 8*mm))
        
        # ===== KPI SUMMARY =====
        story.append(Paragraph("■ Indicadores Clave de Rendimiento", self.styles['SectionHeader']))
        
        ndvi_mean = data.get('ndvi_mean', 0) or 0
        ndwi_mean = data.get('ndwi_mean', 0) or 0
        evi_mean = data.get('evi_mean', 0) or 0
        stress_pct = data.get('stress_area_pct', 0) or 0
        
        # Interpret values
        def interpret_ndvi(v):
            if v >= 0.6: return "Vigor alto"
            elif v >= 0.45: return "Vigor moderado"
            elif v >= 0.35: return "Vigor bajo"
            else: return "Estrés severo"
        
        def interpret_ndwi(v):
            if v >= 0.2: return "Óptimo"
            elif v >= 0.1: return "Déficit leve"
            else: return "Déficit severo"
        
        kpi_data = [
            [
                Paragraph(f"<font size='24'><b>{self._fmt(ndvi_mean, 2)}</b></font>", self.styles['KPIValue']),
                Paragraph(f"<font size='24'><b>{self._fmt(ndwi_mean, 2)}</b></font>", self.styles['KPIValue']),
                Paragraph(f"<font size='24'><b>{self._fmt(evi_mean, 2)}</b></font>", self.styles['KPIValue']),
                Paragraph(f"<font size='24'><b>{self._fmt(stress_pct, 1) if stress_pct else 'N/A'}</b></font><font size='12'> %</font>", self.styles['KPIValue']),
            ],
            [
                Paragraph("NDVI Medio", self.styles['KPILabel']),
                Paragraph("NDWI Medio", self.styles['KPILabel']),
                Paragraph("EVI Medio", self.styles['KPILabel']),
                Paragraph("Área Estrés", self.styles['KPILabel']),
            ],
            [
                Paragraph(f"<font size='9' color='#8D6E63'>{interpret_ndvi(ndvi_mean)}</font>", self.styles['KPILabel']),
                Paragraph(f"<font size='9' color='#8D6E63'>{interpret_ndwi(ndwi_mean)}</font>", self.styles['KPILabel']),
                Paragraph(f"<font size='9' color='#8D6E63'>Productividad</font>", self.styles['KPILabel']),
                Paragraph(f"<font size='9' color='#8D6E63'>NDVI &lt; 0.35</font>", self.styles['KPILabel']),
            ],
        ]
        
        kpi_table = Table(kpi_data, colWidths=[45*mm, 45*mm, 45*mm, 45*mm])
        kpi_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BACKGROUND', (0, 0), (-1, -1), COLORS['background']),
            ('BOX', (0, 0), (-1, -1), 1, COLORS['light_gray']),
            ('LINEAFTER', (0, 0), (-2, -1), 0.5, COLORS['light_gray']),
            ('TOPPADDING', (0, 0), (-1, 0), 4*mm),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 3*mm),
        ]))
        story.append(kpi_table)
        story.append(Spacer(1, 8*mm))
        
        # ===== TIMESERIES CHART =====
        story.append(Paragraph("■ Evolución Temporal de Índices", self.styles['SectionHeader']))
        
        timeseries = data.get('timeseries', [])
        chart_img = create_ndvi_timeseries_chart(timeseries)
        img = Image(chart_img, width=170*mm, height=60*mm)
        story.append(img)
        story.append(Spacer(1, 6*mm))
        
        # ===== DETAILED INDICES TABLE =====
        story.append(Paragraph("■ Detalle de Índices Vegetativos", self.styles['SectionHeader']))
        
        indices_data = [
            ['Métrica', 'Valor', 'P10', 'P50', 'P90', 'Interpretación'],
            ['NDVI (Vigor)', 
             self._fmt(ndvi_mean), 
             self._fmt(data.get('ndvi_p10')), 
             self._fmt(data.get('ndvi_p50')),
             self._fmt(data.get('ndvi_p90')),
             interpret_ndvi(ndvi_mean)],
            ['NDWI (Agua)', 
             self._fmt(ndwi_mean),
             self._fmt(data.get('ndwi_p10')),
             '—',
             self._fmt(data.get('ndwi_p90')),
             interpret_ndwi(ndwi_mean)],
            ['EVI (Productiv.)', 
             self._fmt(evi_mean),
             self._fmt(data.get('evi_p10')),
             '—',
             self._fmt(data.get('evi_p90')),
             '—'],
            ['NDCI (Clorofila)', 
             self._fmt(data.get('ndci_mean')),
             '—', '—', '—', '—'],
            ['SAVI (Aj. Suelo)', 
             self._fmt(data.get('savi_mean')),
             '—', '—', '—', '—'],
        ]
        
        indices_table = Table(indices_data, colWidths=[35*mm, 22*mm, 22*mm, 22*mm, 22*mm, 40*mm])
        indices_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), COLORS['secondary_gold']),
            ('TEXTCOLOR', (0, 0), (-1, 0), COLORS['white']),
            ('BACKGROUND', (0, 1), (-1, -1), COLORS['background']),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, COLORS['light_gray']),
            ('TOPPADDING', (0, 0), (-1, -1), 2*mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2*mm),
        ]))
        story.append(indices_table)
        
        # ===== PAGE BREAK =====
        story.append(PageBreak())
        
        # ===== RISK ASSESSMENT =====
        story.append(Paragraph("■■ Evaluación de Riesgos", self.styles['SectionHeader']))
        
        # Calculate risk levels
        water_risk = 'high' if ndwi_mean < 0.1 else ('medium' if ndwi_mean < 0.2 else 'low')
        vigor_risk = 'high' if ndvi_mean < 0.35 else ('medium' if ndvi_mean < 0.45 else 'low')
        heterogeneity = data.get('heterogeneity', 0) or 0
        hetero_risk = 'high' if heterogeneity > 0.25 else ('medium' if heterogeneity > 0.15 else 'low')
        
        risk_data = [
            ['Tipo de Riesgo', 'Nivel', 'Indicador', 'Acción Sugerida'],
            ['Estrés Hídrico', self._risk_cell(water_risk), f'NDWI: {self._fmt(ndwi_mean)}', 
             'Verificar riego' if water_risk == 'high' else 'Monitorear'],
            ['Déficit de Vigor', self._risk_cell(vigor_risk), f'NDVI: {self._fmt(ndvi_mean)}',
             'Inspección' if vigor_risk == 'high' else 'Monitorear'],
            ['Heterogeneidad', self._risk_cell(hetero_risk) if heterogeneity else self._risk_cell('unknown'), 
             f'P90-P10: {self._fmt(heterogeneity) if heterogeneity else "N/D"}',
             'VRA recomendado' if hetero_risk == 'high' else 'Homogéneo'],
        ]
        
        risk_table = Table(risk_data, colWidths=[40*mm, 30*mm, 45*mm, 55*mm])
        risk_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), COLORS['primary_brown']),
            ('TEXTCOLOR', (0, 0), (-1, 0), COLORS['white']),
            ('BACKGROUND', (0, 1), (-1, -1), COLORS['background']),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, COLORS['light_gray']),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5*mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5*mm),
            ('LEFTPADDING', (0, 0), (-1, -1), 2*mm),
        ]))
        story.append(risk_table)
        story.append(Spacer(1, 8*mm))
        
        # ===== RECOMMENDATIONS =====
        story.append(Paragraph("■ Recomendaciones Prioritarias", self.styles['SectionHeader']))
        
        recommendations = self._generate_recommendations(data)
        
        for i, rec in enumerate(recommendations, 1):
            # Priority color
            priority_colors = {'Alta': '#F44336', 'Media': '#FF9800', 'Baja': '#4CAF50'}
            priority_color = priority_colors.get(rec['priority'], '#9E9E9E')
            
            rec_header = Paragraph(
                f"<font size='11'><b>{i}. {rec['action']}</b></font> "
                f"<font size='9' color='{priority_color}'>● Prioridad: {rec['priority']}</font> "
                f"<font size='9' color='#8D6E63'>| Plazo: {rec['deadline']}</font>",
                self.styles['CustomBody']
            )
            story.append(rec_header)
            
            rec_details = Paragraph(
                f"<font size='9' color='#5D4037'>"
                f"<b>Trigger:</b> {rec['trigger']}<br/>"
                f"<b>Zona:</b> {rec['zone']}<br/>"
                f"<b>Justificación:</b> {rec['justification']}"
                f"</font>",
                self.styles['RecommendationText']
            )
            story.append(rec_details)
            story.append(Spacer(1, 4*mm))
        
        # ===== TECHNICAL ANNEX =====
        story.append(Paragraph("■ Anexo Técnico", self.styles['SectionHeader']))
        
        # Data sources
        story.append(Paragraph("<b>Fuentes de Datos</b>", self.styles['SubsectionHeader']))
        sources_text = f"""
        • Sentinel-2 (SR Harmonized): {data.get('images_processed', 'N/A')} escenas procesadas<br/>
        • Última imagen válida: {data.get('latest_image_date', 'N/A')}<br/>
        • MODIS LST: Temperatura superficial media {self._fmt(data.get('lst_mean_c'), 1)} ºC<br/>
        • Resolución espacial: 10 m (Sentinel-2), 1 km (MODIS)
        """
        story.append(Paragraph(sources_text, self.styles['CustomBody']))
        
        # Thresholds reference
        story.append(Paragraph("<b>Umbrales de Referencia</b>", self.styles['SubsectionHeader']))
        
        thresh_data = [
            ['Índice', 'Óptimo', 'Moderado', 'Estrés'],
            ['NDVI', '> 0.60', '0.45 - 0.60', '< 0.35'],
            ['NDWI', '> 0.20', '0.10 - 0.20', '< 0.10'],
            ['EVI', '> 0.40', '0.25 - 0.40', '< 0.25'],
        ]
        
        thresh_table = Table(thresh_data, colWidths=[30*mm, 40*mm, 40*mm, 40*mm])
        thresh_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), COLORS['secondary_gold']),
            ('TEXTCOLOR', (0, 0), (-1, 0), COLORS['white']),
            ('BACKGROUND', (1, 1), (1, -1), colors.HexColor('#E8F5E9')),
            ('BACKGROUND', (2, 1), (2, -1), colors.HexColor('#FFF3E0')),
            ('BACKGROUND', (3, 1), (3, -1), colors.HexColor('#FFEBEE')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, COLORS['light_gray']),
            ('TOPPADDING', (0, 0), (-1, -1), 1.5*mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5*mm),
        ]))
        story.append(thresh_table)
        
        # ===== FOOTER DISCLAIMER =====
        story.append(Spacer(1, 10*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=COLORS['light_gray']))
        story.append(Spacer(1, 3*mm))
        
        disclaimer = Paragraph(
            '<font size="8" color="#8D6E63">'
            '<i>Este informe ha sido generado automáticamente mediante análisis de imágenes satelitales. '
            'Las recomendaciones deben ser validadas por un técnico agrónomo antes de su implementación. '
            'Los datos satelitales están sujetos a disponibilidad y condiciones atmosféricas.</i>'
            '</font>',
            self.styles['Footer']
        )
        story.append(disclaimer)
        
        # Build PDF
        doc.build(story, onFirstPage=self._header_footer, onLaterPages=self._header_footer)
        
        return self.output_path
    
    def _fmt(self, value, decimals=2):
        """Format numeric value"""
        if value is None or value == '' or value == 'N/A':
            return 'N/A'
        try:
            return f"{float(value):.{decimals}f}"
        except:
            return str(value)
    
    def _risk_cell(self, risk_level):
        """Create colored risk indicator text"""
        colors_map = {
            'low': ('🟢', 'Bajo'),
            'medium': ('🟡', 'Moderado'),
            'high': ('🔴', 'Alto'),
            'unknown': ('⚪', 'N/D'),
        }
        icon, text = colors_map.get(risk_level, colors_map['unknown'])
        return f"■ {text}"
    
    def _generate_recommendations(self, data):
        """Generate default recommendations based on data analysis"""
        recommendations = []
        
        ndvi_val = data.get('ndvi_mean')
        ndwi_val = data.get('ndwi_mean')
        stress_pct = data.get('stress_area_pct', 0)
        
        # Recommendation 1: Based on NDWI (water stress)
        if ndwi_val and ndwi_val < 0.1:
            recommendations.append({
                'action': 'Verificar sistema de riego',
                'priority': 'Alta',
                'deadline': '3-5 días',
                'trigger': f'NDWI = {ndwi_val:.2f} indica déficit hídrico severo',
                'zone': 'Toda la parcela',
                'justification': 'Estrés hídrico puede reducir producción hasta 30%'
            })
        elif ndwi_val and ndwi_val < 0.2:
            recommendations.append({
                'action': 'Ajustar frecuencia de riego',
                'priority': 'Media',
                'deadline': '7 días',
                'trigger': f'NDWI = {ndwi_val:.2f} indica déficit moderado',
                'zone': 'Zonas con NDWI < 0.15',
                'justification': 'Prevenir escalada de estrés hídrico'
            })
        else:
            recommendations.append({
                'action': 'Mantener programa de riego actual',
                'priority': 'Baja',
                'deadline': '14 días',
                'trigger': 'Estado hídrico dentro de parámetros óptimos',
                'zone': 'Toda la parcela',
                'justification': 'Continuar monitoreo regular'
            })
        
        # Recommendation 2: Based on NDVI (vigor)
        if ndvi_val and ndvi_val < 0.35:
            recommendations.append({
                'action': 'Inspección de campo urgente',
                'priority': 'Alta',
                'deadline': '3 días',
                'trigger': f'NDVI = {ndvi_val:.2f} indica estrés severo',
                'zone': 'Áreas con NDVI < 0.35',
                'justification': 'Descartar plagas, enfermedades o fallo de riego'
            })
        elif ndvi_val and ndvi_val < 0.45:
            recommendations.append({
                'action': 'Evaluación nutricional',
                'priority': 'Media',
                'deadline': '7-10 días',
                'trigger': f'NDVI = {ndvi_val:.2f} por debajo del óptimo',
                'zone': 'Zonas de bajo vigor',
                'justification': 'Vigor reducido puede indicar deficiencia nutricional'
            })
        else:
            recommendations.append({
                'action': 'Monitoreo estándar de vigor',
                'priority': 'Baja',
                'deadline': '14 días',
                'trigger': 'Vigor vegetativo dentro de rango normal',
                'zone': 'Toda la parcela',
                'justification': 'Cultivo en buen estado vegetativo'
            })
        
        # Recommendation 3: Based on stress area
        if stress_pct and stress_pct > 20:
            recommendations.append({
                'action': 'Zonificación para aplicación variable',
                'priority': 'Media',
                'deadline': '10 días',
                'trigger': f'{stress_pct:.1f}% del área presenta estrés',
                'zone': 'Parcela completa',
                'justification': 'VRA puede optimizar uso de insumos en zonas heterogéneas'
            })
        else:
            recommendations.append({
                'action': 'Preparar próximo ciclo de monitoreo',
                'priority': 'Baja',
                'deadline': '14 días',
                'trigger': 'Análisis baseline completado',
                'zone': 'Toda la parcela',
                'justification': 'Establecer comparativa para seguimiento bisemanal'
            })
        
        return recommendations


# ============================================================================
# MAIN FUNCTION
# ============================================================================
def generate_report(data, output_path, logo_path=None):
    """
    Main function to generate a Mu.Orbita professional report
    
    Args:
        data: dict with all KPIs and metadata
        output_path: path for the output PDF
        logo_path: optional path to logo image
    
    Returns:
        path to generated PDF
    """
    generator = MuOrbitaReportGenerator(output_path, logo_path)
    return generator.generate(data)


# ============================================================================
# CLI INTERFACE
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description='Mu.Orbita Professional PDF Report Generator'
    )
    parser.add_argument(
        '--job-id', 
        required=True, 
        help='Job ID for the report'
    )
    parser.add_argument(
        '--output', 
        required=True, 
        help='Output path for the PDF file'
    )
    parser.add_argument(
        '--data', 
        default=None,
        help='JSON string with report data (use --data-file for large data)'
    )
    parser.add_argument(
        '--data-file', 
        default=None,
        help='Path to JSON file with report data (preferred over --data)'
    )
    parser.add_argument(
        '--data-stdin',
        action='store_true',
        help='Read JSON data from stdin (preferred method from n8n)'
    )
    parser.add_argument(
        '--logo', 
        default=None,
        help='Optional path to logo image'
    )
    
    args = parser.parse_args()
    
    # Load data from stdin, file, or string
    if args.data_stdin:
        try:
            stdin_data = sys.stdin.read()
            data = json.loads(stdin_data)
        except Exception as e:
            print(json.dumps({
                'success': False,
                'error': f'Error reading from stdin: {str(e)}'
            }))
            sys.exit(1)
    elif args.data_file:
        try:
            with open(args.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(json.dumps({
                'success': False,
                'error': f'Error reading data file: {str(e)}'
            }))
            sys.exit(1)
    elif args.data:
        try:
            data = json.loads(args.data)
        except Exception as e:
            print(json.dumps({
                'success': False,
                'error': f'Error parsing JSON data: {str(e)}'
            }))
            sys.exit(1)
    else:
        print(json.dumps({
            'success': False,
            'error': 'Either --data, --data-file, or --data-stdin is required'
        }))
        sys.exit(1)
    
    # Ensure job_id is in data
    if 'job_id' not in data:
        data['job_id'] = args.job_id
    
    # Generate report
    try:
        output_path = generate_report(data, args.output, args.logo)
        print(json.dumps({
            'success': True,
            'output_path': output_path,
            'job_id': args.job_id
        }))
    except Exception as e:
        print(json.dumps({
            'success': False,
            'error': str(e)
        }))
        sys.exit(1)


if __name__ == '__main__':
    main()