#!/usr/bin/env python3
"""
Mu.Orbita GEE Automation Script v5.2 (FLAT 2D MAPS)
=====================================================

CAMBIOS V5.2 vs V5.1:
✅ MAPAS PLANOS 2D: Vista cenital (bird's eye), NO perspectiva 3D
✅ Índice clipado a la parcela: píxeles fuera = fondo claro (#F5F5F0)
✅ Contorno oscuro (#333) de la parcela para delimitación clara
✅ Región = bounding box rectangular (roi.bounds()) — elimina efecto 3D
✅ Sin blending con RGB satelital (heatmap puro del índice)
✅ Leyenda profesional con fondo claro, marcador de media, etiquetas min/max
✅ RGB satelital también plano 2D con clip + fondo neutro
✅ Todo lo demás IDÉNTICO a v5.1 (ERA5, VRA, series temporales, persist_images)

MODOS:
    baseline:   Análisis completo (todos los índices + VRA + LST + imágenes planas)
    biweekly:   Seguimiento ligero (NDVI + NDWI + weather ERA5)
"""

import argparse
import json
import ee
import sys
import os
import io
import base64
import urllib.request
from datetime import datetime, timedelta

# ============================================================================
# INICIALIZACIÓN
# ============================================================================

def initialize_gee():
    """Initialize Earth Engine with Service Account or default credentials"""
    try:
        service_account_key = os.environ.get('GEE_SERVICE_ACCOUNT_KEY')
        if service_account_key:
            key_data = json.loads(service_account_key)
            credentials = ee.ServiceAccountCredentials(
                email=key_data['client_email'],
                key_data=service_account_key
            )
            ee.Initialize(credentials)
        else:
            ee.Initialize()
        return True
    except Exception as e:
        print(json.dumps({"error": f"Failed to initialize GEE: {str(e)}"}))
        return False

if not initialize_gee():
    sys.exit(1)

# ============================================================================
# PALETAS DE VISUALIZACIÓN (v5.2: sin 'alpha', añadido 'unit')
# ============================================================================

VIZ_PALETTES = {
    'NDVI': {
        'min': 0.0, 'max': 0.8,
        'palette': ['8B0000', 'FF0000', 'FF6347', 'FFA500', 'FFFF00', 
                    'ADFF2F', '7CFC00', '32CD32', '228B22', '006400'],
        'label': 'NDVI (Vigor Vegetativo)',
        'unit': ''
    },
    'NDWI': {
        'min': -0.3, 'max': 0.4,
        'palette': ['8B4513', 'D2691E', 'F4A460', 'FFF8DC', 'E0FFFF', 
                    '87CEEB', '4682B4', '0000CD', '00008B'],
        'label': 'NDWI (Estado Hídrico)',
        'unit': ''
    },
    'EVI': {
        'min': 0.0, 'max': 0.6,
        'palette': ['8B0000', 'CD5C5C', 'F08080', 'FFFFE0', 'ADFF2F', 
                    '7FFF00', '32CD32', '228B22', '006400'],
        'label': 'EVI (Productividad)',
        'unit': ''
    },
    'NDCI': {
        'min': -0.2, 'max': 0.6,
        'palette': ['8B0000', 'FF6347', 'FFA500', 'FFFF00', 'ADFF2F', 
                    '7CFC00', '32CD32', '228B22', '006400'],
        'label': 'NDCI (Clorofila)',
        'unit': ''
    },
    'SAVI': {
        'min': 0.0, 'max': 0.8,
        'palette': ['8B0000', 'FF0000', 'FF6347', 'FFA500', 'FFFF00', 
                    'ADFF2F', '7CFC00', '32CD32', '228B22', '006400'],
        'label': 'SAVI (Vigor Ajustado Suelo)',
        'unit': ''
    },
    'VRA': {
        'min': 0, 'max': 2,
        'palette': ['e74c3c', 'f1c40f', '27ae60'],
        'label': 'Zonas de Manejo Variable',
        'unit': ''
    },
    'LST': {
        'min': 15, 'max': 45,
        'palette': ['0000FF', '00FFFF', '00FF00', 'FFFF00', 'FF0000'],
        'label': 'Temperatura Superficial',
        'unit': '°C'
    }
}

# ============================================================================
# ARGUMENTOS
# ============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description='Mu.Orbita GEE Automation v5.2 (Flat 2D Maps)')
    parser.add_argument('--mode', required=True, 
                        choices=['execute', 'check-status', 'download-results', 'start-tasks'])
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--roi', help='GeoJSON string of ROI')
    parser.add_argument('--start-date', help='Start date YYYY-MM-DD')
    parser.add_argument('--end-date', help='End date YYYY-MM-DD')
    parser.add_argument('--crop', default='olivar', help='Crop type')
    parser.add_argument('--buffer', type=int, default=0, help='Buffer in meters')
    parser.add_argument('--analysis-type', default='baseline', help='Type of analysis: baseline or biweekly')
    parser.add_argument('--drive-folder', default='MuOrbita_Outputs', help='(legacy, unused)')
    parser.add_argument('--output-dir', help='Local output directory')
    parser.add_argument('--export-png', type=bool, default=True, help='Export PNG for web dashboard')
    return parser.parse_args()

# ============================================================================
# UTILIDADES
# ============================================================================

def create_roi(geojson_str, buffer_meters=0):
    """Create EE geometry from GeoJSON"""
    try:
        geojson = json.loads(geojson_str)
        if geojson.get('type') == 'FeatureCollection':
            roi = ee.FeatureCollection(geojson).geometry()
        elif geojson.get('type') == 'Feature':
            roi = ee.Geometry(geojson['geometry'])
        else:
            roi = ee.Geometry(geojson)
        
        if buffer_meters > 0:
            roi = roi.buffer(buffer_meters)
        return roi
    except Exception as e:
        raise ValueError(f"Invalid GeoJSON: {str(e)}")


def get_bounds(roi):
    """Get bounds of ROI for Leaflet positioning"""
    try:
        bounds = roi.bounds().coordinates().getInfo()[0]
        lngs = [p[0] for p in bounds]
        lats = [p[1] for p in bounds]
        return {
            'south': min(lats),
            'west': min(lngs),
            'north': max(lats),
            'east': max(lngs)
        }
    except Exception as e:
        print(f"Warning: Could not get bounds: {e}")
        return None


# ============================================================================
# GENERACIÓN DE IMÁGENES PLANAS 2D (v5.2 — REEMPLAZA v5.1 composites)
# ============================================================================

def get_flat_index_png(index_image, roi, viz_params, dimensions=1024,
                       bg_color='F5F5F0', boundary_color='333333',
                       boundary_width=2):
    """
    Genera un PNG PLANO 2D del índice, vista cenital (bird's eye).
    
    DIFERENCIAS CON v5.1 (get_composite_png_base64):
    ✅ SIN mezcla con imagen RGB satelital → heatmap puro
    ✅ Clip estricto a la parcela → fuera = fondo neutro (#F5F5F0)
    ✅ Región = roi.bounds() (rectángulo) → NO perspectiva 3D
    ✅ Contorno oscuro (#333) → mejor contraste sobre colores claros
    
    Args:
        index_image:    ee.Image con 1 banda del índice (NDVI, NDWI, etc.)
        roi:            ee.Geometry de la parcela
        viz_params:     dict con min, max, palette
        dimensions:     resolución máxima del PNG (default 1024)
        bg_color:       hex del fondo fuera de parcela (default F5F5F0)
        boundary_color: hex del contorno de parcela (default 333333)
        boundary_width: grosor contorno en píxeles (default 2)
    
    Returns:
        str: PNG en base64, o None si falla
    """
    try:
        # ── 1. Clipar índice a la parcela ───────────────────────────
        clipped = index_image.clip(roi)
        
        # ── 2. Fondo sólido del color deseado ───────────────────────
        bg_r = int(bg_color[0:2], 16)
        bg_g = int(bg_color[2:4], 16)
        bg_b = int(bg_color[4:6], 16)
        
        bg_image = ee.Image([
            ee.Image.constant(bg_r).toUint8().rename('vis-red'),
            ee.Image.constant(bg_g).toUint8().rename('vis-green'),
            ee.Image.constant(bg_b).toUint8().rename('vis-blue')
        ])
        
        # ── 3. Colorear el índice con la paleta ─────────────────────
        index_viz = {k: v for k, v in viz_params.items() if k in ('min', 'max', 'palette')}
        index_colored = clipped.visualize(**index_viz)
        
        # ── 4. Componer: fondo + índice (solo dentro de parcela) ────
        # El .clip(roi) hace que fuera de la parcela no haya datos
        # → .blend() solo pinta donde hay datos → fondo visible fuera
        composed = bg_image.blend(index_colored)
        
        # ── 5. Contorno de la parcela ───────────────────────────────
        roi_fc = ee.FeatureCollection([ee.Feature(roi)])
        outline = ee.Image().byte().paint(
            featureCollection=roi_fc,
            color=1,
            width=boundary_width
        )
        outline_vis = outline.visualize(palette=[boundary_color], min=0, max=1)
        final = composed.blend(outline_vis)
        
        # ── 6. Región = bounding box RECTANGULAR ────────────────────
        # CLAVE: roi.bounds() genera un rectángulo perfecto alineado
        # a los ejes → vista cenital plana, SIN perspectiva 3D
        bbox = roi.bounds()
        region_coords = bbox.getInfo()['coordinates']
        
        # ── 7. Generar thumbnail y descargar ────────────────────────
        url = final.getThumbURL({
            'region': region_coords,
            'dimensions': dimensions,
            'format': 'png'
        })
        
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'MuOrbita/5.2')
        response = urllib.request.urlopen(req, timeout=60)
        png_bytes = response.read()
        
        if len(png_bytes) < 100:
            print(f"Warning: Flat PNG too small ({len(png_bytes)} bytes)")
            return None
        
        return base64.b64encode(png_bytes).decode('utf-8')
    
    except Exception as e:
        print(f"Warning: Could not generate flat index PNG: {e}")
        return None


def get_flat_rgb_png(sentinel_rgb_image, roi, dimensions=1024,
                     bg_color='F5F5F0', boundary_color='333333',
                     boundary_width=2):
    """
    Genera un PNG plano 2D de la imagen satelital true-color (RGB).
    Mismo estilo visual que get_flat_index_png para consistencia.
    """
    try:
        # Clipar a la parcela y visualizar
        rgb = sentinel_rgb_image.select(['B4', 'B3', 'B2']).clip(roi).visualize(
            min=0, max=0.3, gamma=1.3
        )
        
        # Fondo sólido
        bg_r = int(bg_color[0:2], 16)
        bg_g = int(bg_color[2:4], 16)
        bg_b = int(bg_color[4:6], 16)
        bg_image = ee.Image([
            ee.Image.constant(bg_r).toUint8().rename('vis-red'),
            ee.Image.constant(bg_g).toUint8().rename('vis-green'),
            ee.Image.constant(bg_b).toUint8().rename('vis-blue')
        ])
        
        composed = bg_image.blend(rgb)
        
        # Contorno
        roi_fc = ee.FeatureCollection([ee.Feature(roi)])
        outline = ee.Image().byte().paint(roi_fc, 1, boundary_width)
        outline_vis = outline.visualize(palette=[boundary_color], min=0, max=1)
        final = composed.blend(outline_vis)
        
        # Bounding box rectangular
        bbox = roi.bounds()
        region_coords = bbox.getInfo()['coordinates']
        
        url = final.getThumbURL({
            'region': region_coords,
            'dimensions': dimensions,
            'format': 'png'
        })
        
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'MuOrbita/5.2')
        response = urllib.request.urlopen(req, timeout=60)
        png_bytes = response.read()
        
        if len(png_bytes) < 100:
            return None
        
        return base64.b64encode(png_bytes).decode('utf-8')
    
    except Exception as e:
        print(f"Warning: Could not generate flat RGB PNG: {e}")
        return None


# ============================================================================
# LEYENDA PROFESIONAL (v5.2 — REEMPLAZA add_legend_to_png)
# ============================================================================

def add_professional_legend(png_base64, index_name, mean_value=None):
    """
    Añade leyenda profesional al PNG: título, colorbar, estadísticas.
    
    Mejoras vs v5.1 (add_legend_to_png):
    ✅ Fondo claro (#F9F7F2) → legible en PDF e impresión
    ✅ Texto oscuro para mejor contraste
    ✅ Marcador triangular del valor medio sobre la barra
    ✅ Etiquetas min/max en los extremos con unidades
    ✅ Color de acento marrón Mu.Orbita para el título
    
    Args:
        png_base64:  PNG en base64
        index_name:  'NDVI', 'NDWI', etc.
        mean_value:  valor medio para marcar en la barra
    
    Returns:
        PNG con leyenda, en base64
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Warning: Pillow not installed, returning PNG without legend")
        return png_base64
    
    viz = VIZ_PALETTES.get(index_name)
    if not viz:
        return png_base64
    
    # Decodificar imagen
    img_bytes = base64.b64decode(png_base64)
    img = Image.open(io.BytesIO(img_bytes)).convert('RGBA')
    
    # ── Dimensiones de la leyenda ───────────────────────────────
    legend_h = 90
    pad = 20
    bar_h = 18
    bar_w = min(350, img.width - 2 * pad)
    
    # ── Colores ─────────────────────────────────────────────────
    bg_color = (249, 247, 242, 255)    # #F9F7F2
    text_color = (51, 51, 51)           # #333333
    text_muted = (136, 136, 136)        # #888888
    accent_color = (139, 69, 19)        # #8B4513 (marrón Mu.Orbita)
    
    # ── Nueva imagen con leyenda abajo ──────────────────────────
    new_img = Image.new('RGBA', (img.width, img.height + legend_h), bg_color)
    new_img.paste(img, (0, 0))
    draw = ImageDraw.Draw(new_img)
    
    # Línea separadora
    draw.line([(0, img.height), (img.width, img.height)], fill=(200, 195, 185), width=1)
    
    # ── Fuentes ─────────────────────────────────────────────────
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        font_value = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    except (OSError, IOError):
        font_title = ImageFont.load_default()
        font_small = font_title
        font_value = font_title
    
    y0 = img.height + 8
    
    # ── Título del índice ───────────────────────────────────────
    label = viz.get('label', index_name)
    draw.text((pad, y0), label, fill=accent_color, font=font_title)
    
    # Valor medio a la derecha del título
    if mean_value is not None:
        mean_text = f"Media: {mean_value:.2f}"
        try:
            title_bbox = draw.textbbox((0, 0), label, font=font_title)
            title_w = title_bbox[2] - title_bbox[0]
        except AttributeError:
            title_w = len(label) * 8
        draw.text((pad + title_w + 20, y0 + 1), mean_text, fill=text_color, font=font_value)
    
    # ── Barra de color (colorbar) ───────────────────────────────
    bar_y = y0 + 24
    bar_x = pad
    
    colors_hex = viz['palette']
    colors_rgb = [tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) for h in colors_hex]
    n = len(colors_rgb)
    
    # Dibujar gradiente
    for x in range(bar_w):
        t = x / bar_w
        idx = t * (n - 1)
        i = min(int(idx), n - 2)
        f = idx - i
        c1, c2 = colors_rgb[i], colors_rgb[i + 1]
        color = tuple(int(c1[j] * (1 - f) + c2[j] * f) for j in range(3))
        draw.rectangle([bar_x + x, bar_y, bar_x + x + 1, bar_y + bar_h], fill=color)
    
    # Borde de la barra
    draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], outline=(100, 100, 100), width=1)
    
    # ── Etiquetas min/max ───────────────────────────────────────
    min_val = viz['min']
    max_val = viz['max']
    unit = viz.get('unit', '')
    
    draw.text((bar_x, bar_y + bar_h + 3), f"{min_val}{unit}", fill=text_muted, font=font_small)
    
    max_text = f"{max_val}{unit}"
    try:
        max_bbox = draw.textbbox((0, 0), max_text, font=font_small)
        max_w = max_bbox[2] - max_bbox[0]
    except AttributeError:
        max_w = len(max_text) * 6
    draw.text((bar_x + bar_w - max_w, bar_y + bar_h + 3), max_text, fill=text_muted, font=font_small)
    
    # ── Marcador del valor medio sobre la barra ─────────────────
    if mean_value is not None:
        val_range = max_val - min_val
        if val_range > 0:
            t = max(0, min(1, (mean_value - min_val) / val_range))
            marker_x = bar_x + int(t * bar_w)
            
            # Triángulo invertido (▼) apuntando a la barra
            triangle_size = 6
            draw.polygon([
                (marker_x, bar_y - 2),
                (marker_x - triangle_size, bar_y - 2 - triangle_size),
                (marker_x + triangle_size, bar_y - 2 - triangle_size)
            ], fill=text_color)
    
    # ── Convertir RGBA → RGB para compatibilidad ────────────────
    final_img = Image.new('RGB', new_img.size, (249, 247, 242))
    final_img.paste(new_img, mask=new_img.split()[3])
    
    buf = io.BytesIO()
    final_img.save(buf, format='PNG', optimize=True)
    buf.seek(0)
    
    return base64.b64encode(buf.getvalue()).decode('utf-8')


# ============================================================================
# COLECCIONES DE DATOS
# ============================================================================

def get_sentinel2_collection(roi, start_date, end_date):
    """Get Sentinel-2 SR collection with cloud masking"""
    def mask_clouds(image):
        qa = image.select('QA60')
        scl = image.select('SCL')
        
        cloud_mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
        scl_mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
        
        return image.updateMask(cloud_mask.And(scl_mask)).divide(10000).copyProperties(image, ['system:time_start'])
    
    collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(roi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
        .map(mask_clouds))
    
    return collection


def calculate_indices(image):
    """Calculate all vegetation indices"""
    nir = image.select('B8')
    red = image.select('B4')
    blue = image.select('B2')
    swir = image.select('B11')
    red_edge = image.select('B5')
    
    ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
    ndwi = image.normalizedDifference(['B8', 'B11']).rename('NDWI')
    
    evi = image.expression(
        '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
        {'NIR': nir, 'RED': red, 'BLUE': blue}
    ).rename('EVI')
    
    ndci = image.normalizedDifference(['B5', 'B4']).rename('NDCI')
    
    L = 0.5
    savi = nir.subtract(red).divide(nir.add(red).add(L)).multiply(1 + L).rename('SAVI')
    osavi = nir.subtract(red).divide(nir.add(red).add(0.16)).multiply(1.16).rename('OSAVI')
    
    return image.addBands([ndvi, ndwi, evi, ndci, savi, osavi])


def get_modis_lst(roi, start_date, end_date):
    """Get MODIS Land Surface Temperature"""
    modis = (ee.ImageCollection('MODIS/061/MOD11A2')
        .filterBounds(roi)
        .filterDate(start_date, end_date)
        .select('LST_Day_1km')
        .map(lambda img: img.multiply(0.02).subtract(273.15).rename('LST_C')
             .copyProperties(img, ['system:time_start'])))
    
    return modis.median().clip(roi)

# ============================================================================
# VRA ZONIFICACIÓN
# ============================================================================

def calculate_vra_zones(composite, roi):
    """Calculate VRA zones using k-means clustering"""
    try:
        training_bands = ['NDVI', 'EVI', 'NDWI']
        training_image = composite.select(training_bands)
        
        valid_mask = training_image.mask().reduce(ee.Reducer.min())
        training_masked = training_image.updateMask(valid_mask)
        
        sample = training_masked.sample(
            region=roi,
            scale=20,
            numPixels=5000,
            geometries=False
        )
        
        clusterer = ee.Clusterer.wekaKMeans(3).train(sample)
        vra = training_masked.cluster(clusterer).rename('zone')
        
        vra_stats = []
        for zone_num in range(3):
            zone_mask = vra.eq(zone_num)
            zone_area = zone_mask.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=roi,
                scale=20,
                maxPixels=1e9
            ).getInfo()
            
            zone_indices = composite.select(['NDVI', 'NDWI', 'EVI']).updateMask(zone_mask).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=roi,
                scale=20,
                maxPixels=1e9
            ).getInfo()
            
            area_ha = zone_area.get('zone', 0) / 10000
            vra_stats.append({
                'zone': zone_num,
                'area_ha': round(area_ha, 2),
                'ndvi_mean': round(zone_indices.get('NDVI', 0) or 0, 3),
                'ndwi_mean': round(zone_indices.get('NDWI', 0) or 0, 3),
                'evi_mean': round(zone_indices.get('EVI', 0) or 0, 3)
            })
        
        vra_stats.sort(key=lambda x: x['ndvi_mean'])
        labels = ['Bajo vigor', 'Vigor medio', 'Alto vigor']
        recommendations = ['Dosis alta', 'Dosis media', 'Dosis baja']
        
        for i, stat in enumerate(vra_stats):
            stat['label'] = labels[i]
            stat['recommendation'] = recommendations[i]
        
        return vra, vra_stats
        
    except Exception as e:
        print(f"Warning: VRA calculation failed: {e}")
        return None, []

# ============================================================================
# ERA5 WEATHER DATA
# ============================================================================

def get_era5_weather(roi, start_date, end_date):
    """
    Obtiene datos meteorológicos de ERA5-Land para el período.
    """
    weather_kpis = {}
    daily_series = []
    
    tmax_by_date = {}
    tmin_by_date = {}
    precip_by_date = {}
    et_by_date = {}
    
    try:
        # ---- TEMPERATURA ----
        era5_tmax = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('temperature_2m_max')
            .map(lambda img: img.subtract(273.15).rename('Tmax_C')
                 .copyProperties(img, ['system:time_start'])))
        
        era5_tmin = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('temperature_2m_min')
            .map(lambda img: img.subtract(273.15).rename('Tmin_C')
                 .copyProperties(img, ['system:time_start'])))
        
        tmax_values = era5_tmax.map(lambda img: ee.Feature(None, {
            'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            'tmax': img.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
            ).get('Tmax_C')
        }))
        
        tmin_values = era5_tmin.map(lambda img: ee.Feature(None, {
            'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            'tmin': img.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
            ).get('Tmin_C')
        }))
        
        tmax_list = tmax_values.toList(100).getInfo()
        tmin_list = tmin_values.toList(100).getInfo()
        
        tmax_vals = []
        tmin_vals = []
        heat_days = 0
        frost_days = 0
        gdd_total = 0
        
        for f in tmax_list:
            props = f.get('properties', {})
            val = props.get('tmax')
            date = props.get('date', '')
            if val is not None:
                tmax_vals.append(val)
                tmax_by_date[date] = val
                if val >= 35:
                    heat_days += 1
        
        for f in tmin_list:
            props = f.get('properties', {})
            val = props.get('tmin')
            date = props.get('date', '')
            if val is not None:
                tmin_vals.append(val)
                tmin_by_date[date] = val
                if val <= 0:
                    frost_days += 1
        
        for date in tmax_by_date:
            tmax_d = tmax_by_date.get(date)
            tmin_d = tmin_by_date.get(date)
            if tmax_d is not None and tmin_d is not None:
                tmean = (tmax_d + tmin_d) / 2
                gdd_total += max(0, tmean - 10)
        
        weather_kpis['weather_tmax_mean'] = round(sum(tmax_vals) / len(tmax_vals), 1) if tmax_vals else None
        weather_kpis['weather_tmax_max'] = round(max(tmax_vals), 1) if tmax_vals else None
        weather_kpis['weather_tmin_mean'] = round(sum(tmin_vals) / len(tmin_vals), 1) if tmin_vals else None
        weather_kpis['weather_tmin_min'] = round(min(tmin_vals), 1) if tmin_vals else None
        weather_kpis['weather_heat_days'] = heat_days
        weather_kpis['weather_frost_days'] = frost_days
        weather_kpis['weather_gdd_base10'] = round(gdd_total, 1)
        
    except Exception as e:
        print(f"Warning: ERA5 temperature failed: {e}")
        weather_kpis['weather_tmax_mean'] = None
        weather_kpis['weather_tmin_mean'] = None
        weather_kpis['weather_heat_days'] = None
        weather_kpis['weather_frost_days'] = None
        weather_kpis['weather_gdd_base10'] = None
    
    try:
        # ---- PRECIPITACIÓN ----
        era5_precip = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('total_precipitation_sum')
            .map(lambda img: img.multiply(1000).rename('Precip_mm')
                 .copyProperties(img, ['system:time_start'])))
        
        precip_values = era5_precip.map(lambda img: ee.Feature(None, {
            'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            'precip': img.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
            ).get('Precip_mm')
        }))
        
        precip_list = precip_values.toList(100).getInfo()
        precip_vals = []
        rain_days = 0
        
        for f in precip_list:
            props = f.get('properties', {})
            val = props.get('precip')
            date = props.get('date', '')
            if val is not None:
                precip_vals.append(val)
                precip_by_date[date] = val
                if val > 1:
                    rain_days += 1
        
        weather_kpis['weather_precip_total_mm'] = round(sum(precip_vals), 1) if precip_vals else None
        weather_kpis['weather_precip_max_daily_mm'] = round(max(precip_vals), 1) if precip_vals else None
        weather_kpis['weather_rain_days'] = rain_days
        
    except Exception as e:
        print(f"Warning: ERA5 precipitation failed: {e}")
        weather_kpis['weather_precip_total_mm'] = None
        weather_kpis['weather_rain_days'] = None
    
    try:
        # ---- EVAPOTRANSPIRACIÓN ----
        era5_et = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('total_evaporation_sum')
            .map(lambda img: img.multiply(-1000).rename('ET_mm')
                 .copyProperties(img, ['system:time_start'])))
        
        et_values = era5_et.map(lambda img: ee.Feature(None, {
            'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            'et': img.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
            ).get('ET_mm')
        }))
        
        et_list = et_values.toList(100).getInfo()
        et_vals = []
        for f in et_list:
            props = f.get('properties', {})
            val = props.get('et')
            date = props.get('date', '')
            if val is not None:
                et_vals.append(val)
                et_by_date[date] = val
        
        et_total = sum(et_vals) if et_vals else 0
        precip_total = weather_kpis.get('weather_precip_total_mm') or 0
        
        weather_kpis['weather_et_total_mm'] = round(et_total, 1) if et_vals else None
        weather_kpis['weather_water_balance_mm'] = round(precip_total - et_total, 1)
        
    except Exception as e:
        print(f"Warning: ERA5 ET failed: {e}")
        weather_kpis['weather_et_total_mm'] = None
        weather_kpis['weather_water_balance_mm'] = None
    
    try:
        # ---- VIENTO ----
        era5_wind_u = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('u_component_of_wind_10m'))
        
        era5_wind_v = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('v_component_of_wind_10m'))
        
        wind_speed_mean = era5_wind_u.mean().pow(2).add(era5_wind_v.mean().pow(2)).sqrt()
        wind_stats = wind_speed_mean.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
        ).getInfo()
        
        wind_val = list(wind_stats.values())[0] if wind_stats else None
        weather_kpis['weather_wind_mean_ms'] = round(wind_val, 1) if wind_val else None
        
    except Exception as e:
        print(f"Warning: ERA5 wind failed: {e}")
        weather_kpis['weather_wind_mean_ms'] = None
    
    try:
        # ---- HUMEDAD DEL SUELO ----
        era5_sm = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi)
            .select('volumetric_soil_water_layer_1'))
        
        sm_stats = era5_sm.reduce(
            ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True)
        ).reduceRegion(
            reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
        ).getInfo()
        
        weather_kpis['weather_soil_moisture_mean'] = round(
            sm_stats.get('volumetric_soil_water_layer_1_mean', 0) or 0, 3)
        weather_kpis['weather_soil_moisture_min'] = round(
            sm_stats.get('volumetric_soil_water_layer_1_min', 0) or 0, 3)
        
    except Exception as e:
        print(f"Warning: ERA5 soil moisture failed: {e}")
        weather_kpis['weather_soil_moisture_mean'] = None
    
    # ---- SERIE TEMPORAL DIARIA ----
    all_dates = sorted(set(
        list(tmax_by_date.keys()) + list(tmin_by_date.keys()) + 
        list(precip_by_date.keys()) + list(et_by_date.keys())
    ))
    
    for date in all_dates:
        daily_series.append({
            'date': date,
            'tmax_c': round(tmax_by_date.get(date, -9999), 1),
            'tmin_c': round(tmin_by_date.get(date, -9999), 1),
            'precip_mm': round(precip_by_date.get(date, 0), 1),
            'et_mm': round(et_by_date.get(date, 0), 1),
        })
    
    return weather_kpis, daily_series

def persist_images_to_db(job_id, images_base64, bounds=None):
    """
    Persiste las imágenes generadas por GEE en PostgreSQL vía HTTP API.
    Se llama al final de cada análisis (baseline/biweekly).
    
    Las imágenes se guardan en la tabla gee_images y el PDF generator
    las carga directamente de BD por job_id, sin depender de n8n.
    
    Args:
        job_id: Identificador del análisis
        images_base64: Dict {NDVI: "base64...", NDWI: "base64...", ...}
        bounds: Dict {north, south, east, west} o None
    
    Returns:
        list: Nombres de las imágenes guardadas exitosamente
    """
    if not images_base64:
        print("⚠️ No images to persist")
        return []
    
    stored = []
    api_base = os.environ.get(
        'API_BASE_URL', 
        'https://muorbita-api-production.up.railway.app'
    )
    
    try:
        store_payload = json.dumps({
            'job_id': job_id,
            'images': images_base64,
            'bounds': bounds
        }).encode('utf-8')
        
        req = urllib.request.Request(
            f'{api_base}/api/images/store',
            data=store_payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        response = urllib.request.urlopen(req, timeout=60)
        result = json.loads(response.read().decode('utf-8'))
        
        if result.get('success'):
            stored = [d['index_type'] for d in result.get('details', [])]
            total_kb = sum(d.get('size_kb', 0) for d in result.get('details', []))
            print(f"✅ Persisted {len(stored)} images in DB ({total_kb} KB total): {stored}")
        else:
            print(f"⚠️ Store API returned success=false: {result}")
            
    except Exception as e:
        print(f"⚠️ Could not persist images to DB: {e}")
        print("   Images will be passed inline as fallback (legacy behavior)")
    
    return stored

# ============================================================================
# EJECUTAR ANÁLISIS BIWEEKLY
# ============================================================================

def execute_biweekly_analysis(args):
    """
    Análisis BIWEEKLY ligero — PNGs planos 2D (v5.2).
    """
    roi = create_roi(args.roi, args.buffer)
    job_id = args.job_id
    bounds = get_bounds(roi)
    
    # ========== DATOS SATELITALES ==========
    collection = get_sentinel2_collection(roi, args.start_date, args.end_date)
    count = collection.size().getInfo()
    
    if count == 0:
        return {
            "error": "No images found for the biweekly period",
            "job_id": job_id,
            "analysis_type": "biweekly",
            "start_date": args.start_date,
            "end_date": args.end_date,
            "suggestion": "Try extending the date range or check cloud cover"
        }
    
    indexed_collection = collection.map(calculate_indices)
    composite = indexed_collection.median().clip(roi)
    
    # ── Imagen Sentinel-2 más reciente (para RGB de referencia) ─────
    latest_sentinel = indexed_collection.sort('system:time_start', False).first().clip(roi)
    
    latest = collection.sort('system:time_start', False).first()
    try:
        latest_date = ee.Date(latest.get('system:time_start')).format('YYYY-MM-dd').getInfo()
    except:
        latest_date = args.end_date
    
    # ========== ESTADÍSTICAS ==========
    stats = composite.select(['NDVI', 'NDWI', 'EVI', 'NDCI']).reduceRegion(
        reducer=ee.Reducer.mean()
            .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=roi, scale=10, maxPixels=1e9
    ).getInfo()
    
    area_ha = roi.area().divide(10000).getInfo()
    
    stress_mask = composite.select('NDVI').lt(0.35)
    stress_area = stress_mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=roi, scale=10, maxPixels=1e9
    ).getInfo()
    stress_ha = stress_area.get('NDVI', 0) / 10000
    stress_pct = (stress_ha / area_ha * 100) if area_ha > 0 else 0
    
    hist_stats = indexed_collection.select('NDVI').mean().reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=roi, scale=20, maxPixels=1e9
    ).getInfo()
    
    ndvi_mean = stats.get('NDVI_mean', 0) or 0
    hist_mean = hist_stats.get('NDVI_mean', ndvi_mean) or ndvi_mean
    hist_std = hist_stats.get('NDVI_stdDev', 0.1) or 0.1
    z_score = (ndvi_mean - hist_mean) / hist_std if hist_std > 0 else 0
    
    # ========== ERA5 WEATHER ==========
    weather_kpis, weather_daily = get_era5_weather(roi, args.start_date, args.end_date)
    
    # ========== MODIS LST ==========
    try:
        lst = get_modis_lst(roi, args.start_date, args.end_date)
        lst_stats = lst.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=roi, scale=1000, maxPixels=1e9
        ).getInfo()
        lst_mean = lst_stats.get('LST_C_mean', None)
    except:
        lst = None
        lst_mean = None
    
    # ========== SERIE TEMPORAL ==========
    time_series = []
    try:
        ts_features = indexed_collection.select(['NDVI', 'NDWI', 'EVI']).map(lambda img: 
            ee.Feature(None, img.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=roi, scale=20, maxPixels=1e9
            )).set('date', ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'))
        )
        ts_list = ts_features.toList(100).getInfo()
        for feature in ts_list:
            props = feature.get('properties', {})
            if props.get('date'):
                time_series.append({
                    'date': props.get('date', ''),
                    'ndvi': round(props.get('NDVI_mean', 0) or 0, 3),
                    'ndwi': round(props.get('NDWI_mean', 0) or 0, 3),
                    'evi': round(props.get('EVI_mean', 0) or 0, 3)
                })
        time_series.sort(key=lambda x: x['date'])
    except Exception as e:
        print(f"Warning: Could not get time series: {e}")
    
    # ========== GENERAR PNGs PLANOS 2D (v5.2) ==========
    print("Generating FLAT 2D PNG maps (bird's eye view)...")
    
    images_base64 = {}
    
    for idx_name in ['NDVI', 'NDWI']:
        print(f"  Generating flat 2D {idx_name}...")
        viz = VIZ_PALETTES[idx_name]
        b64 = get_flat_index_png(
            index_image=composite.select(idx_name),
            roi=roi,
            viz_params=viz,
            dimensions=1024
        )
        if b64:
            b64 = add_professional_legend(b64, idx_name, stats.get(f'{idx_name}_mean'))
            images_base64[idx_name] = b64
            print(f"  ✓ {idx_name}: flat 2D + legend OK")
        else:
            print(f"  ✗ {idx_name}: generation failed")
    
    # Imagen RGB de referencia (plana)
    print("  Generating flat 2D RGB reference...")
    rgb_b64 = get_flat_rgb_png(latest_sentinel, roi, dimensions=1024)
    if rgb_b64:
        images_base64['RGB'] = rgb_b64
        print("  ✓ RGB: flat 2D OK")
    
    print(f"\n  Total flat 2D images: {len(images_base64)}")
    
    # ========== KPIs ==========
    kpis = {
        'job_id': job_id,
        'crop_type': args.crop,
        'analysis_type': 'biweekly',
        'start_date': args.start_date,
        'end_date': args.end_date,
        'latest_image_date': latest_date,
        'images_processed': count,
        'area_hectares': round(area_ha, 2),
        'ndvi_mean': round(stats.get('NDVI_mean', 0) or 0, 3),
        'ndvi_p10': round(stats.get('NDVI_p10', 0) or 0, 3),
        'ndvi_p50': round(stats.get('NDVI_p50', 0) or 0, 3),
        'ndvi_p90': round(stats.get('NDVI_p90', 0) or 0, 3),
        'ndvi_stddev': round(stats.get('NDVI_stdDev', 0) or 0, 3),
        'ndvi_zscore': round(z_score, 2),
        'ndwi_mean': round(stats.get('NDWI_mean', 0) or 0, 3),
        'ndwi_p10': round(stats.get('NDWI_p10', 0) or 0, 3),
        'ndwi_p90': round(stats.get('NDWI_p90', 0) or 0, 3),
        'evi_mean': round(stats.get('EVI_mean', 0) or 0, 3),
        'ndci_mean': round(stats.get('NDCI_mean', 0) or 0, 3),
        'stress_area_ha': round(stress_ha, 2),
        'stress_area_pct': round(stress_pct, 1),
        'lst_mean_c': round(lst_mean, 1) if lst_mean else None,
        'bounds_south': bounds['south'] if bounds else None,
        'bounds_west': bounds['west'] if bounds else None,
        'bounds_north': bounds['north'] if bounds else None,
        'bounds_east': bounds['east'] if bounds else None,
    }
    kpis.update(weather_kpis)
    
    # ========== PERSISTIR IMÁGENES EN BD ==========
    stored = persist_images_to_db(job_id, images_base64, bounds)
    
    # ========== RESULTADO ==========
    result = {
        'success': True,
        'job_id': job_id,
        'analysis_type': 'biweekly',
        'kpis': kpis,
        'weather': weather_kpis,
        'weather_daily': weather_daily,
        'bounds': bounds,
        'time_series': time_series,
        
        'images_stored': stored,
        'images_available': list(images_base64.keys()),
        
        # SOLO incluir base64 si NO se pudieron guardar en BD (fallback)
        'images_base64': {} if stored else images_base64,
        
        'tasks': [],
        'task_count': 0,
        'message': (
            f'Biweekly analysis complete. '
            f'{len(stored)} flat 2D images persisted in DB.'
            if stored else
            f'Biweekly analysis complete. '
            f'{len(images_base64)} flat 2D images in response (DB store failed).'
        )
    }
    
    return result


# ============================================================================
# EJECUTAR ANÁLISIS BASELINE
# ============================================================================

def execute_analysis(args):
    """
    Análisis BASELINE completo — PNGs planos 2D (v5.2).
    """
    roi = create_roi(args.roi, args.buffer)
    job_id = args.job_id
    bounds = get_bounds(roi)
    
    # ========== DATOS SATELITALES ==========
    collection = get_sentinel2_collection(roi, args.start_date, args.end_date)
    count = collection.size().getInfo()
    
    if count == 0:
        return {
            "error": "No images found for the specified date range and ROI",
            "job_id": job_id,
            "start_date": args.start_date,
            "end_date": args.end_date
        }
    
    indexed_collection = collection.map(calculate_indices)
    composite = indexed_collection.median().clip(roi)
    
    # ── Imagen Sentinel-2 más reciente (para RGB de referencia) ──
    latest_sentinel = indexed_collection.sort('system:time_start', False).first().clip(roi)
    
    latest = collection.sort('system:time_start', False).first()
    try:
        latest_date = ee.Date(latest.get('system:time_start')).format('YYYY-MM-dd').getInfo()
    except:
        latest_date = args.end_date
    
    # ========== ESTADÍSTICAS ==========
    stats = composite.select(['NDVI', 'NDWI', 'EVI', 'NDCI', 'SAVI', 'OSAVI']).reduceRegion(
        reducer=ee.Reducer.mean()
            .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True)
            .combine(ee.Reducer.count(), sharedInputs=True),
        geometry=roi, scale=10, maxPixels=1e9
    ).getInfo()
    
    area_ha = roi.area().divide(10000).getInfo()
    
    stress_mask = composite.select('NDVI').lt(0.35)
    stress_area = stress_mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=roi, scale=10, maxPixels=1e9
    ).getInfo()
    stress_ha = stress_area.get('NDVI', 0) / 10000
    stress_pct = (stress_ha / area_ha * 100) if area_ha > 0 else 0
    
    hist_stats = indexed_collection.select('NDVI').mean().reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=roi, scale=20, maxPixels=1e9
    ).getInfo()
    
    ndvi_mean = stats.get('NDVI_mean', 0) or 0
    hist_mean = hist_stats.get('NDVI_mean', ndvi_mean) or ndvi_mean
    hist_std = hist_stats.get('NDVI_stdDev', 0.1) or 0.1
    z_score = (ndvi_mean - hist_mean) / hist_std if hist_std > 0 else 0
    
    # ========== MODIS LST ==========
    try:
        lst = get_modis_lst(roi, args.start_date, args.end_date)
        lst_stats = lst.reduceRegion(
            reducer=ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True),
            geometry=roi, scale=1000, maxPixels=1e9
        ).getInfo()
        lst_mean = lst_stats.get('LST_C_mean', None)
        lst_min = lst_stats.get('LST_C_min', None)
        lst_max = lst_stats.get('LST_C_max', None)
    except:
        lst = None
        lst_mean = lst_min = lst_max = None
    
    # ========== VRA ==========
    vra_image, vra_stats = calculate_vra_zones(composite, roi)
    
    # ========== KPIs ==========
    kpis = {
        'job_id': job_id,
        'crop_type': args.crop,
        'analysis_type': args.analysis_type,
        'start_date': args.start_date,
        'end_date': args.end_date,
        'latest_image_date': latest_date,
        'images_processed': count,
        'area_hectares': round(area_ha, 2),
        'ndvi_mean': round(stats.get('NDVI_mean', 0) or 0, 3),
        'ndvi_p10': round(stats.get('NDVI_p10', 0) or 0, 3),
        'ndvi_p50': round(stats.get('NDVI_p50', 0) or 0, 3),
        'ndvi_p90': round(stats.get('NDVI_p90', 0) or 0, 3),
        'ndvi_stddev': round(stats.get('NDVI_stdDev', 0) or 0, 3),
        'ndvi_zscore': round(z_score, 2),
        'ndwi_mean': round(stats.get('NDWI_mean', 0) or 0, 3),
        'ndwi_p10': round(stats.get('NDWI_p10', 0) or 0, 3),
        'ndwi_p90': round(stats.get('NDWI_p90', 0) or 0, 3),
        'evi_mean': round(stats.get('EVI_mean', 0) or 0, 3),
        'evi_p10': round(stats.get('EVI_p10', 0) or 0, 3),
        'evi_p90': round(stats.get('EVI_p90', 0) or 0, 3),
        'ndci_mean': round(stats.get('NDCI_mean', 0) or 0, 3),
        'savi_mean': round(stats.get('SAVI_mean', 0) or 0, 3),
        'osavi_mean': round(stats.get('OSAVI_mean', 0) or 0, 3),
        'stress_area_ha': round(stress_ha, 2),
        'stress_area_pct': round(stress_pct, 1),
        'lst_mean_c': round(lst_mean, 1) if lst_mean else None,
        'lst_min_c': round(lst_min, 1) if lst_min else None,
        'lst_max_c': round(lst_max, 1) if lst_max else None,
        'bounds_south': bounds['south'] if bounds else None,
        'bounds_west': bounds['west'] if bounds else None,
        'bounds_north': bounds['north'] if bounds else None,
        'bounds_east': bounds['east'] if bounds else None,
        'valid_pixels': stats.get('NDVI_count', 0)
    }
    
    # ========== GENERAR PNGs PLANOS 2D (v5.2) ==========
    print("Generating FLAT 2D PNG maps (bird's eye view)...")
    
    images_base64 = {}
    
    # ── Índices vegetativos (mapas planos 2D) ───────────────────
    for idx_name in ['NDVI', 'NDWI', 'EVI', 'NDCI', 'SAVI']:
        print(f"  Generating flat 2D {idx_name}...")
        viz = VIZ_PALETTES[idx_name]
        
        b64 = get_flat_index_png(
            index_image=composite.select(idx_name),
            roi=roi,
            viz_params=viz,
            dimensions=1024
        )
        
        if b64:
            mean_key = f'{idx_name.lower()}_mean'
            b64 = add_professional_legend(b64, idx_name, kpis.get(mean_key))
            images_base64[idx_name] = b64
            print(f"  ✓ {idx_name}: flat 2D + legend OK")
        else:
            print(f"  ✗ {idx_name}: generation failed")
    
    # ── VRA (mapa plano 2D) ─────────────────────────────────────
    if vra_image is not None:
        print("  Generating flat 2D VRA...")
        viz = VIZ_PALETTES['VRA']
        b64 = get_flat_index_png(
            index_image=vra_image,
            roi=roi,
            viz_params=viz,
            dimensions=1024
        )
        if b64:
            b64 = add_professional_legend(b64, 'VRA')
            images_base64['VRA'] = b64
            print("  ✓ VRA: flat 2D + legend OK")
    
    # ── LST (mapa plano 2D — resolución MODIS 1km) ─────────────
    if lst is not None:
        print("  Generating flat 2D LST...")
        viz = VIZ_PALETTES['LST']
        b64 = get_flat_index_png(
            index_image=lst,
            roi=roi,
            viz_params=viz,
            dimensions=512  # Menor resolución (MODIS = 1km)
        )
        if b64:
            b64 = add_professional_legend(b64, 'LST', kpis.get('lst_mean_c'))
            images_base64['LST'] = b64
            print("  ✓ LST: flat 2D + legend OK")
    
    # ── Imagen RGB satelital de referencia (plana) ──────────────
    print("  Generating flat 2D RGB reference...")
    rgb_b64 = get_flat_rgb_png(latest_sentinel, roi, dimensions=1024)
    if rgb_b64:
        images_base64['RGB'] = rgb_b64
        print("  ✓ RGB: flat 2D OK")
    
    print(f"\n  Total flat 2D images: {len(images_base64)}")
    
    # ========== SERIE TEMPORAL ==========
    time_series = []
    try:
        ts_features = indexed_collection.select(['NDVI', 'NDWI', 'EVI']).map(lambda img: 
            ee.Feature(None, img.reduceRegion(
                reducer=ee.Reducer.mean()
                    .combine(ee.Reducer.percentile([10, 90]), sharedInputs=True),
                geometry=roi, scale=20, maxPixels=1e9
            )).set('date', ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'))
        )
        ts_list = ts_features.toList(500).getInfo()
        for feature in ts_list:
            props = feature.get('properties', {})
            if props.get('date'):
                time_series.append({
                    'date': props.get('date', ''),
                    'ndvi': round(props.get('NDVI_mean', 0) or 0, 3),
                    'ndwi': round(props.get('NDWI_mean', 0) or 0, 3),
                    'evi': round(props.get('EVI_mean', 0) or 0, 3)
                })
        time_series.sort(key=lambda x: x['date'])
    except Exception as e:
        print(f"Warning: Could not get time series: {e}")
    
    # ========== PERSISTIR IMÁGENES EN BD ==========
    stored = persist_images_to_db(job_id, images_base64, bounds)
    
    # ========== RESULTADO ==========
    result = {
        'success': True,
        'job_id': job_id,
        'analysis_type': 'baseline',
        'kpis': kpis,
        'vra_stats': vra_stats,
        'bounds': bounds,
        'time_series': time_series,
        
        'images_stored': stored,
        'images_available': list(images_base64.keys()),
        
        # SOLO incluir base64 si NO se pudieron guardar en BD (fallback)
        'images_base64': {} if stored else images_base64,
        
        'tasks': [],
        'task_count': 0,
        'message': (
            f'Baseline analysis complete. '
            f'{len(stored)} flat 2D images persisted in DB.'
        )
    }
    
    return result

# ============================================================================
# CHECK STATUS (legacy — ahora siempre "complete" porque no hay tasks)
# ============================================================================

def check_status(args):
    """Check status — con v5.x siempre está completo (no hay tasks asíncronos)"""
    return {
        'job_id': args.job_id,
        'tasks': [],
        'completed': 0,
        'running': 0,
        'failed': 0,
        'pending': 0,
        'total': 0,
        'all_complete': True,
        'png_complete': True,
        'any_failed': False,
        'progress_pct': 100,
        'message': 'v5.2: No async tasks. All data returned immediately in execute response.'
    }

# ============================================================================
# DOWNLOAD RESULTS (legacy — datos ya están en el JSON de execute)
# ============================================================================

def download_results(args):
    """Download results — con v5.x no aplica, datos ya en JSON"""
    return {
        'job_id': args.job_id,
        'analysis_type': getattr(args, 'analysis_type', 'baseline'),
        'status': 'ready',
        'download_ready': True,
        'message': 'v5.2: All data returned directly in execute response. No Drive downloads needed.'
    }

# ============================================================================
# START TASKS (legacy — no hay tasks)
# ============================================================================

def start_tasks(args):
    """Start tasks — con v5.x no aplica"""
    return {
        'job_id': args.job_id,
        'started': 0,
        'message': 'v5.2: No async tasks to start. All processing is synchronous.'
    }

# ============================================================================
# MAIN
# ============================================================================

def main():
    args = parse_args()
    
    try:
        if args.mode == 'execute':
            analysis_type = getattr(args, 'analysis_type', 'baseline')
            if analysis_type == 'biweekly':
                result = execute_biweekly_analysis(args)
            else:
                result = execute_analysis(args)
                
        elif args.mode == 'check-status':
            result = check_status(args)
            
        elif args.mode == 'download-results':
            result = download_results(args)
            
        elif args.mode == 'start-tasks':
            result = start_tasks(args)
            
        else:
            result = {'error': f'Unknown mode: {args.mode}'}
        
        print(json.dumps(result, indent=2))
        
    except Exception as e:
        import traceback
        print(json.dumps({
            'error': str(e),
            'traceback': traceback.format_exc()
        }))
        sys.exit(1)

if __name__ == '__main__':
    main()
