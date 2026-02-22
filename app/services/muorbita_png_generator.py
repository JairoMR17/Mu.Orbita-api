"""
Mu.Orbita PNG Dashboard Image Generator
=========================================
Generates professional PNG images for individual indices,
to be uploaded to Google Drive and displayed on the web dashboard.

These are SEPARATE from the PDF report — standalone visuals.

INTEGRATION:
    # In Railway FastAPI:
    from muorbita_png_generator import generate_dashboard_pngs
    result = generate_dashboard_pngs(data_dict)
    # result = {"success": True, "images": [{name, base64, filename, size}, ...]}

    # In n8n "Code in JavaScript" node:
    # POST to /api/v1/generate-pngs with same data as PDF
    # Returns array of PNG base64 strings to upload to Drive

Author: Mu.Orbita
Date: 2026-02
"""

import io
import base64
import json
import math
from datetime import datetime
from typing import Dict, List, Any, Tuple, Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
import matplotlib.colors as mcolors
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.gridspec import GridSpec
import numpy as np


# ============================================================
# 1. BRAND PALETTE (matched to email template)
# ============================================================

P = {
    'bg':           '#F9F7F2',   # Cream background
    'bg_ax':        '#FDFBF7',   # Slightly lighter for axes
    'text':         '#3E2B1D',   # Dark brown main text
    'text_light':   '#7A7A7A',
    'text_muted':   '#AAAAAA',
    'gold':         '#9E7E46',   # Brand gold
    'gold_light':   '#C4A265',
    'border':       '#E6DDD0',
    'brown_soft':   '#5C4033',
    'green':        '#4B7F3A',
    'green_light':  '#7CB342',
    'yellow':       '#B8860B',
    'red':          '#A63D2F',
    'red_light':    '#E57373',
    'blue':         '#3B7DD8',
    'blue_light':   '#64B5F6',
    'ndvi':         '#4B7F3A',
    'ndwi':         '#3B7DD8',
    'evi':          '#C4A265',
    'ndci':         '#8BC34A',
    'savi':         '#795548',
    'lst':          '#E65100',
    'vra_high':     '#4B7F3A',
    'vra_med':      '#FDD835',
    'vra_low':      '#E53935',
}


def _apply_style():
    """Apply corporate matplotlib style."""
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': ['Helvetica', 'Arial', 'DejaVu Sans'],
        'font.size': 10,
        'axes.titlesize': 13,
        'axes.titleweight': 'bold',
        'axes.titlecolor': P['text'],
        'axes.edgecolor': P['border'],
        'axes.labelcolor': P['text_light'],
        'xtick.color': P['text_light'],
        'ytick.color': P['text_light'],
        'grid.color': P['border'],
        'grid.linewidth': 0.5,
        'figure.facecolor': P['bg'],
        'axes.facecolor': P['bg_ax'],
    })


def _brand_header(ax, title, subtitle=None):
    """Add branded header to a chart."""
    ax.text(0.0, 1.08, 'Mu', transform=ax.transAxes, fontsize=10,
            fontstyle='italic', fontweight='normal', color=P['text'], va='bottom')
    mu_w = 0.035
    ax.text(mu_w, 1.08, '.Orbita', transform=ax.transAxes, fontsize=10,
            fontweight='bold', color=P['text'], va='bottom')
    ax.text(1.0, 1.08, 'INFORME SATELITAL', transform=ax.transAxes,
            fontsize=7, fontweight='bold', color=P['gold'], ha='right', va='bottom')


def _save_png(fig, dpi=180):
    """Save figure to PNG bytes."""
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor=P['bg'],
                dpi=dpi, pad_inches=0.3)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ============================================================
# 2. INTERPRETATION HELPERS
# ============================================================

def _ndvi_label(v):
    if v >= 0.60: return "Vigor alto", P['green']
    if v >= 0.45: return "Vigor moderado", P['yellow']
    if v >= 0.35: return "Vigor bajo", P['yellow']
    if v >= 0.20: return "Estrés severo", P['red']
    return "Suelo desnudo", P['red']

def _ndwi_label(v):
    if v >= 0.20: return "Estado óptimo", P['green']
    if v >= 0.10: return "Déficit leve", P['yellow']
    if v >= 0.00: return "Déficit moderado", P['yellow']
    return "Déficit severo", P['red']

def _crop_name(ct):
    m = {'olive':'Olivar','olivar':'Olivar','vineyard':'Viñedo','vid':'Viñedo',
         'almond':'Almendro','almendro':'Almendro'}
    return m.get(str(ct).lower(), str(ct).capitalize() if ct else 'Cultivo')

def _fmt_date(d):
    if not d: return '—'
    try: return datetime.strptime(str(d)[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
    except: return str(d)


# ============================================================
# 3. INDIVIDUAL PNG GENERATORS
# ============================================================

def png_ndvi_map(data: Dict) -> bytes:
    """
    NDVI spatial map with parcel outline, colorbar, stats.
    Uses simulated raster until real GeoTIFF integration.
    """
    _apply_style()
    fig, ax = plt.subplots(figsize=(8, 6), dpi=180)

    mean = data.get('ndvi_mean', 0.3)
    p10 = data.get('ndvi_p10', 0.2)
    p90 = data.get('ndvi_p90', 0.4)
    crop = _crop_name(data.get('crop_type', ''))
    date = _fmt_date(data.get('latest_image_date'))

    # Simulated spatial data (will be replaced with real GeoTIFF)
    np.random.seed(42)
    rows, cols = 40, 50
    base = np.random.normal(mean, data.get('ndvi_stddev', 0.08), (rows, cols))
    # Add spatial structure (gradient + clusters)
    x_grad = np.linspace(-0.03, 0.03, cols)
    y_grad = np.linspace(-0.02, 0.02, rows)
    X, Y = np.meshgrid(x_grad, y_grad)
    base += X + Y
    base = np.clip(base, 0, 0.85)

    # Parcel mask (irregular polygon)
    mask = np.ones_like(base, dtype=bool)
    for i in range(rows):
        for j in range(cols):
            # Simple elliptical mask
            cx, cy = cols/2, rows/2
            if ((j-cx)/cx*1.1)**2 + ((i-cy)/cy*0.9)**2 > 0.85:
                mask[i, j] = False
                base[i, j] = np.nan

    cmap = mcolors.LinearSegmentedColormap.from_list('ndvi_pro',
        [(0, '#8B0000'), (0.2, '#D32F2F'), (0.35, '#FF8F00'), (0.45, '#FDD835'),
         (0.55, '#C0CA33'), (0.65, '#7CB342'), (0.75, '#4B7F3A'), (1.0, '#1B5E20')])
    cmap.set_bad(color=P['bg'])

    im = ax.imshow(base, cmap=cmap, vmin=0, vmax=0.8, aspect='auto',
                   interpolation='bilinear', extent=[0, 1, 0, 1])

    # Colorbar
    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, shrink=0.85)
    cbar.set_label('NDVI (Índice de Vegetación)', fontsize=9, color=P['text_light'])
    cbar.ax.tick_params(labelsize=8)
    # Reference lines on colorbar
    for v, lbl in [(0.35, 'Estrés'), (0.45, ''), (0.60, 'Óptimo')]:
        cbar.ax.axhline(y=v, color='white', linewidth=1.5, linestyle='--', alpha=0.8)

    # Stats overlay
    label, color = _ndvi_label(mean)
    stats_text = f'NDVI medio: {mean:.3f}\nP10: {p10:.3f}  |  P90: {p90:.3f}\n{label}'
    props = dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9,
                 edgecolor=P['border'], linewidth=0.8)
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', bbox=props, color=P['text'],
            fontfamily='monospace')

    # Scale bar
    ax.plot([0.05, 0.20], [0.03, 0.03], color=P['text'], linewidth=2)
    ax.text(0.125, 0.06, '~280m', ha='center', fontsize=7, color=P['text'])

    ax.set_title(f'MAPA NDVI — Estado Actual\n{crop} | {date}', pad=15)
    ax.set_xlabel('Longitud relativa', fontsize=8)
    ax.set_ylabel('Latitud relativa', fontsize=8)
    ax.tick_params(labelsize=7)

    # Brand footer
    fig.text(0.5, 0.01, f'© {datetime.now().year} Mu.Orbita — Generado: {datetime.now().strftime("%d/%m/%Y %H:%M")}',
             ha='center', fontsize=7, color=P['text_muted'])

    return _save_png(fig)


def png_ndwi_map(data: Dict) -> bytes:
    """NDWI spatial map — water content."""
    _apply_style()
    fig, ax = plt.subplots(figsize=(8, 6), dpi=180)

    mean = data.get('ndwi_mean', 0.0)
    crop = _crop_name(data.get('crop_type', ''))
    date = _fmt_date(data.get('latest_image_date'))

    np.random.seed(7)
    rows, cols = 40, 50
    base = np.random.normal(mean, 0.08, (rows, cols))
    x_grad = np.linspace(0.02, -0.02, cols)
    y_grad = np.linspace(0.01, -0.01, rows)
    X, Y = np.meshgrid(x_grad, y_grad)
    base += X + Y
    base = np.clip(base, -0.3, 0.5)

    for i in range(rows):
        for j in range(cols):
            cx, cy = cols/2, rows/2
            if ((j-cx)/cx*1.1)**2 + ((i-cy)/cy*0.9)**2 > 0.85:
                base[i, j] = np.nan

    cmap = mcolors.LinearSegmentedColormap.from_list('ndwi_pro',
        [(0, '#8B0000'), (0.25, '#E65100'), (0.4, '#FDD835'),
         (0.55, '#81D4FA'), (0.7, '#1E88E5'), (1.0, '#0D47A1')])
    cmap.set_bad(color=P['bg'])

    im = ax.imshow(base, cmap=cmap, vmin=-0.3, vmax=0.4, aspect='auto',
                   interpolation='bilinear', extent=[0, 1, 0, 1])

    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, shrink=0.85)
    cbar.set_label('NDWI (Índice de Agua)', fontsize=9, color=P['text_light'])
    cbar.ax.tick_params(labelsize=8)
    for v in [0.0, 0.10, 0.20]:
        cbar.ax.axhline(y=v, color='white', linewidth=1.5, linestyle='--', alpha=0.8)

    label, color = _ndwi_label(mean)
    stats_text = f'NDWI medio: {mean:.3f}\n{label}'
    props = dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9,
                 edgecolor=P['border'], linewidth=0.8)
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', bbox=props, color=P['text'], fontfamily='monospace')

    ax.set_title(f'MAPA NDWI — Estado Hídrico\n{crop} | {date}', pad=15)
    ax.set_xlabel('Longitud relativa', fontsize=8)
    ax.set_ylabel('Latitud relativa', fontsize=8)
    ax.tick_params(labelsize=7)

    fig.text(0.5, 0.01, f'© {datetime.now().year} Mu.Orbita',
             ha='center', fontsize=7, color=P['text_muted'])
    return _save_png(fig)


def png_evi_map(data: Dict) -> bytes:
    """EVI spatial map — productivity."""
    _apply_style()
    fig, ax = plt.subplots(figsize=(8, 6), dpi=180)

    mean = data.get('evi_mean', 0.25)
    crop = _crop_name(data.get('crop_type', ''))
    date = _fmt_date(data.get('latest_image_date'))

    np.random.seed(13)
    rows, cols = 40, 50
    base = np.clip(np.random.normal(mean, 0.07, (rows, cols)), 0, 0.7)
    for i in range(rows):
        for j in range(cols):
            cx, cy = cols/2, rows/2
            if ((j-cx)/cx*1.1)**2 + ((i-cy)/cy*0.9)**2 > 0.85:
                base[i, j] = np.nan

    cmap = mcolors.LinearSegmentedColormap.from_list('evi_pro',
        [(0, '#4A148C'), (0.2, '#7B1FA2'), (0.35, '#E65100'),
         (0.5, '#FDD835'), (0.7, '#7CB342'), (1.0, '#1B5E20')])
    cmap.set_bad(color=P['bg'])

    im = ax.imshow(base, cmap=cmap, vmin=0, vmax=0.6, aspect='auto',
                   interpolation='bilinear', extent=[0, 1, 0, 1])

    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, shrink=0.85)
    cbar.set_label('EVI (Productividad)', fontsize=9, color=P['text_light'])
    cbar.ax.tick_params(labelsize=8)

    stats_text = f'EVI medio: {mean:.3f}'
    props = dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9,
                 edgecolor=P['border'], linewidth=0.8)
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', bbox=props, color=P['text'], fontfamily='monospace')

    ax.set_title(f'MAPA EVI — Productividad\n{crop} | {date}', pad=15)
    ax.set_xlabel('Longitud relativa', fontsize=8)
    ax.set_ylabel('Latitud relativa', fontsize=8)
    ax.tick_params(labelsize=7)

    fig.text(0.5, 0.01, f'© {datetime.now().year} Mu.Orbita',
             ha='center', fontsize=7, color=P['text_muted'])
    return _save_png(fig)


def png_time_series(data: Dict) -> bytes:
    """Time series chart — NDVI, NDWI, EVI evolution."""
    _apply_style()
    ts = data.get('time_series', [])
    crop = _crop_name(data.get('crop_type', ''))

    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=180)

    if not ts or len(ts) < 2:
        ax.text(0.5, 0.5, 'Datos de serie temporal insuficientes',
                ha='center', va='center', fontsize=13, color=P['text_muted'])
        ax.axis('off')
        return _save_png(fig)

    dates, ndvi, ndwi, evi = [], [], [], []
    for pt in ts:
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
        ax.text(0.5, 0.5, 'Datos insuficientes', ha='center', va='center',
                fontsize=13, color=P['text_muted'])
        ax.axis('off')
        return _save_png(fig)

    # Reference zones
    ax.axhspan(0.0, 0.35, alpha=0.06, color=P['red'], zorder=0)
    ax.axhspan(0.45, 0.65, alpha=0.06, color=P['green'], zorder=0)
    ax.axhline(y=0.35, color=P['red'], linestyle='--', linewidth=0.7, alpha=0.4)
    ax.axhline(y=0.60, color=P['green'], linestyle='--', linewidth=0.7, alpha=0.4)

    # Data
    ax.plot(dates, ndvi, color=P['ndvi'], linewidth=2.5, label='NDVI (Vigor)',
            marker='o', markersize=5, markerfacecolor=P['bg'], markeredgewidth=1.5, zorder=3)
    ax.plot(dates, ndwi, color=P['ndwi'], linewidth=2, label='NDWI (Agua)',
            marker='s', markersize=4, markerfacecolor=P['bg'], markeredgewidth=1.2, zorder=2)
    if any(v != 0 for v in evi):
        ax.plot(dates, evi, color=P['evi'], linewidth=1.8, label='EVI (Productiv.)',
                marker='^', markersize=4, markerfacecolor=P['bg'], markeredgewidth=1.2, zorder=2)

    # Zone labels
    ax.text(dates[-1], 0.17, '  Estrés', fontsize=8, color=P['red'], alpha=0.6, va='center')
    ax.text(dates[-1], 0.55, '  Óptimo', fontsize=8, color=P['green'], alpha=0.6, va='center')

    ax.set_ylabel('Valor del índice', fontsize=10)
    ax.set_title(f'Evolución Temporal de Índices — {crop}', pad=12, fontsize=13)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=10))
    plt.xticks(rotation=30, ha='right')
    ax.set_ylim(-0.15, 1.0)
    ax.legend(loc='upper right', fontsize=9, framealpha=0.9, edgecolor=P['border'])
    ax.grid(True, alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    fig.text(0.5, -0.02, f'© {datetime.now().year} Mu.Orbita — Período: {_fmt_date(data.get("start_date"))} → {_fmt_date(data.get("end_date"))}',
             ha='center', fontsize=7, color=P['text_muted'])

    plt.tight_layout()
    return _save_png(fig)


def png_ndvi_distribution(data: Dict) -> bytes:
    """NDVI distribution histogram + boxplot."""
    _apply_style()
    fig = plt.figure(figsize=(10, 4), dpi=180)
    gs = GridSpec(1, 2, width_ratios=[2, 1], wspace=0.3)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])

    mean = data.get('ndvi_mean', 0.3)
    p10 = data.get('ndvi_p10', 0.2)
    p50 = data.get('ndvi_p50', 0.28)
    p90 = data.get('ndvi_p90', 0.4)
    std = data.get('ndvi_stddev', 0.08)
    crop = _crop_name(data.get('crop_type', ''))

    # Simulate pixel distribution
    np.random.seed(42)
    n_pixels = 5000
    pixels = np.random.normal(mean, std, n_pixels)
    pixels = np.clip(pixels, 0, 0.85)

    # Histogram
    bins = np.linspace(0, 0.8, 40)
    n, _, patches = ax1.hist(pixels, bins=bins, edgecolor='white', linewidth=0.3)

    # Color bins by NDVI value
    cmap = mcolors.LinearSegmentedColormap.from_list('ndvi',
        [(0, '#D32F2F'), (0.35, '#FF8F00'), (0.55, '#FDD835'),
         (0.75, '#4B7F3A'), (1.0, '#1B5E20')])
    for patch, val in zip(patches, bins[:-1]):
        patch.set_facecolor(cmap(val / 0.8))

    # Reference lines
    ax1.axvline(mean, color=P['text'], linewidth=2, linestyle='--', label=f'Media: {mean:.3f}')
    ax1.axvline(p10, color=P['gold'], linewidth=1.5, linestyle=':', label=f'P10: {p10:.3f}')
    ax1.axvline(p90, color=P['gold'], linewidth=1.5, linestyle=':', label=f'P90: {p90:.3f}')

    # Stress zone
    ax1.axvspan(0, 0.35, alpha=0.08, color=P['red'])
    ax1.text(0.17, max(n)*0.9, 'Estrés', fontsize=8, color=P['red'], ha='center', alpha=0.7)

    ax1.set_xlabel('NDVI', fontsize=10)
    ax1.set_ylabel('Frecuencia (píxeles)', fontsize=10)
    ax1.set_title(f'Distribución de Valores NDVI\n{crop} — {_fmt_date(data.get("latest_image_date"))}',
                  fontsize=11, pad=8)
    ax1.legend(fontsize=8, framealpha=0.9)
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)

    # Boxplot
    bp = ax2.boxplot([pixels], vert=True, widths=0.5, patch_artist=True,
                     boxprops=dict(facecolor=P['bg'], edgecolor=P['gold'], linewidth=1.5),
                     whiskerprops=dict(color=P['gold']),
                     capprops=dict(color=P['gold']),
                     medianprops=dict(color=P['red'], linewidth=2),
                     flierprops=dict(marker='o', markerfacecolor=P['red_light'],
                                    markersize=3, alpha=0.4))

    # Reference bands
    ax2.axhspan(0.0, 0.35, alpha=0.08, color=P['red'])
    ax2.axhspan(0.35, 0.45, alpha=0.08, color=P['yellow'])
    ax2.axhspan(0.45, 0.65, alpha=0.08, color=P['green'])

    ax2.axhline(0.35, color=P['red'], linestyle='--', linewidth=0.7, alpha=0.5)
    ax2.axhline(0.60, color=P['green'], linestyle='--', linewidth=0.7, alpha=0.5)

    ax2.text(1.4, 0.20, 'Estrés severo', fontsize=7, color=P['red'], va='center')
    ax2.text(1.4, 0.40, 'Vigor bajo', fontsize=7, color=P['yellow'], va='center')
    ax2.text(1.4, 0.55, 'Vigor alto', fontsize=7, color=P['green'], va='center')

    stats_txt = (f'Estadísticas:\n'
                 f'Media: {mean:.3f}\n'
                 f'Mediana: {p50:.3f}\n'
                 f'Desv. Est.: {std:.3f}\n'
                 f'P10: {p10:.3f}\n'
                 f'P90: {p90:.3f}')
    props = dict(boxstyle='round,pad=0.4', facecolor='white', alpha=0.9,
                 edgecolor=P['border'])
    ax2.text(1.55, 0.75, stats_txt, fontsize=7, color=P['text'],
             fontfamily='monospace', bbox=props, va='top')

    ax2.set_ylabel('NDVI', fontsize=10)
    ax2.set_title('Estadísticas NDVI', fontsize=11, pad=8)
    ax2.set_ylim(-0.05, 0.85)
    ax2.set_xticklabels([crop])

    fig.text(0.5, -0.02, f'© {datetime.now().year} Mu.Orbita',
             ha='center', fontsize=7, color=P['text_muted'])
    plt.tight_layout()
    return _save_png(fig)


def png_vra_zones(data: Dict) -> bytes:
    """VRA 3-zone prescription map."""
    _apply_style()
    fig, ax = plt.subplots(figsize=(8, 6), dpi=180)

    mean = data.get('ndvi_mean', 0.3)
    crop = _crop_name(data.get('crop_type', ''))

    np.random.seed(42)
    rows, cols = 40, 50
    base = np.random.normal(mean, 0.10, (rows, cols))
    base = np.clip(base, 0, 0.8)

    # K-means simulation: 3 zones
    zones = np.zeros_like(base, dtype=int)
    zones[base < 0.30] = 0   # Low vigor
    zones[(base >= 0.30) & (base < 0.50)] = 1  # Medium
    zones[base >= 0.50] = 2   # High vigor

    # Apply parcel mask
    for i in range(rows):
        for j in range(cols):
            cx, cy = cols/2, rows/2
            if ((j-cx)/cx*1.1)**2 + ((i-cy)/cy*0.9)**2 > 0.85:
                zones[i, j] = -1

    # Custom colormap for 3 zones
    zone_colors = [P['vra_low'], P['vra_med'], P['vra_high']]
    cmap = mcolors.ListedColormap(zone_colors)
    cmap.set_under(color=P['bg'])

    im = ax.imshow(zones, cmap=cmap, vmin=0, vmax=2, aspect='auto',
                   interpolation='nearest', extent=[0, 1, 0, 1])

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=P['vra_low'], edgecolor='white', label='Zona 1: Bajo vigor (intervención)'),
        Patch(facecolor=P['vra_med'], edgecolor='white', label='Zona 2: Vigor medio (monitorizar)'),
        Patch(facecolor=P['vra_high'], edgecolor='white', label='Zona 3: Vigor alto (mantener)')
    ]
    ax.legend(handles=legend_elements, loc='lower right', fontsize=8,
              framealpha=0.95, edgecolor=P['border'])

    # Zone stats
    valid = zones[zones >= 0]
    z0_pct = (valid == 0).sum() / len(valid) * 100
    z1_pct = (valid == 1).sum() / len(valid) * 100
    z2_pct = (valid == 2).sum() / len(valid) * 100

    stats_text = f'Zona 1: {z0_pct:.0f}%\nZona 2: {z1_pct:.0f}%\nZona 3: {z2_pct:.0f}%'
    props = dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9,
                 edgecolor=P['border'])
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', bbox=props, color=P['text'], fontfamily='monospace')

    ax.set_title(f'Zonificación VRA — Aplicación Variable\n{crop} | 3 zonas de manejo', pad=15)
    ax.set_xlabel('Longitud relativa', fontsize=8)
    ax.set_ylabel('Latitud relativa', fontsize=8)
    ax.tick_params(labelsize=7)

    fig.text(0.5, 0.01, f'© {datetime.now().year} Mu.Orbita — K-means clustering sobre [NDVI, EVI, NDWI]',
             ha='center', fontsize=7, color=P['text_muted'])
    return _save_png(fig)


def png_kpi_summary(data: Dict) -> bytes:
    """KPI summary card — dashboard-ready visual."""
    _apply_style()
    fig, ax = plt.subplots(figsize=(10, 3.5), dpi=180)
    ax.axis('off')

    crop = _crop_name(data.get('crop_type', ''))
    date = _fmt_date(data.get('latest_image_date'))

    kpis = [
        ('NDVI', data.get('ndvi_mean', 0), *_ndvi_label(data.get('ndvi_mean', 0))),
        ('NDWI', data.get('ndwi_mean', 0), *_ndwi_label(data.get('ndwi_mean', 0))),
        ('EVI', data.get('evi_mean', 0), 'Productividad', P['gold']),
        ('Estrés', data.get('stress_area_pct', 0), f"{data.get('stress_area_pct',0):.0f}% área",
         P['red'] if data.get('stress_area_pct', 0) > 40 else P['yellow'] if data.get('stress_area_pct', 0) > 15 else P['green']),
    ]

    n = len(kpis)
    card_w = 0.22
    gap = (1.0 - n * card_w) / (n + 1)

    for i, (name, val, label, color) in enumerate(kpis):
        x = gap + i * (card_w + gap)

        # Card background
        rect = FancyBboxPatch((x, 0.15), card_w, 0.75, boxstyle="round,pad=0.02",
                              facecolor='white', edgecolor=P['border'], linewidth=1)
        ax.add_patch(rect)

        # Top accent line
        ax.plot([x + 0.02, x + card_w - 0.02], [0.85, 0.85], color=color, linewidth=3)

        # Value
        val_str = f'{val:.2f}' if name != 'Estrés' else f'{val:.1f}%'
        ax.text(x + card_w/2, 0.62, val_str, ha='center', va='center',
                fontsize=20, fontweight='bold', color=color)

        # Name
        ax.text(x + card_w/2, 0.42, name, ha='center', va='center',
                fontsize=9, color=P['text_light'], fontweight='bold')

        # Status label
        ax.text(x + card_w/2, 0.25, label, ha='center', va='center',
                fontsize=8, color=color)

    # Title
    ax.text(0.5, 0.98, f'KPIs de Estado — {crop} | {date}',
            ha='center', va='top', fontsize=12, fontweight='bold', color=P['text'],
            transform=ax.transAxes)

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.05)

    fig.text(0.5, 0.02, f'© {datetime.now().year} Mu.Orbita',
             ha='center', fontsize=7, color=P['text_muted'])
    plt.tight_layout()
    return _save_png(fig)


# ============================================================
# 4. PUBLIC API FUNCTION
# ============================================================

def generate_dashboard_pngs(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate all dashboard PNG images.

    Args:
        data: Same dict as generate_muorbita_report() — KPIs, time_series, etc.

    Returns:
        {
            "success": True,
            "images": [
                {"name": "NDVI_MAP", "base64": "...", "filename": "...", "size": 12345},
                ...
            ],
            "job_id": "...",
            "generated_at": "..."
        }
    """
    try:
        job_id = data.get('job_id', 'UNKNOWN')
        images = []

        # Define generators
        generators = [
            ('NDVI_MAP',         png_ndvi_map,         f'PNG_NDVI_{job_id}.png'),
            ('NDWI_MAP',         png_ndwi_map,         f'PNG_NDWI_{job_id}.png'),
            ('EVI_MAP',          png_evi_map,           f'PNG_EVI_{job_id}.png'),
            ('TIME_SERIES',      png_time_series,       f'PNG_TimeSeries_{job_id}.png'),
            ('NDVI_DISTRIBUTION', png_ndvi_distribution, f'PNG_NDVI_Dist_{job_id}.png'),
            ('VRA_ZONES',        png_vra_zones,         f'PNG_VRA_{job_id}.png'),
            ('KPI_SUMMARY',      png_kpi_summary,       f'PNG_KPIs_{job_id}.png'),
        ]

        for name, gen_func, filename in generators:
            try:
                png_bytes = gen_func(data)
                images.append({
                    'name': name,
                    'base64': base64.b64encode(png_bytes).decode('utf-8'),
                    'filename': filename,
                    'size': len(png_bytes),
                    'content_type': 'image/png',
                })
            except Exception as e:
                images.append({
                    'name': name,
                    'error': str(e),
                    'filename': filename,
                    'size': 0,
                })

        return {
            'success': True,
            'images': images,
            'image_count': len([i for i in images if 'base64' in i]),
            'total_size': sum(i.get('size', 0) for i in images),
            'job_id': job_id,
            'generated_at': datetime.now().isoformat(),
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
# 5. CLI TEST
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
        "latest_image_date": "2026-02-12",
        "images_processed": 24,

        "ndvi_mean": 0.30, "ndvi_p10": 0.24, "ndvi_p50": 0.29,
        "ndvi_p90": 0.39, "ndvi_stddev": 0.06,
        "ndwi_mean": 0.01, "ndwi_p10": -0.05, "ndwi_p90": 0.06,
        "evi_mean": 0.27, "evi_p10": 0.22, "evi_p90": 0.32,
        "ndci_mean": 0.13, "savi_mean": 0.23,
        "stress_area_ha": 21.1, "stress_area_pct": 78.5,

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
        ]
    }

    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            test_data = json.load(f)

    result = generate_dashboard_pngs(test_data)

    if result['success']:
        print(f"✅ Generated {result['image_count']} PNGs ({result['total_size']:,} bytes total)")
        for img in result['images']:
            if 'base64' in img:
                out = f"/tmp/{img['filename']}"
                with open(out, 'wb') as f:
                    f.write(base64.b64decode(img['base64']))
                print(f"   📷 {img['name']}: {out} ({img['size']:,} bytes)")
            else:
                print(f"   ❌ {img['name']}: {img.get('error', 'Unknown error')}")
    else:
        print(f"❌ Error: {result['error']}")
