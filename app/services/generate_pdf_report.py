"""
Mu.Orbita PDF Report Generator v2.0
=====================================
Generador profesional de informes PDF con:
- Gráficos de series temporales
- Mapas de calor (NDVI, NDWI)
- Narrativa de análisis IA
- Diseño profesional corregido

Autor: Mu.Orbita
Fecha: 2025-12-16
"""

import io
import base64
import json
from datetime import datetime
from typing import Optional, Dict, List, Any

# ReportLab imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, KeepTogether, ListFlowable, ListItem
)
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics import renderPDF

# Matplotlib para gráficos más sofisticados
import matplotlib
matplotlib.use('Agg')  # Backend sin GUI
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap
import numpy as np

# ============================================
# CONFIGURACIÓN DE COLORES CORPORATIVOS
# ============================================

COLORS_MUORBITA = {
    'primary': '#8B7355',      # Marrón tierra (cabecera)
    'secondary': '#228B22',    # Verde bosque (vigor)
    'accent': '#4169E1',       # Azul (agua)
    'warning': '#DAA520',      # Dorado (precaución)
    'danger': '#CC4444',       # Rojo (estrés)
    'text': '#3E2B1D',         # Marrón oscuro texto
    'light_bg': '#F9F7F2',     # Fondo claro
    'border': '#E6DDD0',       # Borde suave
    'white': '#FFFFFF',
}

# Convertir hex a RGB para ReportLab
def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) / 255 for i in (0, 2, 4))


# ============================================
# ESTILOS DE PÁRRAFO PERSONALIZADOS
# ============================================

def get_custom_styles():
    """Crear estilos personalizados para el PDF"""
    styles = getSampleStyleSheet()
    
    # Título principal
    styles.add(ParagraphStyle(
        name='MuTitle',
        parent=styles['Title'],
        fontName='Helvetica-Bold',
        fontSize=24,
        textColor=colors.HexColor(COLORS_MUORBITA['primary']),
        spaceAfter=6*mm,
        alignment=TA_CENTER
    ))
    
    # Subtítulo
    styles.add(ParagraphStyle(
        name='MuSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        textColor=colors.HexColor('#666666'),
        spaceAfter=8*mm,
        alignment=TA_CENTER
    ))
    
    # Encabezado de sección
    styles.add(ParagraphStyle(
        name='MuSectionHeader',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=14,
        textColor=colors.HexColor(COLORS_MUORBITA['primary']),
        spaceBefore=8*mm,
        spaceAfter=4*mm,
        borderPadding=3,
        leftIndent=0
    ))
    
    # Texto normal
    styles.add(ParagraphStyle(
        name='MuBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor(COLORS_MUORBITA['text']),
        leading=14,
        alignment=TA_JUSTIFY,
        spaceAfter=3*mm
    ))
    
    # Texto pequeño
    styles.add(ParagraphStyle(
        name='MuSmall',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        textColor=colors.HexColor('#666666'),
        leading=10
    ))
    
    # KPI grande
    styles.add(ParagraphStyle(
        name='MuKPIValue',
        fontName='Helvetica-Bold',
        fontSize=28,
        textColor=colors.HexColor(COLORS_MUORBITA['primary']),
        alignment=TA_CENTER,
        leading=32
    ))
    
    # Etiqueta KPI
    styles.add(ParagraphStyle(
        name='MuKPILabel',
        fontName='Helvetica',
        fontSize=9,
        textColor=colors.HexColor('#666666'),
        alignment=TA_CENTER,
        spaceAfter=2*mm
    ))
    
    # Interpretación KPI
    styles.add(ParagraphStyle(
        name='MuKPIInterpretation',
        fontName='Helvetica-Bold',
        fontSize=9,
        alignment=TA_CENTER
    ))
    
    return styles


# ============================================
# FUNCIONES DE INTERPRETACIÓN
# ============================================

def interpret_ndvi(value: float) -> tuple:
    """Interpretar valor NDVI y devolver (texto, color)"""
    if value < 0.20:
        return "Suelo desnudo", COLORS_MUORBITA['danger']
    elif value < 0.35:
        return "Estrés severo", COLORS_MUORBITA['danger']
    elif value < 0.45:
        return "Vigor bajo", COLORS_MUORBITA['warning']
    elif value < 0.60:
        return "Vigor moderado", COLORS_MUORBITA['secondary']
    else:
        return "Vigor alto", COLORS_MUORBITA['secondary']


def interpret_ndwi(value: float) -> tuple:
    """Interpretar valor NDWI y devolver (texto, color)"""
    if value < 0.0:
        return "Déficit severo", COLORS_MUORBITA['danger']
    elif value < 0.10:
        return "Déficit moderado", COLORS_MUORBITA['warning']
    elif value < 0.20:
        return "Estado aceptable", COLORS_MUORBITA['warning']
    else:
        return "Estado óptimo", COLORS_MUORBITA['secondary']


def interpret_stress_pct(value: float) -> tuple:
    """Interpretar porcentaje de área con estrés"""
    if value > 50:
        return "Crítico", COLORS_MUORBITA['danger']
    elif value > 25:
        return "Moderado", COLORS_MUORBITA['warning']
    else:
        return "Bajo", COLORS_MUORBITA['secondary']


def interpret_heterogeneity(value: float) -> tuple:
    """Interpretar heterogeneidad (P90-P10)"""
    if value < 0.15:
        return "Homogéneo", COLORS_MUORBITA['secondary']
    elif value < 0.25:
        return "Heterogeneidad moderada", COLORS_MUORBITA['warning']
    else:
        return "Heterogeneidad alta", COLORS_MUORBITA['danger']


def get_risk_level_color(level: str) -> str:
    """Obtener color según nivel de riesgo"""
    levels = {
        'Bajo': COLORS_MUORBITA['secondary'],
        'Moderado': COLORS_MUORBITA['warning'],
        'Alto': COLORS_MUORBITA['danger'],
        'Crítico': COLORS_MUORBITA['danger']
    }
    return levels.get(level, COLORS_MUORBITA['text'])


# ============================================
# GENERACIÓN DE GRÁFICOS CON MATPLOTLIB
# ============================================

def generate_time_series_chart(time_series: List[Dict], width_px=600, height_px=250) -> bytes:
    """
    Generar gráfico de serie temporal NDVI/NDWI con matplotlib.
    Retorna imagen PNG en bytes.
    """
    if not time_series or len(time_series) < 2:
        # Generar gráfico placeholder
        fig, ax = plt.subplots(figsize=(width_px/100, height_px/100), dpi=100)
        ax.text(0.5, 0.5, 'Datos de serie temporal no disponibles', 
                ha='center', va='center', fontsize=12, color='#888888')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', facecolor='white')
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
    
    # Parsear datos
    dates = []
    ndvi_values = []
    ndwi_values = []
    evi_values = []
    
    for point in time_series:
        try:
            date_str = point.get('date', '')
            if date_str:
                dates.append(datetime.strptime(date_str, '%Y-%m-%d'))
                ndvi_values.append(point.get('ndvi', 0))
                ndwi_values.append(point.get('ndwi', 0))
                evi_values.append(point.get('evi', 0))
        except:
            continue
    
    if len(dates) < 2:
        # Fallback
        fig, ax = plt.subplots(figsize=(width_px/100, height_px/100), dpi=100)
        ax.text(0.5, 0.5, 'Datos insuficientes para serie temporal', 
                ha='center', va='center', fontsize=12, color='#888888')
        ax.axis('off')
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', facecolor='white')
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
    
    # Crear gráfico
    fig, ax = plt.subplots(figsize=(width_px/100, height_px/100), dpi=100)
    
    # Líneas de índices
    ax.plot(dates, ndvi_values, color='#228B22', linewidth=2, label='NDVI (Vigor)', marker='o', markersize=4)
    ax.plot(dates, ndwi_values, color='#4169E1', linewidth=2, label='NDWI (Agua)', marker='s', markersize=4)
    if any(v > 0 for v in evi_values):
        ax.plot(dates, evi_values, color='#DAA520', linewidth=2, label='EVI (Productividad)', marker='^', markersize=4)
    
    # Zonas de referencia
    ax.axhspan(0.6, 1.0, alpha=0.1, color='green', label='_nolegend_')
    ax.axhspan(0.35, 0.6, alpha=0.1, color='yellow', label='_nolegend_')
    ax.axhspan(0, 0.35, alpha=0.1, color='red', label='_nolegend_')
    
    # Líneas de umbral
    ax.axhline(y=0.60, color='green', linestyle='--', linewidth=0.8, alpha=0.5)
    ax.axhline(y=0.35, color='red', linestyle='--', linewidth=0.8, alpha=0.5)
    
    # Formato
    ax.set_xlabel('Fecha', fontsize=10)
    ax.set_ylabel('Valor del Índice', fontsize=10)
    ax.set_title('Evolución Temporal de Índices', fontsize=12, fontweight='bold', color='#8B7355')
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=45, ha='right')
    
    ax.set_ylim(-0.2, 1.0)
    ax.legend(loc='upper right', fontsize=8)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Exportar a bytes
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor='white', dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_ndvi_histogram(ndvi_mean: float, ndvi_p10: float, ndvi_p90: float, 
                           width_px=300, height_px=200) -> bytes:
    """Generar histograma simplificado de distribución NDVI"""
    fig, ax = plt.subplots(figsize=(width_px/100, height_px/100), dpi=100)
    
    # Simular distribución basada en percentiles
    mu = ndvi_mean
    sigma = (ndvi_p90 - ndvi_p10) / 3.29  # ~3.29 sigmas entre P10 y P90
    x = np.linspace(max(0, mu - 3*sigma), min(1, mu + 3*sigma), 100)
    y = (1/(sigma * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mu) / sigma) ** 2)
    
    # Colorear por zonas
    colors_zones = np.where(x < 0.35, '#CC4444', np.where(x < 0.60, '#DAA520', '#228B22'))
    
    for i in range(len(x)-1):
        ax.fill_between(x[i:i+2], y[i:i+2], color=colors_zones[i], alpha=0.6)
    
    ax.axvline(x=ndvi_mean, color='#3E2B1D', linestyle='-', linewidth=2, label=f'Media: {ndvi_mean:.2f}')
    ax.axvline(x=ndvi_p10, color='#888888', linestyle='--', linewidth=1, label=f'P10: {ndvi_p10:.2f}')
    ax.axvline(x=ndvi_p90, color='#888888', linestyle='--', linewidth=1, label=f'P90: {ndvi_p90:.2f}')
    
    ax.set_xlabel('NDVI', fontsize=9)
    ax.set_ylabel('Densidad', fontsize=9)
    ax.set_title('Distribución NDVI', fontsize=10, fontweight='bold', color='#8B7355')
    ax.legend(loc='upper right', fontsize=7)
    ax.set_xlim(0, 1)
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor='white', dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_placeholder_map(title: str, mean_value: float, colormap: str = 'RdYlGn',
                            width_px=280, height_px=200) -> bytes:
    """
    Generar mapa placeholder cuando no hay datos geoespaciales.
    En producción, esto se reemplazaría con la renderización real del GeoTIFF.
    """
    fig, ax = plt.subplots(figsize=(width_px/100, height_px/100), dpi=100)
    
    # Simular datos espaciales
    np.random.seed(42)
    data = np.random.normal(mean_value, 0.1, (20, 20))
    data = np.clip(data, 0, 1)
    
    # Crear mapa de calor
    cmap = plt.colormaps.get_cmap(colormap)
    im = ax.imshow(data, cmap=cmap, vmin=0, vmax=1, aspect='auto')
    
    # Colorbar
    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.ax.tick_params(labelsize=7)
    
    ax.set_title(f'{title}\nMedia: {mean_value:.2f}', fontsize=9, fontweight='bold', color='#8B7355')
    ax.axis('off')
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor='white', dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ============================================
# CLASE PRINCIPAL DEL GENERADOR PDF
# ============================================

class MuOrbitaPDFGenerator:
    """Generador de informes PDF profesionales para Mu.Orbita"""
    
    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.styles = get_custom_styles()
        self.buffer = io.BytesIO()
        self.width, self.height = A4
        self.margin = 15*mm
        
    def _create_header_footer(self, canvas, doc):
        """Añadir cabecera y pie de página"""
        canvas.saveState()
        
        # === CABECERA ===
        # Banda de color
        canvas.setFillColor(colors.HexColor(COLORS_MUORBITA['primary']))
        canvas.rect(0, self.height - 25*mm, self.width, 25*mm, fill=True, stroke=False)
        
        # Logo/Nombre
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica-Bold', 20)
        canvas.drawString(self.margin, self.height - 17*mm, "Mu.Orbita")
        
        # Slogan
        canvas.setFont('Helvetica', 9)
        canvas.drawString(self.margin, self.height - 22*mm, "Precision from Orbit — Sustainability from Data")
        
        # Fecha en la derecha
        canvas.drawRightString(self.width - self.margin, self.height - 17*mm, 
                               datetime.now().strftime('%d/%m/%Y'))
        
        # === PIE DE PÁGINA ===
        canvas.setFillColor(colors.HexColor('#888888'))
        canvas.setFont('Helvetica', 8)
        
        # Línea separadora
        canvas.setStrokeColor(colors.HexColor(COLORS_MUORBITA['border']))
        canvas.line(self.margin, 12*mm, self.width - self.margin, 12*mm)
        
        # Textos del pie
        canvas.drawString(self.margin, 7*mm, f"© 2025 Mu.Orbita")
        canvas.drawCentredString(self.width/2, 7*mm, f"Página {doc.page}")
        canvas.drawRightString(self.width - self.margin, 7*mm, "info@muorbita.com")
        
        canvas.restoreState()
    
    def _build_info_table(self) -> Table:
        """Crear tabla de información del análisis"""
        data = self.data
        
        # Formatear Job ID (mostrar completo o versión más legible)
        job_id = data.get('job_id', 'N/A')
        if len(job_id) > 35:
            # Mostrar versión corta pero legible
            job_id_display = f"{job_id[:20]}...{job_id[-10:]}"
        else:
            job_id_display = job_id
        
        table_data = [
            [Paragraph('<b>Cliente</b>', self.styles['MuSmall']), 
             Paragraph(data.get('client_name', 'N/A'), self.styles['MuBody']),
             Paragraph('<b>Cultivo</b>', self.styles['MuSmall']),
             Paragraph(data.get('crop_type', 'N/A').capitalize(), self.styles['MuBody'])],
            
            [Paragraph('<b>Tipo Análisis</b>', self.styles['MuSmall']),
             Paragraph(data.get('analysis_type', 'BASELINE').upper(), self.styles['MuBody']),
             Paragraph('<b>Área Total</b>', self.styles['MuSmall']),
             Paragraph(f"{data.get('area_hectares', 0):.1f} ha", self.styles['MuBody'])],
            
            [Paragraph('<b>Período</b>', self.styles['MuSmall']),
             Paragraph(f"{data.get('start_date', 'N/A')} — {data.get('end_date', 'N/A')}", self.styles['MuBody']),
             Paragraph('<b>Job ID</b>', self.styles['MuSmall']),
             Paragraph(job_id_display, self.styles['MuSmall'])],  # Fuente pequeña para Job ID
        ]
        
        col_widths = [25*mm, 55*mm, 25*mm, 55*mm]
        table = Table(table_data, colWidths=col_widths)
        
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(COLORS_MUORBITA['light_bg'])),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor(COLORS_MUORBITA['text'])),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor(COLORS_MUORBITA['border'])),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor(COLORS_MUORBITA['primary'])),
        ]))
        
        return table
    
    def _build_kpi_cards(self) -> Table:
        """Crear tarjetas de KPIs principales"""
        data = self.data
        
        # KPI 1: NDVI
        ndvi_mean = data.get('ndvi_mean', 0)
        ndvi_interp, ndvi_color = interpret_ndvi(ndvi_mean)
        
        # KPI 2: NDWI
        ndwi_mean = data.get('ndwi_mean', 0)
        ndwi_interp, ndwi_color = interpret_ndwi(ndwi_mean)
        
        # KPI 3: EVI
        evi_mean = data.get('evi_mean', 0)
        
        # KPI 4: Área con estrés
        stress_pct = data.get('stress_area_pct', 0)
        stress_interp, stress_color = interpret_stress_pct(stress_pct)
        
        def make_kpi_cell(value: str, label: str, interpretation: str, color: str):
            """Crear celda de KPI"""
            return [
                Paragraph(f'<font color="{color}" size="24"><b>{value}</b></font>', 
                         ParagraphStyle('kpi', alignment=TA_CENTER)),
                Paragraph(f'<font size="8" color="#666666">{label}</font>', 
                         ParagraphStyle('label', alignment=TA_CENTER, spaceBefore=2*mm)),
                Paragraph(f'<font size="9" color="{color}"><b>{interpretation}</b></font>', 
                         ParagraphStyle('interp', alignment=TA_CENTER, spaceBefore=1*mm)),
            ]
        
        # Construir tabla de KPIs
        kpi_data = [[
            make_kpi_cell(f"{ndvi_mean:.2f}", "NDVI Medio", ndvi_interp, ndvi_color),
            make_kpi_cell(f"{ndwi_mean:.2f}", "NDWI Medio", ndwi_interp, ndwi_color),
            make_kpi_cell(f"{evi_mean:.2f}", "EVI Medio", "Productividad", COLORS_MUORBITA['warning']),
            make_kpi_cell(f"{stress_pct:.1f}%", "Área Estrés", stress_interp, stress_color),
        ]]
        
        # Aplanar para que cada celda sea una mini-tabla
        flat_data = []
        row = []
        for kpi in kpi_data[0]:
            mini_table = Table([[k] for k in kpi], colWidths=[38*mm])
            mini_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            row.append(mini_table)
        flat_data.append(row)
        
        table = Table(flat_data, colWidths=[42*mm, 42*mm, 42*mm, 42*mm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(COLORS_MUORBITA['light_bg'])),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor(COLORS_MUORBITA['border'])),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor(COLORS_MUORBITA['border'])),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        
        return table
    
    def _build_vegetation_detail_table(self) -> Table:
        """Tabla detallada de índices vegetativos"""
        data = self.data
        
        ndvi_interp, _ = interpret_ndvi(data.get('ndvi_mean', 0))
        ndwi_interp, _ = interpret_ndwi(data.get('ndwi_mean', 0))
        
        header_style = ParagraphStyle('header', fontName='Helvetica-Bold', fontSize=9, 
                                       textColor=colors.white, alignment=TA_CENTER)
        cell_style = ParagraphStyle('cell', fontName='Helvetica', fontSize=9, alignment=TA_CENTER)
        
        table_data = [
            [Paragraph('Métrica', header_style), 
             Paragraph('Valor', header_style),
             Paragraph('P10', header_style), 
             Paragraph('P50', header_style),
             Paragraph('P90', header_style), 
             Paragraph('Interpretación', header_style)],
            
            [Paragraph('NDVI (Vigor)', cell_style),
             Paragraph(f"{data.get('ndvi_mean', 0):.2f}", cell_style),
             Paragraph(f"{data.get('ndvi_p10', 0):.2f}", cell_style),
             Paragraph(f"{data.get('ndvi_p50', 0):.2f}", cell_style),
             Paragraph(f"{data.get('ndvi_p90', 0):.2f}", cell_style),
             Paragraph(ndvi_interp, cell_style)],
            
            [Paragraph('NDWI (Agua)', cell_style),
             Paragraph(f"{data.get('ndwi_mean', 0):.2f}", cell_style),
             Paragraph(f"{data.get('ndwi_p10', 0):.2f}", cell_style),
             Paragraph('—', cell_style),
             Paragraph(f"{data.get('ndwi_p90', 0):.2f}", cell_style),
             Paragraph(ndwi_interp, cell_style)],
            
            [Paragraph('EVI (Productiv.)', cell_style),
             Paragraph(f"{data.get('evi_mean', 0):.2f}", cell_style),
             Paragraph(f"{data.get('evi_p10', 0):.2f}", cell_style),
             Paragraph('—', cell_style),
             Paragraph(f"{data.get('evi_p90', 0):.2f}", cell_style),
             Paragraph('—', cell_style)],
            
            [Paragraph('NDCI (Clorofila)', cell_style),
             Paragraph(f"{data.get('ndci_mean', 0):.2f}", cell_style),
             Paragraph('—', cell_style),
             Paragraph('—', cell_style),
             Paragraph('—', cell_style),
             Paragraph('—', cell_style)],
            
            [Paragraph('SAVI (Aj. Suelo)', cell_style),
             Paragraph(f"{data.get('savi_mean', 0):.2f}", cell_style),
             Paragraph('—', cell_style),
             Paragraph('—', cell_style),
             Paragraph('—', cell_style),
             Paragraph('—', cell_style)],
        ]
        
        col_widths = [32*mm, 22*mm, 18*mm, 18*mm, 18*mm, 52*mm]
        table = Table(table_data, colWidths=col_widths)
        
        table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(COLORS_MUORBITA['primary'])),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            # Body
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor(COLORS_MUORBITA['text'])),
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor(COLORS_MUORBITA['border'])),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor(COLORS_MUORBITA['primary'])),
            # Alignment
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            # Alternating rows
            ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#F5F5F5')),
            ('BACKGROUND', (0, 4), (-1, 4), colors.HexColor('#F5F5F5')),
        ]))
        
        return table
    
    def _build_risk_table(self) -> Table:
        """Tabla de evaluación de riesgos"""
        data = self.data
        
        # Evaluar riesgos
        ndwi_mean = data.get('ndwi_mean', 0)
        ndvi_mean = data.get('ndvi_mean', 0)
        heterogeneity = data.get('ndvi_p90', 0) - data.get('ndvi_p10', 0)
        
        # Nivel de estrés hídrico
        if ndwi_mean < 0:
            hydric_level, hydric_action = "Alto", "Verificar riego urgente"
        elif ndwi_mean < 0.10:
            hydric_level, hydric_action = "Moderado", "Monitorizar riego"
        else:
            hydric_level, hydric_action = "Bajo", "Mantener régimen actual"
        
        # Nivel de déficit de vigor
        if ndvi_mean < 0.35:
            vigor_level, vigor_action = "Alto", "Inspección de campo urgente"
        elif ndvi_mean < 0.45:
            vigor_level, vigor_action = "Moderado", "Planificar inspección"
        else:
            vigor_level, vigor_action = "Bajo", "Sin acción requerida"
        
        # Heterogeneidad
        hetero_interp, _ = interpret_heterogeneity(heterogeneity)
        if heterogeneity > 0.25:
            hetero_action = "Considerar VRA"
        elif heterogeneity > 0.15:
            hetero_action = "Evaluar zonificación"
        else:
            hetero_action = "Sin acción requerida"
        
        header_style = ParagraphStyle('header', fontName='Helvetica-Bold', fontSize=9, 
                                       textColor=colors.white, alignment=TA_CENTER)
        cell_style = ParagraphStyle('cell', fontName='Helvetica', fontSize=9, alignment=TA_CENTER)
        
        def get_level_indicator(level: str) -> Paragraph:
            color = get_risk_level_color(level)
            return Paragraph(f'<font color="{color}">■</font> {level}', cell_style)
        
        table_data = [
            [Paragraph('Tipo de Riesgo', header_style),
             Paragraph('Nivel', header_style),
             Paragraph('Indicador', header_style),
             Paragraph('Acción Sugerida', header_style)],
            
            [Paragraph('Estrés Hídrico', cell_style),
             get_level_indicator(hydric_level),
             Paragraph(f'NDWI: {ndwi_mean:.2f}', cell_style),
             Paragraph(hydric_action, cell_style)],
            
            [Paragraph('Déficit de Vigor', cell_style),
             get_level_indicator(vigor_level),
             Paragraph(f'NDVI: {ndvi_mean:.2f}', cell_style),
             Paragraph(vigor_action, cell_style)],
            
            [Paragraph('Heterogeneidad', cell_style),
             get_level_indicator('Bajo' if heterogeneity < 0.15 else ('Moderado' if heterogeneity < 0.25 else 'Alto')),
             Paragraph(f'P90-P10: {heterogeneity:.2f}', cell_style),
             Paragraph(hetero_action, cell_style)],
        ]
        
        col_widths = [40*mm, 30*mm, 35*mm, 55*mm]
        table = Table(table_data, colWidths=col_widths)
        
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(COLORS_MUORBITA['primary'])),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor(COLORS_MUORBITA['border'])),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor(COLORS_MUORBITA['primary'])),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        
        return table
    
    def _build_recommendations(self) -> List:
        """Generar sección de recomendaciones prioritarias"""
        data = self.data
        elements = []
        
        ndwi_mean = data.get('ndwi_mean', 0)
        ndvi_mean = data.get('ndvi_mean', 0)
        stress_pct = data.get('stress_area_pct', 0)
        
        recommendations = []
        
        # Recomendación 1: Basada en NDWI
        if ndwi_mean < 0:
            recommendations.append({
                'title': 'Verificar sistema de riego',
                'priority': 'Alta',
                'deadline': '3-5 días',
                'trigger': f'NDWI = {ndwi_mean:.2f} indica déficit hídrico severo',
                'zone': 'Toda la parcela',
                'justification': 'Estrés hídrico severo puede reducir producción hasta 30%'
            })
        elif ndwi_mean < 0.10:
            recommendations.append({
                'title': 'Ajustar programación de riego',
                'priority': 'Media',
                'deadline': '7 días',
                'trigger': f'NDWI = {ndwi_mean:.2f} indica déficit hídrico moderado',
                'zone': 'Zonas con menor NDWI',
                'justification': 'Prevenir escalada de estrés hídrico'
            })
        
        # Recomendación 2: Basada en NDVI
        if ndvi_mean < 0.35:
            recommendations.append({
                'title': 'Inspección de campo urgente',
                'priority': 'Alta',
                'deadline': '3 días',
                'trigger': f'NDVI = {ndvi_mean:.2f} indica estrés severo',
                'zone': f'Áreas con NDVI < 0.35 ({stress_pct:.1f}% del área)',
                'justification': 'Descartar plagas, enfermedades o fallo de riego'
            })
        elif ndvi_mean < 0.45:
            recommendations.append({
                'title': 'Planificar inspección visual',
                'priority': 'Media',
                'deadline': '7 días',
                'trigger': f'NDVI = {ndvi_mean:.2f} indica vigor bajo',
                'zone': 'Zonas con menor vigor',
                'justification': 'Identificar causas de bajo rendimiento vegetativo'
            })
        
        # Recomendación 3: VRA si hay heterogeneidad o estrés amplio
        if stress_pct > 50:
            recommendations.append({
                'title': 'Zonificación para aplicación variable (VRA)',
                'priority': 'Media',
                'deadline': '10 días',
                'trigger': f'{stress_pct:.1f}% del área presenta estrés',
                'zone': 'Parcela completa',
                'justification': 'VRA puede optimizar uso de insumos en zonas heterogéneas'
            })
        else:
            recommendations.append({
                'title': 'Mantener monitorización quincenal',
                'priority': 'Baja',
                'deadline': '14 días',
                'trigger': 'Situación bajo control',
                'zone': 'Toda la parcela',
                'justification': 'Detección temprana de cambios en vigor'
            })
        
        # Formatear recomendaciones
        for i, rec in enumerate(recommendations[:3], 1):
            priority_color = {
                'Alta': COLORS_MUORBITA['danger'],
                'Media': COLORS_MUORBITA['warning'],
                'Baja': COLORS_MUORBITA['secondary']
            }.get(rec['priority'], COLORS_MUORBITA['text'])
            
            rec_text = f"""
            <b>{i}. {rec['title']}</b> <font color="{priority_color}">● Prioridad: {rec['priority']}</font> | Plazo: {rec['deadline']}<br/>
            <font size="9">
            <b>Trigger:</b> {rec['trigger']}<br/>
            <b>Zona:</b> {rec['zone']}<br/>
            <b>Justificación:</b> {rec['justification']}
            </font>
            """
            
            elements.append(Paragraph(rec_text, self.styles['MuBody']))
            elements.append(Spacer(1, 3*mm))
        
        return elements
    
    def _build_ai_analysis_section(self) -> List:
        """Construir sección de análisis IA (narrativa)"""
        elements = []
        
        markdown_analysis = self.data.get('markdown_analysis', '')
        
        if not markdown_analysis:
            # Generar análisis automático basado en los datos
            data = self.data
            ndvi_mean = data.get('ndvi_mean', 0)
            ndwi_mean = data.get('ndwi_mean', 0)
            stress_pct = data.get('stress_area_pct', 0)
            heterogeneity = data.get('ndvi_p90', 0) - data.get('ndvi_p10', 0)
            
            ndvi_interp, _ = interpret_ndvi(ndvi_mean)
            ndwi_interp, _ = interpret_ndwi(ndwi_mean)
            hetero_interp, _ = interpret_heterogeneity(heterogeneity)
            
            analysis_text = f"""
            <b>Interpretación Integrada:</b><br/><br/>
            
            El cultivo presenta valores de vigor vegetativo clasificados como <b>{ndvi_interp.lower()}</b> 
            (NDVI medio de {ndvi_mean:.2f}). El estado hídrico indica <b>{ndwi_interp.lower()}</b> 
            con un NDWI de {ndwi_mean:.2f}. El <b>{stress_pct:.1f}%</b> del área total 
            ({data.get('stress_area_ha', 0):.1f} ha de {data.get('area_hectares', 0):.1f} ha) 
            muestra signos de estrés significativo (NDVI &lt; 0.35).<br/><br/>
            
            La heterogeneidad intra-parcela es <b>{hetero_interp.lower()}</b> 
            (rango P10-P90: {heterogeneity:.2f}), lo que 
            {"sugiere considerar aplicación variable de insumos" if heterogeneity > 0.15 else "indica un estado relativamente uniforme del cultivo"}.
            <br/><br/>
            
            <b>Contexto estacional:</b> Para esta época del año, los valores observados 
            {"requieren atención inmediata" if ndvi_mean < 0.35 else "deben monitorizarse de cerca" if ndvi_mean < 0.45 else "están dentro de parámetros aceptables"}.
            """
            
            elements.append(Paragraph(analysis_text, self.styles['MuBody']))
        else:
            # Parsear markdown básico
            lines = markdown_analysis.split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    elements.append(Spacer(1, 2*mm))
                elif line.startswith('## '):
                    elements.append(Paragraph(line[3:], self.styles['MuSectionHeader']))
                elif line.startswith('### '):
                    elements.append(Paragraph(f"<b>{line[4:]}</b>", self.styles['MuBody']))
                elif line.startswith('- '):
                    elements.append(Paragraph(f"• {line[2:]}", self.styles['MuBody']))
                elif line.startswith('**') and line.endswith('**'):
                    elements.append(Paragraph(f"<b>{line[2:-2]}</b>", self.styles['MuBody']))
                else:
                    elements.append(Paragraph(line, self.styles['MuBody']))
        
        return elements
    
    def _build_technical_annex(self) -> List:
        """Construir anexo técnico"""
        elements = []
        data = self.data
        
        annex_text = f"""
        <b>Fuentes de Datos</b><br/>
        • Sentinel-2 (SR Harmonized): {data.get('images_processed', 0)} escenas procesadas<br/>
        • Última imagen válida: {data.get('latest_image_date', 'N/A')}<br/>
        • MODIS LST: Temperatura superficial media {data.get('lst_mean_c', 0):.1f} ºC<br/>
        • Resolución espacial: 10 m (Sentinel-2), 1 km (MODIS)<br/><br/>
        
        <b>Umbrales de Referencia</b><br/>
        • NDVI &gt; 0.60: Vigor alto | 0.45-0.60: Moderado | &lt; 0.35: Estrés<br/>
        • NDWI &gt; 0.20: Óptimo | 0.10-0.20: Moderado | &lt; 0.10: Déficit<br/>
        • EVI &gt; 0.40: Productividad alta | 0.25-0.40: Moderada | &lt; 0.25: Baja<br/><br/>
        
        <b>Procesamiento</b><br/>
        • Motor: Google Earth Engine<br/>
        • Máscaras de nube: QA60 + SCL (Sentinel-2)<br/>
        • Estadísticas: Media, P10, P50, P90, desviación estándar
        """
        
        elements.append(Paragraph(annex_text, self.styles['MuSmall']))
        
        return elements
    
    def generate(self) -> bytes:
        """Generar el PDF completo y retornar como bytes"""
        
        doc = SimpleDocTemplate(
            self.buffer,
            pagesize=A4,
            leftMargin=self.margin,
            rightMargin=self.margin,
            topMargin=30*mm,  # Espacio para cabecera
            bottomMargin=20*mm  # Espacio para pie
        )
        
        elements = []
        
        # === PÁGINA 1: Resumen ===
        
        # Título
        elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph("Informe de Análisis Agrícola", self.styles['MuTitle']))
        elements.append(Paragraph("Análisis Baseline — Diagnóstico Inicial", self.styles['MuSubtitle']))
        
        # Tabla de información
        elements.append(self._build_info_table())
        elements.append(Spacer(1, 8*mm))
        
        # Sección: Indicadores Clave
        elements.append(Paragraph("■ Indicadores Clave de Rendimiento", self.styles['MuSectionHeader']))
        elements.append(self._build_kpi_cards())
        elements.append(Spacer(1, 8*mm))
        
        # Sección: Serie Temporal (gráfico)
        elements.append(Paragraph("■ Evolución Temporal de Índices", self.styles['MuSectionHeader']))
        
        time_series = self.data.get('time_series', [])
        chart_bytes = generate_time_series_chart(time_series)
        chart_image = Image(io.BytesIO(chart_bytes), width=160*mm, height=60*mm)
        elements.append(chart_image)
        elements.append(Spacer(1, 5*mm))
        
        # Sección: Detalle de Índices
        elements.append(Paragraph("■ Detalle de Índices Vegetativos", self.styles['MuSectionHeader']))
        elements.append(self._build_vegetation_detail_table())
        elements.append(Spacer(1, 8*mm))
        
        # === PÁGINA 2: Mapas y Análisis ===
        elements.append(PageBreak())
        
        # Sección: Mapas de Color
        elements.append(Paragraph("■ Mapas de Vigor y Estado Hídrico", self.styles['MuSectionHeader']))
        
        # Generar mapas placeholder (en producción, usar datos reales)
        ndvi_map_bytes = generate_placeholder_map("NDVI (Vigor)", self.data.get('ndvi_mean', 0.3), 'RdYlGn')
        ndwi_map_bytes = generate_placeholder_map("NDWI (Agua)", max(0, self.data.get('ndwi_mean', 0)), 'Blues')
        
        maps_table = Table([
            [Image(io.BytesIO(ndvi_map_bytes), width=75*mm, height=55*mm),
             Image(io.BytesIO(ndwi_map_bytes), width=75*mm, height=55*mm)]
        ], colWidths=[80*mm, 80*mm])
        maps_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(maps_table)
        elements.append(Spacer(1, 5*mm))
        
        # Histograma de distribución
        elements.append(Paragraph("■ Distribución de Valores NDVI", self.styles['MuSectionHeader']))
        histogram_bytes = generate_ndvi_histogram(
            self.data.get('ndvi_mean', 0.3),
            self.data.get('ndvi_p10', 0.2),
            self.data.get('ndvi_p90', 0.4)
        )
        elements.append(Image(io.BytesIO(histogram_bytes), width=100*mm, height=65*mm))
        elements.append(Spacer(1, 5*mm))
        
        # Sección: Análisis IA
        elements.append(Paragraph("■ Análisis Agronómico", self.styles['MuSectionHeader']))
        elements.extend(self._build_ai_analysis_section())
        elements.append(Spacer(1, 8*mm))
        
        # === PÁGINA 3: Riesgos y Recomendaciones ===
        elements.append(PageBreak())
        
        # Sección: Evaluación de Riesgos
        elements.append(Paragraph("■ Evaluación de Riesgos", self.styles['MuSectionHeader']))
        elements.append(self._build_risk_table())
        elements.append(Spacer(1, 8*mm))
        
        # Sección: Recomendaciones
        elements.append(Paragraph("■ Recomendaciones Prioritarias", self.styles['MuSectionHeader']))
        elements.extend(self._build_recommendations())
        elements.append(Spacer(1, 8*mm))
        
        # Sección: Anexo Técnico
        elements.append(Paragraph("■ Anexo Técnico", self.styles['MuSectionHeader']))
        elements.extend(self._build_technical_annex())
        
        # Disclaimer final
        elements.append(Spacer(1, 10*mm))
        disclaimer = """
        <i><font size="8" color="#888888">
        Este informe ha sido generado automáticamente mediante análisis de imágenes satelitales. 
        Las recomendaciones deben ser validadas por un técnico agrónomo antes de su implementación. 
        Los datos satelitales están sujetos a disponibilidad y condiciones atmosféricas.
        </font></i>
        """
        elements.append(Paragraph(disclaimer, self.styles['MuSmall']))
        
        # Construir PDF
        doc.build(elements, onFirstPage=self._create_header_footer, 
                  onLaterPages=self._create_header_footer)
        
        self.buffer.seek(0)
        return self.buffer.getvalue()


# ============================================
# FUNCIÓN PRINCIPAL PARA INTEGRACIÓN API
# ============================================

def generate_muorbita_report(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Función principal para generar el informe PDF.
    
    Args:
        data: Diccionario con todos los datos del análisis
        
    Returns:
        Dict con pdf_base64, filename, y metadata
    """
    try:
        generator = MuOrbitaPDFGenerator(data)
        pdf_bytes = generator.generate()
        
        # Codificar en base64
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        # Generar nombre de archivo
        job_id = data.get('job_id', 'UNKNOWN')
        filename = f"Informe_MUORBITA_{job_id}.pdf"
        
        return {
            'success': True,
            'pdf_base64': pdf_base64,
            'filename': filename,
            'pdf_size': len(pdf_bytes),
            'job_id': job_id,
            'generated_at': datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'job_id': data.get('job_id', 'UNKNOWN')
        }


# ============================================
# TEST LOCAL
# ============================================

if __name__ == "__main__":
    # Datos de prueba (simular datos reales)
    test_data = {
        "job_id": "MUORBITA_1765867180435_D49461765",
        "client_name": "Nuria Canamaque",
        "crop_type": "olivar",
        "analysis_type": "BASELINE",
        "start_date": "2025-06-16",
        "end_date": "2025-12-16",
        "area_hectares": 24.8,
        "images_processed": 68,
        "latest_image_date": "2025-12-06",
        
        "ndvi_mean": 0.30,
        "ndvi_p10": 0.23,
        "ndvi_p50": 0.28,
        "ndvi_p90": 0.38,
        "ndvi_stddev": 0.05,
        "ndvi_zscore": -0.01,
        
        "ndwi_mean": -0.01,
        "ndwi_p10": -0.05,
        "ndwi_p90": 0.04,
        
        "evi_mean": 0.29,
        "evi_p10": 0.25,
        "evi_p90": 0.34,
        
        "ndci_mean": 0.11,
        "savi_mean": 0.25,
        
        "stress_area_ha": 20.4,
        "stress_area_pct": 82.3,
        
        "lst_mean_c": 32.6,
        "lst_min_c": 25.0,
        "lst_max_c": 40.0,
        
        "heterogeneity": 0.15,
        
        # Serie temporal de ejemplo
        "time_series": [
            {"date": "2025-06-20", "ndvi": 0.45, "ndwi": 0.15, "evi": 0.38},
            {"date": "2025-07-05", "ndvi": 0.52, "ndwi": 0.18, "evi": 0.42},
            {"date": "2025-07-20", "ndvi": 0.48, "ndwi": 0.12, "evi": 0.40},
            {"date": "2025-08-05", "ndvi": 0.42, "ndwi": 0.08, "evi": 0.35},
            {"date": "2025-08-20", "ndvi": 0.38, "ndwi": 0.05, "evi": 0.32},
            {"date": "2025-09-05", "ndvi": 0.35, "ndwi": 0.02, "evi": 0.30},
            {"date": "2025-09-20", "ndvi": 0.32, "ndwi": -0.01, "evi": 0.28},
            {"date": "2025-10-05", "ndvi": 0.30, "ndwi": -0.02, "evi": 0.27},
            {"date": "2025-10-20", "ndvi": 0.31, "ndwi": 0.00, "evi": 0.28},
            {"date": "2025-11-05", "ndvi": 0.30, "ndwi": -0.01, "evi": 0.29},
            {"date": "2025-12-06", "ndvi": 0.30, "ndwi": -0.01, "evi": 0.29},
        ],
        
        "markdown_analysis": ""  # Vacío para usar análisis automático
    }
    
    result = generate_muorbita_report(test_data)
    
    if result['success']:
        # Guardar PDF de prueba
        with open(f"/tmp/{result['filename']}", 'wb') as f:
            f.write(base64.b64decode(result['pdf_base64']))
        print(f"✅ PDF generado: {result['filename']} ({result['pdf_size']} bytes)")
    else:
        print(f"❌ Error: {result['error']}")
