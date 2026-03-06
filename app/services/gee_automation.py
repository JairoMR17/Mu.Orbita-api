#!/usr/bin/env python3
"""
Mu.Orbita GEE Automation Script v5.3 (FLAT 2D + OPTIMIZED)
=============================================================

CAMBIOS V5.3:
✅ MAPAS PLANOS 2D: clip(roi) + roi.bounds() + fondo neutro — NO perspectiva 3D
✅ OPTIMIZACIÓN: ERA5 en 1 sola query (antes 6 separadas) → ahorra ~90s
✅ OPTIMIZACIÓN: Estadísticas en 1 getInfo() combinado
✅ OPTIMIZACIÓN: PNGs a 768px (suficiente para PDF A4 y web)
✅ OPTIMIZACIÓN: Series temporales limitadas a 50 imágenes max
✅ Leyenda profesional: fondo claro, marcador ▼, min/max con unidades
✅ Sin blending RGB satelital → heatmap puro del índice
✅ Contorno oscuro (#333) sobre fondo crema (#F5F5F0)

TIEMPO ESTIMADO:
    Antes (v5.1):  ~5 min (6 ERA5 queries + PNGs 1024px + getInfo() individual)
    Ahora (v5.3):  ~2-3 min (1 ERA5 batch + PNGs 768px + stats combinados)

MODOS:
    baseline:   Análisis completo (todos los índices + VRA + LST)
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
# PALETAS DE VISUALIZACIÓN
# ============================================================================

VIZ_PALETTES = {
    'NDVI': {
        'min': 0.0, 'max': 0.8,
        'palette': ['8B0000', 'FF0000', 'FF6347', 'FFA500', 'FFFF00',
                    'ADFF2F', '7CFC00', '32CD32', '228B22', '006400'],
        'label': 'NDVI (Vigor Vegetativo)', 'unit': ''
    },
    'NDWI': {
        'min': -0.3, 'max': 0.4,
        'palette': ['8B4513', 'D2691E', 'F4A460', 'FFF8DC', 'E0FFFF',
                    '87CEEB', '4682B4', '0000CD', '00008B'],
        'label': 'NDWI (Estado Hídrico)', 'unit': ''
    },
    'EVI': {
        'min': 0.0, 'max': 0.6,
        'palette': ['8B0000', 'CD5C5C', 'F08080', 'FFFFE0', 'ADFF2F',
                    '7FFF00', '32CD32', '228B22', '006400'],
        'label': 'EVI (Productividad)', 'unit': ''
    },
    'NDCI': {
        'min': -0.2, 'max': 0.6,
        'palette': ['8B0000', 'FF6347', 'FFA500', 'FFFF00', 'ADFF2F',
                    '7CFC00', '32CD32', '228B22', '006400'],
        'label': 'NDCI (Clorofila)', 'unit': ''
    },
    'SAVI': {
        'min': 0.0, 'max': 0.8,
        'palette': ['8B0000', 'FF0000', 'FF6347', 'FFA500', 'FFFF00',
                    'ADFF2F', '7CFC00', '32CD32', '228B22', '006400'],
        'label': 'SAVI (Vigor Ajustado Suelo)', 'unit': ''
    },
    'VRA': {
        'min': 0, 'max': 2,
        'palette': ['e74c3c', 'f1c40f', '27ae60'],
        'label': 'Zonas de Manejo Variable', 'unit': ''
    },
    'LST': {
        'min': 15, 'max': 45,
        'palette': ['0000FF', '00FFFF', '00FF00', 'FFFF00', 'FF0000'],
        'label': 'Temperatura Superficial', 'unit': '°C'
    }
}

# ============================================================================
# ARGUMENTOS
# ============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description='Mu.Orbita GEE v5.3')
    parser.add_argument('--mode', required=True,
                        choices=['execute', 'check-status', 'download-results', 'start-tasks'])
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--roi', help='GeoJSON string of ROI')
    parser.add_argument('--start-date', help='Start date YYYY-MM-DD')
    parser.add_argument('--end-date', help='End date YYYY-MM-DD')
    parser.add_argument('--crop', default='olivar', help='Crop type')
    parser.add_argument('--buffer', type=int, default=0, help='Buffer in meters')
    parser.add_argument('--analysis-type', default='baseline')
    parser.add_argument('--drive-folder', default='MuOrbita_Outputs')
    parser.add_argument('--output-dir', help='Local output directory')
    parser.add_argument('--export-png', type=bool, default=True)
    return parser.parse_args()

# ============================================================================
# UTILIDADES
# ============================================================================

def create_roi(geojson_str, buffer_meters=0):
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


def get_bounds(roi):
    try:
        bounds = roi.bounds().coordinates().getInfo()[0]
        lngs = [p[0] for p in bounds]
        lats = [p[1] for p in bounds]
        return {'south': min(lats), 'west': min(lngs),
                'north': max(lats), 'east': max(lngs)}
    except Exception as e:
        print(f"Warning: Could not get bounds: {e}")
        return None


# ============================================================================
# PNG PLANO 2D — FUNCIÓN PRINCIPAL (v5.3)
# ============================================================================

def get_flat_index_png(index_image, roi, viz_params, dimensions=768,
                       bg_color='F5F5F0', boundary_color='333333',
                       boundary_width=2):
    """
    Genera un PNG PLANO 2D del índice — vista cenital pura.

    Cómo funciona:
    1. clip(roi)     → solo píxeles dentro de la parcela tienen datos
    2. bg_image      → imagen de fondo sólido (crema)
    3. blend()       → el índice coloreado se pinta SOBRE el fondo
                       (fuera de parcela no hay datos → se ve el fondo)
    4. roi.bounds()  → bounding box RECTANGULAR alineado a ejes lat/lng
                       → getThumbURL genera vista cenital plana, NO 3D
    """
    try:
        # 1. Clipar estrictamente a la parcela
        clipped = index_image.clip(roi)

        # 2. Fondo sólido
        bg_r, bg_g, bg_b = int(bg_color[0:2], 16), int(bg_color[2:4], 16), int(bg_color[4:6], 16)
        bg_image = ee.Image([
            ee.Image.constant(bg_r).toUint8().rename('vis-red'),
            ee.Image.constant(bg_g).toUint8().rename('vis-green'),
            ee.Image.constant(bg_b).toUint8().rename('vis-blue')
        ])

        # 3. Colorear índice con paleta
        index_colored = clipped.visualize(
            **{k: v for k, v in viz_params.items() if k in ('min', 'max', 'palette')}
        )

        # 4. Componer: fondo + índice (solo donde hay datos = dentro de parcela)
        composed = bg_image.blend(index_colored)

        # 5. Contorno oscuro de la parcela
        roi_fc = ee.FeatureCollection([ee.Feature(roi)])
        outline = ee.Image().byte().paint(featureCollection=roi_fc, color=1, width=boundary_width)
        outline_vis = outline.visualize(palette=[boundary_color], min=0, max=1)
        final = composed.blend(outline_vis)

        # 6. Bounding box RECTANGULAR → vista cenital plana
        region_coords = roi.bounds().getInfo()['coordinates']

        # 7. Descargar thumbnail
        url = final.getThumbURL({
            'region': region_coords,
            'dimensions': dimensions,
            'format': 'png'
        })
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'MuOrbita/5.3')
        png_bytes = urllib.request.urlopen(req, timeout=60).read()

        if len(png_bytes) < 100:
            return None
        return base64.b64encode(png_bytes).decode('utf-8')

    except Exception as e:
        print(f"Warning: get_flat_index_png failed: {e}")
        return None


def get_flat_rgb_png(sentinel_rgb_image, roi, dimensions=768,
                     bg_color='F5F5F0', boundary_color='333333', boundary_width=2):
    """PNG plano 2D de imagen satelital true-color."""
    try:
        rgb = sentinel_rgb_image.select(['B4', 'B3', 'B2']).clip(roi).visualize(
            min=0, max=0.3, gamma=1.3)

        bg_r, bg_g, bg_b = int(bg_color[0:2], 16), int(bg_color[2:4], 16), int(bg_color[4:6], 16)
        bg_image = ee.Image([
            ee.Image.constant(bg_r).toUint8().rename('vis-red'),
            ee.Image.constant(bg_g).toUint8().rename('vis-green'),
            ee.Image.constant(bg_b).toUint8().rename('vis-blue')
        ])

        composed = bg_image.blend(rgb)
        roi_fc = ee.FeatureCollection([ee.Feature(roi)])
        outline = ee.Image().byte().paint(roi_fc, 1, boundary_width)
        outline_vis = outline.visualize(palette=[boundary_color], min=0, max=1)
        final = composed.blend(outline_vis)

        region_coords = roi.bounds().getInfo()['coordinates']
        url = final.getThumbURL({'region': region_coords, 'dimensions': dimensions, 'format': 'png'})
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'MuOrbita/5.3')
        png_bytes = urllib.request.urlopen(req, timeout=60).read()
        if len(png_bytes) < 100:
            return None
        return base64.b64encode(png_bytes).decode('utf-8')

    except Exception as e:
        print(f"Warning: get_flat_rgb_png failed: {e}")
        return None


# ============================================================================
# LEYENDA PROFESIONAL
# ============================================================================

def add_legend(png_base64, index_name, mean_value=None):
    """Añade leyenda con colorbar, título y marcador de media."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return png_base64

    viz = VIZ_PALETTES.get(index_name)
    if not viz:
        return png_base64

    img = Image.open(io.BytesIO(base64.b64decode(png_base64))).convert('RGBA')

    legend_h, pad, bar_h = 90, 20, 18
    bar_w = min(350, img.width - 2 * pad)

    bg = (249, 247, 242, 255)
    new_img = Image.new('RGBA', (img.width, img.height + legend_h), bg)
    new_img.paste(img, (0, 0))
    draw = ImageDraw.Draw(new_img)
    draw.line([(0, img.height), (img.width, img.height)], fill=(200, 195, 185), width=1)

    try:
        ft = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
        fs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        fv = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    except (OSError, IOError):
        ft = fs = fv = ImageFont.load_default()

    y0 = img.height + 8
    accent = (139, 69, 19)
    dark = (51, 51, 51)
    muted = (136, 136, 136)

    # Título
    label = viz.get('label', index_name)
    draw.text((pad, y0), label, fill=accent, font=ft)
    if mean_value is not None:
        try:
            tw = draw.textbbox((0, 0), label, font=ft)[2]
        except AttributeError:
            tw = len(label) * 8
        draw.text((pad + tw + 20, y0 + 1), f"Media: {mean_value:.2f}", fill=dark, font=fv)

    # Colorbar
    bar_y, bar_x = y0 + 24, pad
    colors = [tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) for h in viz['palette']]
    n = len(colors)
    for x in range(bar_w):
        t = x / bar_w
        idx = t * (n - 1)
        i = min(int(idx), n - 2)
        f = idx - i
        c = tuple(int(colors[i][j] * (1 - f) + colors[i+1][j] * f) for j in range(3))
        draw.rectangle([bar_x + x, bar_y, bar_x + x + 1, bar_y + bar_h], fill=c)
    draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], outline=(100, 100, 100), width=1)

    # Min/max labels
    unit = viz.get('unit', '')
    draw.text((bar_x, bar_y + bar_h + 3), f"{viz['min']}{unit}", fill=muted, font=fs)
    mx_txt = f"{viz['max']}{unit}"
    try:
        mx_w = draw.textbbox((0, 0), mx_txt, font=fs)[2]
    except AttributeError:
        mx_w = len(mx_txt) * 6
    draw.text((bar_x + bar_w - mx_w, bar_y + bar_h + 3), mx_txt, fill=muted, font=fs)

    # Marcador ▼
    if mean_value is not None:
        rng = viz['max'] - viz['min']
        if rng > 0:
            t = max(0, min(1, (mean_value - viz['min']) / rng))
            mx = bar_x + int(t * bar_w)
            draw.polygon([(mx, bar_y - 2), (mx - 6, bar_y - 8), (mx + 6, bar_y - 8)], fill=dark)

    final = Image.new('RGB', new_img.size, (249, 247, 242))
    final.paste(new_img, mask=new_img.split()[3])
    buf = io.BytesIO()
    final.save(buf, format='PNG', optimize=True)
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode('utf-8')


# ============================================================================
# COLECCIONES DE DATOS
# ============================================================================

def get_sentinel2_collection(roi, start_date, end_date):
    def mask_clouds(image):
        qa = image.select('QA60')
        scl = image.select('SCL')
        cloud_mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
        scl_mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
        return (image.updateMask(cloud_mask.And(scl_mask))
                .divide(10000)
                .copyProperties(image, ['system:time_start']))

    return (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(roi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
        .map(mask_clouds))


def calculate_indices(image):
    nir = image.select('B8')
    red = image.select('B4')
    blue = image.select('B2')

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
    try:
        training_image = composite.select(['NDVI', 'EVI', 'NDWI'])
        valid_mask = training_image.mask().reduce(ee.Reducer.min())
        training_masked = training_image.updateMask(valid_mask)

        sample = training_masked.sample(region=roi, scale=20, numPixels=5000, geometries=False)
        clusterer = ee.Clusterer.wekaKMeans(3).train(sample)
        vra = training_masked.cluster(clusterer).rename('zone')

        vra_stats = []
        for zone_num in range(3):
            zone_mask = vra.eq(zone_num)
            zone_area = zone_mask.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(), geometry=roi, scale=20, maxPixels=1e9
            ).getInfo()
            zone_indices = composite.select(['NDVI', 'NDWI', 'EVI']).updateMask(zone_mask).reduceRegion(
                reducer=ee.Reducer.mean(), geometry=roi, scale=20, maxPixels=1e9
            ).getInfo()
            vra_stats.append({
                'zone': zone_num,
                'area_ha': round(zone_area.get('zone', 0) / 10000, 2),
                'ndvi_mean': round(zone_indices.get('NDVI', 0) or 0, 3),
                'ndwi_mean': round(zone_indices.get('NDWI', 0) or 0, 3),
                'evi_mean': round(zone_indices.get('EVI', 0) or 0, 3)
            })

        vra_stats.sort(key=lambda x: x['ndvi_mean'])
        for i, s in enumerate(vra_stats):
            s['label'] = ['Bajo vigor', 'Vigor medio', 'Alto vigor'][i]
            s['recommendation'] = ['Dosis alta', 'Dosis media', 'Dosis baja'][i]

        return vra, vra_stats
    except Exception as e:
        print(f"Warning: VRA failed: {e}")
        return None, []


# ============================================================================
# ERA5 WEATHER — OPTIMIZADO (1 query combinada en vez de 6 separadas)
# ============================================================================

def get_era5_weather(roi, start_date, end_date):
    """
    v5.3 OPTIMIZADO: Una sola ImageCollection filtrada, múltiples select().
    Antes: 6 ImageCollections separadas × toList().getInfo() = ~90s
    Ahora: 1 ImageCollection + 2-3 getInfo() = ~20-30s
    """
    weather_kpis = {}
    daily_series = []

    try:
        # ── UNA SOLA QUERY base ERA5 ───────────────────────────────
        era5_base = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date)
            .filterBounds(roi))

        # ── Temperatura: servidor calcula todo, solo 1 getInfo() ───
        era5_temp = era5_base.select(
            ['temperature_2m_max', 'temperature_2m_min']
        ).map(lambda img:
            img.subtract(273.15)
            .copyProperties(img, ['system:time_start'])
        )

        temp_features = era5_temp.map(lambda img: ee.Feature(None, {
            'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            'tmax': img.select('temperature_2m_max').reduceRegion(
                ee.Reducer.mean(), roi, 11132, maxPixels=1e9).get('temperature_2m_max'),
            'tmin': img.select('temperature_2m_min').reduceRegion(
                ee.Reducer.mean(), roi, 11132, maxPixels=1e9).get('temperature_2m_min'),
        }))

        # ── Precipitación + ET combinados ──────────────────────────
        era5_water = era5_base.select(
            ['total_precipitation_sum', 'total_evaporation_sum']
        ).map(lambda img: ee.Image([
            img.select('total_precipitation_sum').multiply(1000).rename('precip_mm'),
            img.select('total_evaporation_sum').multiply(-1000).rename('et_mm')
        ]).copyProperties(img, ['system:time_start']))

        water_features = era5_water.map(lambda img: ee.Feature(None, {
            'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            'precip': img.select('precip_mm').reduceRegion(
                ee.Reducer.mean(), roi, 11132, maxPixels=1e9).get('precip_mm'),
            'et': img.select('et_mm').reduceRegion(
                ee.Reducer.mean(), roi, 11132, maxPixels=1e9).get('et_mm'),
        }))

        # ── 2 getInfo() en vez de 6 ───────────────────────────────
        print("  Fetching ERA5 temperature...")
        temp_list = temp_features.toList(50).getInfo()
        print("  Fetching ERA5 precipitation + ET...")
        water_list = water_features.toList(50).getInfo()

        # Procesar temperatura
        tmax_by_date = {}
        tmin_by_date = {}
        tmax_vals, tmin_vals = [], []
        heat_days, frost_days, gdd_total = 0, 0, 0

        for f in temp_list:
            p = f.get('properties', {})
            d, tx, tn = p.get('date', ''), p.get('tmax'), p.get('tmin')
            if tx is not None:
                tmax_vals.append(tx)
                tmax_by_date[d] = tx
                if tx >= 35: heat_days += 1
            if tn is not None:
                tmin_vals.append(tn)
                tmin_by_date[d] = tn
                if tn <= 0: frost_days += 1

        for d in tmax_by_date:
            tx, tn = tmax_by_date.get(d), tmin_by_date.get(d)
            if tx is not None and tn is not None:
                gdd_total += max(0, (tx + tn) / 2 - 10)

        weather_kpis['weather_tmax_mean'] = round(sum(tmax_vals) / len(tmax_vals), 1) if tmax_vals else None
        weather_kpis['weather_tmax_max'] = round(max(tmax_vals), 1) if tmax_vals else None
        weather_kpis['weather_tmin_mean'] = round(sum(tmin_vals) / len(tmin_vals), 1) if tmin_vals else None
        weather_kpis['weather_tmin_min'] = round(min(tmin_vals), 1) if tmin_vals else None
        weather_kpis['weather_heat_days'] = heat_days
        weather_kpis['weather_frost_days'] = frost_days
        weather_kpis['weather_gdd_base10'] = round(gdd_total, 1)

        # Procesar agua
        precip_by_date = {}
        et_by_date = {}
        precip_vals, et_vals = [], []
        rain_days = 0

        for f in water_list:
            p = f.get('properties', {})
            d = p.get('date', '')
            pr, et = p.get('precip'), p.get('et')
            if pr is not None:
                precip_vals.append(pr)
                precip_by_date[d] = pr
                if pr > 1: rain_days += 1
            if et is not None:
                et_vals.append(et)
                et_by_date[d] = et

        precip_total = sum(precip_vals) if precip_vals else 0
        et_total = sum(et_vals) if et_vals else 0

        weather_kpis['weather_precip_total_mm'] = round(precip_total, 1) if precip_vals else None
        weather_kpis['weather_precip_max_daily_mm'] = round(max(precip_vals), 1) if precip_vals else None
        weather_kpis['weather_rain_days'] = rain_days
        weather_kpis['weather_et_total_mm'] = round(et_total, 1) if et_vals else None
        weather_kpis['weather_water_balance_mm'] = round(precip_total - et_total, 1)

        # ── Viento + Suelo: 1 solo getInfo() con aggregados del servidor ──
        print("  Fetching ERA5 wind + soil moisture (aggregated)...")
        try:
            wind_u = era5_base.select('u_component_of_wind_10m').mean()
            wind_v = era5_base.select('v_component_of_wind_10m').mean()
            wind_speed = wind_u.pow(2).add(wind_v.pow(2)).sqrt()

            sm = era5_base.select('volumetric_soil_water_layer_1')
            sm_composite = sm.reduce(ee.Reducer.mean().combine(ee.Reducer.min(), sharedInputs=True))

            # Combinar en 1 imagen para 1 solo getInfo()
            combined = wind_speed.rename('wind').addBands(sm_composite)
            combined_stats = combined.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=roi, scale=11132, maxPixels=1e9
            ).getInfo()

            wind_val = combined_stats.get('wind')
            weather_kpis['weather_wind_mean_ms'] = round(wind_val, 1) if wind_val else None
            sm_mean = combined_stats.get('volumetric_soil_water_layer_1_mean')
            sm_min = combined_stats.get('volumetric_soil_water_layer_1_min')
            weather_kpis['weather_soil_moisture_mean'] = round(sm_mean, 3) if sm_mean else None
            weather_kpis['weather_soil_moisture_min'] = round(sm_min, 3) if sm_min else None
        except Exception as e:
            print(f"  Warning: wind/soil query failed: {e}")
            weather_kpis['weather_wind_mean_ms'] = None
            weather_kpis['weather_soil_moisture_mean'] = None

        # ── Serie temporal diaria ──────────────────────────────────
        all_dates = sorted(set(
            list(tmax_by_date.keys()) + list(precip_by_date.keys())
        ))
        for d in all_dates:
            daily_series.append({
                'date': d,
                'tmax_c': round(tmax_by_date.get(d, -9999), 1),
                'tmin_c': round(tmin_by_date.get(d, -9999), 1),
                'precip_mm': round(precip_by_date.get(d, 0), 1),
                'et_mm': round(et_by_date.get(d, 0), 1),
            })

    except Exception as e:
        print(f"Warning: ERA5 weather failed: {e}")
        for k in ['weather_tmax_mean', 'weather_tmin_mean', 'weather_heat_days',
                   'weather_frost_days', 'weather_gdd_base10', 'weather_precip_total_mm',
                   'weather_rain_days', 'weather_et_total_mm', 'weather_water_balance_mm',
                   'weather_wind_mean_ms', 'weather_soil_moisture_mean']:
            weather_kpis.setdefault(k, None)

    return weather_kpis, daily_series


# ============================================================================
# PERSISTIR IMÁGENES EN BD
# ============================================================================

def persist_images_to_db(job_id, images_base64, bounds=None):
    if not images_base64:
        print("⚠️ No images to persist")
        return []

    api_base = os.environ.get('API_BASE_URL', 'https://muorbita-api-production.up.railway.app')
    try:
        payload = json.dumps({
            'job_id': job_id, 'images': images_base64, 'bounds': bounds
        }).encode('utf-8')
        req = urllib.request.Request(
            f'{api_base}/api/images/store', data=payload,
            headers={'Content-Type': 'application/json'}, method='POST'
        )
        result = json.loads(urllib.request.urlopen(req, timeout=60).read().decode('utf-8'))
        if result.get('success'):
            stored = [d['index_type'] for d in result.get('details', [])]
            total_kb = sum(d.get('size_kb', 0) for d in result.get('details', []))
            print(f"✅ Persisted {len(stored)} images ({total_kb} KB): {stored}")
            return stored
        print(f"⚠️ Store API: {result}")
    except Exception as e:
        print(f"⚠️ Could not persist images: {e}")
    return []


# ============================================================================
# GENERADOR DE PNGs — ORQUESTADOR
# ============================================================================

def generate_flat_pngs(composite, latest_sentinel, roi, kpis,
                       index_list, vra_image=None, lst=None):
    """Genera todos los PNGs planos 2D para un análisis."""
    images = {}

    for idx in index_list:
        viz = VIZ_PALETTES.get(idx)
        if not viz:
            continue
        print(f"  Generating flat 2D {idx}...")
        b64 = get_flat_index_png(composite.select(idx), roi, viz, dimensions=768)
        if b64:
            mean_key = f'{idx.lower()}_mean'
            b64 = add_legend(b64, idx, kpis.get(mean_key))
            images[idx] = b64
            print(f"  ✓ {idx}: OK")
        else:
            print(f"  ✗ {idx}: failed")

    if vra_image is not None:
        print("  Generating flat 2D VRA...")
        b64 = get_flat_index_png(vra_image, roi, VIZ_PALETTES['VRA'], dimensions=768)
        if b64:
            images['VRA'] = add_legend(b64, 'VRA')
            print("  ✓ VRA: OK")

    if lst is not None:
        print("  Generating flat 2D LST...")
        b64 = get_flat_index_png(lst, roi, VIZ_PALETTES['LST'], dimensions=512)
        if b64:
            images['LST'] = add_legend(b64, 'LST', kpis.get('lst_mean_c'))
            print("  ✓ LST: OK")

    print("  Generating flat 2D RGB...")
    rgb = get_flat_rgb_png(latest_sentinel, roi, dimensions=768)
    if rgb:
        images['RGB'] = rgb
        print("  ✓ RGB: OK")

    print(f"\n  📊 Total: {len(images)} flat 2D maps")
    return images


# ============================================================================
# ANÁLISIS BIWEEKLY
# ============================================================================

def execute_biweekly_analysis(args):
    roi = create_roi(args.roi, args.buffer)
    job_id = args.job_id
    bounds = get_bounds(roi)

    # Satelital
    collection = get_sentinel2_collection(roi, args.start_date, args.end_date)
    count = collection.size().getInfo()
    if count == 0:
        return {"error": "No images found", "job_id": job_id,
                "analysis_type": "biweekly", "start_date": args.start_date,
                "end_date": args.end_date,
                "suggestion": "Try extending the date range or check cloud cover"}

    indexed = collection.map(calculate_indices)
    composite = indexed.median().clip(roi)
    latest_sentinel = indexed.sort('system:time_start', False).first().clip(roi)

    try:
        latest_date = ee.Date(collection.sort('system:time_start', False).first()
                              .get('system:time_start')).format('YYYY-MM-dd').getInfo()
    except:
        latest_date = args.end_date

    # Estadísticas — 1 solo getInfo()
    print("Computing statistics...")
    stats = composite.select(['NDVI', 'NDWI', 'EVI', 'NDCI']).reduceRegion(
        reducer=ee.Reducer.mean()
            .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=roi, scale=10, maxPixels=1e9
    ).getInfo()

    area_ha = roi.area().divide(10000).getInfo()

    stress_mask = composite.select('NDVI').lt(0.35)
    stress_ha = stress_mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=roi, scale=10, maxPixels=1e9
    ).getInfo().get('NDVI', 0) / 10000
    stress_pct = (stress_ha / area_ha * 100) if area_ha > 0 else 0

    # Z-score
    hist_stats = indexed.select('NDVI').mean().reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=roi, scale=20, maxPixels=1e9
    ).getInfo()
    ndvi_mean = stats.get('NDVI_mean', 0) or 0
    hist_mean = hist_stats.get('NDVI_mean', ndvi_mean) or ndvi_mean
    hist_std = hist_stats.get('NDVI_stdDev', 0.1) or 0.1
    z_score = (ndvi_mean - hist_mean) / hist_std if hist_std > 0 else 0

    # ERA5
    print("Fetching ERA5 weather data...")
    weather_kpis, weather_daily = get_era5_weather(roi, args.start_date, args.end_date)

    # LST
    try:
        lst = get_modis_lst(roi, args.start_date, args.end_date)
        lst_mean = lst.reduceRegion(ee.Reducer.mean(), roi, 1000, maxPixels=1e9).getInfo().get('LST_C_mean')
    except:
        lst, lst_mean = None, None

    # Serie temporal — limitada a 50
    print("Computing time series...")
    time_series = []
    try:
        ts = indexed.select(['NDVI', 'NDWI', 'EVI']).map(lambda img:
            ee.Feature(None, img.reduceRegion(
                ee.Reducer.mean(), roi, 20, maxPixels=1e9
            )).set('date', ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'))
        )
        for f in ts.toList(50).getInfo():
            p = f.get('properties', {})
            if p.get('date'):
                time_series.append({
                    'date': p['date'],
                    'ndvi': round(p.get('NDVI_mean', 0) or 0, 3),
                    'ndwi': round(p.get('NDWI_mean', 0) or 0, 3),
                    'evi': round(p.get('EVI_mean', 0) or 0, 3)
                })
        time_series.sort(key=lambda x: x['date'])
    except Exception as e:
        print(f"Warning: time series failed: {e}")

    # PNGs planos 2D
    print("Generating flat 2D PNG maps...")
    kpis = {
        'job_id': job_id, 'crop_type': args.crop, 'analysis_type': 'biweekly',
        'start_date': args.start_date, 'end_date': args.end_date,
        'latest_image_date': latest_date, 'images_processed': count,
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

    images_base64 = generate_flat_pngs(composite, latest_sentinel, roi, kpis,
                                        index_list=['NDVI', 'NDWI'])

    stored = persist_images_to_db(job_id, images_base64, bounds)

    return {
        'success': True, 'job_id': job_id, 'analysis_type': 'biweekly',
        'kpis': kpis, 'weather': weather_kpis, 'weather_daily': weather_daily,
        'bounds': bounds, 'time_series': time_series,
        'images_stored': stored, 'images_available': list(images_base64.keys()),
        'images_base64': {} if stored else images_base64,
        'tasks': [], 'task_count': 0,
        'message': f'Biweekly v5.3 complete. {len(stored)} flat 2D images in DB.'
    }


# ============================================================================
# ANÁLISIS BASELINE
# ============================================================================

def execute_analysis(args):
    roi = create_roi(args.roi, args.buffer)
    job_id = args.job_id
    bounds = get_bounds(roi)

    # Satelital
    collection = get_sentinel2_collection(roi, args.start_date, args.end_date)
    count = collection.size().getInfo()
    if count == 0:
        return {"error": "No images found", "job_id": job_id,
                "start_date": args.start_date, "end_date": args.end_date}

    indexed = collection.map(calculate_indices)
    composite = indexed.median().clip(roi)
    latest_sentinel = indexed.sort('system:time_start', False).first().clip(roi)

    try:
        latest_date = ee.Date(collection.sort('system:time_start', False).first()
                              .get('system:time_start')).format('YYYY-MM-dd').getInfo()
    except:
        latest_date = args.end_date

    # Estadísticas — 1 getInfo() combinado
    print("Computing statistics...")
    stats = composite.select(['NDVI', 'NDWI', 'EVI', 'NDCI', 'SAVI', 'OSAVI']).reduceRegion(
        reducer=ee.Reducer.mean()
            .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True)
            .combine(ee.Reducer.count(), sharedInputs=True),
        geometry=roi, scale=10, maxPixels=1e9
    ).getInfo()

    area_ha = roi.area().divide(10000).getInfo()

    stress_ha = composite.select('NDVI').lt(0.35).multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=roi, scale=10, maxPixels=1e9
    ).getInfo().get('NDVI', 0) / 10000
    stress_pct = (stress_ha / area_ha * 100) if area_ha > 0 else 0

    hist_stats = indexed.select('NDVI').mean().reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=roi, scale=20, maxPixels=1e9
    ).getInfo()
    ndvi_mean = stats.get('NDVI_mean', 0) or 0
    hist_mean = hist_stats.get('NDVI_mean', ndvi_mean) or ndvi_mean
    hist_std = hist_stats.get('NDVI_stdDev', 0.1) or 0.1
    z_score = (ndvi_mean - hist_mean) / hist_std if hist_std > 0 else 0

    # LST
    try:
        lst = get_modis_lst(roi, args.start_date, args.end_date)
        lst_stats = lst.reduceRegion(
            reducer=ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True),
            geometry=roi, scale=1000, maxPixels=1e9
        ).getInfo()
        lst_mean = lst_stats.get('LST_C_mean')
        lst_min = lst_stats.get('LST_C_min')
        lst_max = lst_stats.get('LST_C_max')
    except:
        lst = None
        lst_mean = lst_min = lst_max = None

    # VRA
    print("Computing VRA zones...")
    vra_image, vra_stats = calculate_vra_zones(composite, roi)

    # KPIs
    kpis = {
        'job_id': job_id, 'crop_type': args.crop,
        'analysis_type': args.analysis_type,
        'start_date': args.start_date, 'end_date': args.end_date,
        'latest_image_date': latest_date, 'images_processed': count,
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

    # PNGs planos 2D
    print("Generating flat 2D PNG maps...")
    images_base64 = generate_flat_pngs(
        composite, latest_sentinel, roi, kpis,
        index_list=['NDVI', 'NDWI', 'EVI', 'NDCI', 'SAVI'],
        vra_image=vra_image, lst=lst
    )

    # Serie temporal
    print("Computing time series...")
    time_series = []
    try:
        ts = indexed.select(['NDVI', 'NDWI', 'EVI']).map(lambda img:
            ee.Feature(None, img.reduceRegion(
                reducer=ee.Reducer.mean()
                    .combine(ee.Reducer.percentile([10, 90]), sharedInputs=True),
                geometry=roi, scale=20, maxPixels=1e9
            )).set('date', ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'))
        )
        for f in ts.toList(50).getInfo():
            p = f.get('properties', {})
            if p.get('date'):
                time_series.append({
                    'date': p['date'],
                    'ndvi': round(p.get('NDVI_mean', 0) or 0, 3),
                    'ndwi': round(p.get('NDWI_mean', 0) or 0, 3),
                    'evi': round(p.get('EVI_mean', 0) or 0, 3)
                })
        time_series.sort(key=lambda x: x['date'])
    except Exception as e:
        print(f"Warning: time series failed: {e}")

    # Persistir
    stored = persist_images_to_db(job_id, images_base64, bounds)

    return {
        'success': True, 'job_id': job_id, 'analysis_type': 'baseline',
        'kpis': kpis, 'vra_stats': vra_stats, 'bounds': bounds,
        'time_series': time_series,
        'images_stored': stored, 'images_available': list(images_base64.keys()),
        'images_base64': {} if stored else images_base64,
        'tasks': [], 'task_count': 0,
        'message': f'Baseline v5.3 complete. {len(stored)} flat 2D images in DB.'
    }


# ============================================================================
# LEGACY ENDPOINTS
# ============================================================================

def check_status(args):
    return {'job_id': args.job_id, 'all_complete': True, 'progress_pct': 100,
            'message': 'v5.3: Synchronous. No async tasks.'}

def download_results(args):
    return {'job_id': args.job_id, 'status': 'ready', 'download_ready': True,
            'message': 'v5.3: Data in execute response.'}

def start_tasks(args):
    return {'job_id': args.job_id, 'started': 0,
            'message': 'v5.3: No async tasks.'}

# ============================================================================
# MAIN
# ============================================================================

def main():
    args = parse_args()
    try:
        if args.mode == 'execute':
            if getattr(args, 'analysis_type', 'baseline') == 'biweekly':
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
        print(json.dumps({'error': str(e), 'traceback': traceback.format_exc()}))
        sys.exit(1)

if __name__ == '__main__':
    main()
