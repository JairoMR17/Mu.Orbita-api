#!/usr/bin/env python3
"""
Mu.Orbita GEE Automation Script v5.7
=============================================================

CAMBIOS V5.7:
✅ VRA: Score compuesto determinista (NDVI 60% + NDWI 25% + EVI 15%)
   reemplaza K-Means no determinista
✅ Serie temporal desacoplada: 1 año para gráfico histórico
   mientras composite/mapas/VRA usan 6 meses (época coherente)
✅ Biweekly: serie temporal también extendida a 1 año

CAMBIOS V5.6:
✅ Compositor de basemap Esri INTEGRADO (todo en un solo archivo)
✅ Descarga tiles Esri World Imagery → compone con PIL → resultado estilo GEE/QGIS
✅ Dos tipos de imagen: NDVI (cartográfico para PDF) + NDVI_WEB (overlay para Leaflet)
✅ Fallback automático si tiles no disponibles
✅ SIN archivos externos — todo self-contained

FLUJO DE IMÁGENES:
    1. GEE genera overlay limpio (colores del índice clipados a parcela) → NDVI_WEB
    2. Python descarga tiles Esri para el bbox de la parcela
    3. PIL compone: basemap + overlay semitransparente + contorno → NDVI
    4. Ambos se guardan en BD (gee_images)
    5. Dashboard usa NDVI_WEB (overlay sobre Leaflet basemap)
    6. PDF usa NDVI (cartográfico autocontenido con basemap real)
"""

import argparse
import json
import ee
import sys
import os
import io
import math
import base64
import urllib.request
from datetime import datetime, timedelta

# ============================================================================
# INICIALIZACIÓN GEE
# ============================================================================

def initialize_gee():
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
# PALETAS
# ============================================================================

VIZ_PALETTES = {
    'NDVI': {
        'min': 0.0, 'max': 0.8,
        'palette': ['8B0000','FF0000','FF6347','FFA500','FFFF00',
                    'ADFF2F','7CFC00','32CD32','228B22','006400'],
        'label': 'NDVI (Vigor Vegetativo)', 'unit': ''
    },
    'NDWI': {
        'min': -0.3, 'max': 0.4,
        'palette': ['8B4513','D2691E','F4A460','FFF8DC','E0FFFF',
                    '87CEEB','4682B4','0000CD','00008B'],
        'label': 'NDWI (Estado Hídrico)', 'unit': ''
    },
    'EVI': {
        'min': 0.0, 'max': 0.6,
        'palette': ['8B0000','CD5C5C','F08080','FFFFE0','ADFF2F',
                    '7FFF00','32CD32','228B22','006400'],
        'label': 'EVI (Productividad)', 'unit': ''
    },
    'NDCI': {
        'min': -0.2, 'max': 0.6,
        'palette': ['8B0000','FF6347','FFA500','FFFF00','ADFF2F',
                    '7CFC00','32CD32','228B22','006400'],
        'label': 'NDCI (Clorofila)', 'unit': ''
    },
    'SAVI': {
        'min': 0.0, 'max': 0.8,
        'palette': ['8B0000','FF0000','FF6347','FFA500','FFFF00',
                    'ADFF2F','7CFC00','32CD32','228B22','006400'],
        'label': 'SAVI (Vigor Ajustado Suelo)', 'unit': ''
    },
    'VRA': {
        'min': 0, 'max': 2,
        'palette': ['e74c3c','f1c40f','27ae60'],
        'label': 'Zonas de Manejo Variable', 'unit': ''
    },
    'LST': {
        'min': 15, 'max': 45,
        'palette': ['0000FF','00FFFF','00FF00','FFFF00','FF0000'],
        'label': 'Temperatura Superficial', 'unit': '°C'
    }
}

# ============================================================================
# ARGUMENTOS
# ============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description='Mu.Orbita GEE v5.7')
    parser.add_argument('--mode', required=True,
                        choices=['execute','check-status','download-results','start-tasks'])
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--roi', help='GeoJSON string of ROI')
    parser.add_argument('--start-date', help='Start date YYYY-MM-DD')
    parser.add_argument('--end-date', help='End date YYYY-MM-DD')
    parser.add_argument('--crop', default='olivar')
    parser.add_argument('--buffer', type=int, default=0)
    parser.add_argument('--analysis-type', default='baseline')
    parser.add_argument('--drive-folder', default='MuOrbita_Outputs')
    parser.add_argument('--output-dir', help='Local output directory')
    parser.add_argument('--export-png', type=bool, default=True)
    return parser.parse_args()

# ============================================================================
# UTILIDADES GEE
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


# ############################################################################
#
#  SECCIÓN 1: GENERADOR DE PNGs PARA LEAFLET (overlay limpio)
#
# ############################################################################

def get_leaflet_overlay_png(index_image_unclipped, roi, viz_params, dimensions=512):
    """
    PNG limpio para Leaflet: solo colores del índice DENTRO de la parcela.
    Sin fondo, sin contorno, sin leyenda. Bounds = exactos de parcela.
    """
    try:
        viz_kw = {k: v for k, v in viz_params.items() if k in ('min','max','palette')}
        index_clipped = index_image_unclipped.clip(roi).visualize(**viz_kw)
        region_coords = roi.bounds().getInfo()['coordinates']
        url = index_clipped.getThumbURL({
            'region': region_coords, 'dimensions': dimensions, 'format': 'png'
        })
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'MuOrbita/5.7')
        png_bytes = urllib.request.urlopen(req, timeout=60).read()
        if len(png_bytes) < 100:
            return None
        return base64.b64encode(png_bytes).decode('utf-8')
    except Exception as e:
        print(f"Warning: Leaflet overlay failed: {e}")
        return None


# ############################################################################
#
#  SECCIÓN 2: COMPOSITOR CARTOGRÁFICO (basemap Esri + índice + contorno)
#             TODO INLINE — sin archivos externos
#
# ############################################################################

def _lat_lon_to_tile(lat, lon, zoom):
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0/math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y

def _tile_to_lat_lon(x, y, zoom):
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    return math.degrees(lat_rad), lon

def _get_optimal_zoom(bounds, target_width=768):
    for z in range(17, 10, -1):
        x1, _ = _lat_lon_to_tile(bounds['south'], bounds['west'], z)
        x2, _ = _lat_lon_to_tile(bounds['south'], bounds['east'], z)
        if (x2 - x1 + 1) <= 8:
            return z
    return 14

def _fetch_tile(x, y, z):
    url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'MuOrbita/5.7')
        req.add_header('Referer', 'https://muorbita.com')
        return urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        return None

def _geo_to_pixel(lat, lon, geo_bounds, img_w, img_h):
    x = int((lon - geo_bounds['west']) / (geo_bounds['east'] - geo_bounds['west']) * img_w)
    y = int((geo_bounds['north'] - lat) / (geo_bounds['north'] - geo_bounds['south']) * img_h)
    return max(0, min(x, img_w-1)), max(0, min(y, img_h-1))


def fetch_esri_basemap(bounds, padding_tiles=1):
    from PIL import Image as PILImage

    zoom = _get_optimal_zoom(bounds)
    x_min, y_min = _lat_lon_to_tile(bounds['north'], bounds['west'], zoom)
    x_max, y_max = _lat_lon_to_tile(bounds['south'], bounds['east'], zoom)

    x_min -= padding_tiles
    x_max += padding_tiles
    y_min -= padding_tiles
    y_max += padding_tiles

    tiles_x = x_max - x_min + 1
    tiles_y = y_max - y_min + 1
    total = tiles_x * tiles_y

    print(f"  [basemap] Fetching {tiles_x}x{tiles_y} = {total} Esri tiles at zoom {zoom}...")

    tile_size = 256
    canvas = PILImage.new('RGB', (tiles_x * tile_size, tiles_y * tile_size), (180, 176, 168))

    fetched = 0
    for ty in range(y_min, y_max + 1):
        for tx in range(x_min, x_max + 1):
            tile_bytes = _fetch_tile(tx, ty, zoom)
            if tile_bytes and len(tile_bytes) > 100:
                try:
                    tile_img = PILImage.open(io.BytesIO(tile_bytes))
                    px = (tx - x_min) * tile_size
                    py = (ty - y_min) * tile_size
                    canvas.paste(tile_img, (px, py))
                    fetched += 1
                except Exception:
                    pass

    if fetched == 0:
        print(f"  [basemap] ❌ No tiles fetched — network issue?")
        return None, None

    nw_lat, nw_lon = _tile_to_lat_lon(x_min, y_min, zoom)
    se_lat, se_lon = _tile_to_lat_lon(x_max + 1, y_max + 1, zoom)
    geo_bounds = {'north': nw_lat, 'south': se_lat, 'west': nw_lon, 'east': se_lon}

    print(f"  [basemap] ✓ {fetched}/{total} tiles, {canvas.size[0]}x{canvas.size[1]} px")
    return canvas, geo_bounds


def compose_cartographic_png(basemap_img, geo_bounds, index_b64, parcel_bounds,
                             roi_coords, index_name='NDVI', mean_value=None,
                             opacity=0.65, dim_factor=0.40, max_dim=768):
    from PIL import Image as PILImage, ImageDraw, ImageFont

    bw, bh = basemap_img.size

    dim_overlay = PILImage.new('RGBA', (bw, bh), (255, 255, 255, int(255 * (1 - dim_factor))))
    x1, y1 = _geo_to_pixel(parcel_bounds['north'], parcel_bounds['west'], geo_bounds, bw, bh)
    x2, y2 = _geo_to_pixel(parcel_bounds['south'], parcel_bounds['east'], geo_bounds, bw, bh)
    dim_draw = ImageDraw.Draw(dim_overlay)
    dim_draw.rectangle([x1, y1, x2, y2], fill=(255, 255, 255, 0))

    result = basemap_img.convert('RGBA')
    result = PILImage.alpha_composite(result, dim_overlay)

    index_bytes = base64.b64decode(index_b64)
    index_img = PILImage.open(io.BytesIO(index_bytes)).convert('RGBA')

    target_w = max(x2 - x1, 1)
    target_h = max(y2 - y1, 1)
    index_resized = index_img.resize((target_w, target_h), PILImage.LANCZOS)

    r, g, b, a = index_resized.split()
    a_adjusted = a.point(lambda p: int(p * opacity) if p > 10 else 0)
    index_resized.putalpha(a_adjusted)

    result.paste(index_resized, (x1, y1), index_resized)

    draw = ImageDraw.Draw(result)
    poly_points = _extract_polygon_pixels(roi_coords, geo_bounds, bw, bh)
    if poly_points and len(poly_points) >= 3:
        shadow = [(p[0]+2, p[1]+2) for p in poly_points]
        for i in range(len(shadow)-1):
            draw.line([shadow[i], shadow[i+1]], fill=(0,0,0,200), width=4)
        draw.line([shadow[-1], shadow[0]], fill=(0,0,0,200), width=4)
        for i in range(len(poly_points)-1):
            draw.line([poly_points[i], poly_points[i+1]], fill=(255,255,255,255), width=3)
        draw.line([poly_points[-1], poly_points[0]], fill=(255,255,255,255), width=3)

    pad = 80
    crop_x1 = max(0, x1 - pad)
    crop_y1 = max(0, y1 - pad)
    crop_x2 = min(bw, x2 + pad)
    crop_y2 = min(bh, y2 + pad)
    cropped = result.crop((crop_x1, crop_y1, crop_x2, crop_y2)).convert('RGB')

    cw, ch = cropped.size
    if max(cw, ch) > max_dim:
        ratio = max_dim / max(cw, ch)
        cropped = cropped.resize((int(cw * ratio), int(ch * ratio)), PILImage.LANCZOS)

    cropped = _add_legend_pil(cropped, index_name, mean_value)

    buf = io.BytesIO()
    cropped.save(buf, format='PNG', optimize=True)
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode('utf-8')


def _extract_polygon_pixels(roi_coords, geo_bounds, img_w, img_h):
    coords = None
    if isinstance(roi_coords, dict):
        c = roi_coords.get('coordinates', [[]])
        if c and isinstance(c[0], list):
            if c[0] and isinstance(c[0][0], list):
                coords = c[0]
            else:
                coords = c
    elif isinstance(roi_coords, list):
        if roi_coords and isinstance(roi_coords[0], list):
            if roi_coords[0] and isinstance(roi_coords[0][0], list):
                coords = roi_coords[0]
            else:
                coords = roi_coords
    if not coords:
        return []

    points = []
    for c in coords:
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            px, py = _geo_to_pixel(c[1], c[0], geo_bounds, img_w, img_h)
            points.append((px, py))
    return points


def _add_legend_pil(img, index_name, mean_value=None):
    from PIL import Image as PILImage, ImageDraw, ImageFont

    viz = VIZ_PALETTES.get(index_name)
    if not viz:
        return img

    legend_h, pad, bar_h = 90, 20, 18
    bar_w = min(350, img.width - 2*pad)

    new_img = PILImage.new('RGB', (img.width, img.height + legend_h), (249,247,242))
    new_img.paste(img, (0, 0))
    draw = ImageDraw.Draw(new_img)
    draw.line([(0, img.height), (img.width, img.height)], fill=(200,195,185), width=1)

    try:
        ft = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
        fs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        fv = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    except (OSError, IOError):
        ft = fs = fv = ImageFont.load_default()

    y0 = img.height + 8
    accent, dark, muted = (139,69,19), (51,51,51), (136,136,136)

    label = viz.get('label', index_name)
    draw.text((pad, y0), label, fill=accent, font=ft)
    if mean_value is not None:
        try:
            tw = draw.textbbox((0,0), label, font=ft)[2]
        except AttributeError:
            tw = len(label) * 8
        draw.text((pad + tw + 20, y0 + 1), f"Media: {mean_value:.2f}", fill=dark, font=fv)

    bar_y, bar_x = y0 + 24, pad
    colors = [tuple(int(h[i:i+2], 16) for i in (0,2,4)) for h in viz['palette']]
    n = len(colors)
    for x in range(bar_w):
        t = x / bar_w
        idx = t * (n - 1)
        i = min(int(idx), n - 2)
        f = idx - i
        c = tuple(int(colors[i][j]*(1-f) + colors[i+1][j]*f) for j in range(3))
        draw.rectangle([bar_x+x, bar_y, bar_x+x+1, bar_y+bar_h], fill=c)
    draw.rectangle([bar_x, bar_y, bar_x+bar_w, bar_y+bar_h], outline=(100,100,100), width=1)

    unit = viz.get('unit', '')
    draw.text((bar_x, bar_y + bar_h + 3), f"{viz['min']}{unit}", fill=muted, font=fs)
    mx_txt = f"{viz['max']}{unit}"
    try:
        mx_w = draw.textbbox((0,0), mx_txt, font=fs)[2]
    except AttributeError:
        mx_w = len(mx_txt) * 6
    draw.text((bar_x + bar_w - mx_w, bar_y + bar_h + 3), mx_txt, fill=muted, font=fs)

    if mean_value is not None:
        rng = viz['max'] - viz['min']
        if rng > 0:
            t = max(0, min(1, (mean_value - viz['min']) / rng))
            mx = bar_x + int(t * bar_w)
            draw.polygon([(mx, bar_y-2), (mx-6, bar_y-8), (mx+6, bar_y-8)], fill=dark)

    return new_img


# ############################################################################
#
#  SECCIÓN 3: ORQUESTADOR — genera web overlays + cartográficos
#
# ############################################################################

def generate_all_images(composite_unclipped, roi, bounds, kpis,
                        index_list, vra_image=None, lst_unclipped=None):
    images = {}

    OPACITY_MAP = {
        'NDVI': 0.65, 'NDWI': 0.70, 'EVI': 0.65,
        'NDCI': 0.65, 'SAVI': 0.65, 'VRA': 0.75, 'LST': 0.60,
    }

    print("\n  === Step 1: GEE overlays for Leaflet ===")
    web_overlays = {}

    for idx in index_list:
        viz = VIZ_PALETTES.get(idx)
        if not viz:
            continue
        b64 = get_leaflet_overlay_png(composite_unclipped.select(idx), roi, viz)
        if b64:
            web_overlays[idx] = b64
            images[f'{idx}_WEB'] = b64
            print(f"  ✓ {idx}_WEB")

    if vra_image is not None:
        b64 = get_leaflet_overlay_png(vra_image, roi, VIZ_PALETTES['VRA'])
        if b64:
            web_overlays['VRA'] = b64
            images['VRA_WEB'] = b64
            print(f"  ✓ VRA_WEB")

    if lst_unclipped is not None:
        b64 = get_leaflet_overlay_png(lst_unclipped, roi, VIZ_PALETTES['LST'])
        if b64:
            web_overlays['LST'] = b64
            images['LST_WEB'] = b64
            print(f"  ✓ LST_WEB")

    print("\n  === Step 2: Fetch Esri basemap ===")
    basemap_img = None
    geo_bounds = None

    if bounds:
        try:
            basemap_img, geo_bounds = fetch_esri_basemap(bounds, padding_tiles=1)
        except Exception as e:
            print(f"  ⚠ Basemap fetch failed: {e}")

    if basemap_img and geo_bounds:
        print("\n  === Step 3: Compositing cartographic PNGs ===")

        try:
            roi_info = roi.getInfo()
        except:
            roi_info = {}

        for idx, overlay_b64 in web_overlays.items():
            opacity = OPACITY_MAP.get(idx, 0.65)
            mean_key = f'{idx.lower()}_mean'
            mean_val = kpis.get(mean_key)

            try:
                carto_b64 = compose_cartographic_png(
                    basemap_img=basemap_img.copy(),
                    geo_bounds=geo_bounds,
                    index_b64=overlay_b64,
                    parcel_bounds=bounds,
                    roi_coords=roi_info,
                    index_name=idx,
                    mean_value=mean_val,
                    opacity=opacity
                )
                if carto_b64:
                    images[idx] = carto_b64
                    print(f"  ✓ {idx} (cartographic, {len(carto_b64)//1024} KB)")
                else:
                    images[idx] = _fallback_with_legend(overlay_b64, idx, mean_val)
                    print(f"  ⚠ {idx} fallback (overlay+legend)")
            except Exception as e:
                print(f"  ⚠ {idx} compositor error: {e}")
                images[idx] = _fallback_with_legend(overlay_b64, idx, mean_val)

        try:
            from PIL import Image as PILImage
            bw, bh = basemap_img.size
            x1, y1 = _geo_to_pixel(bounds['north'], bounds['west'], geo_bounds, bw, bh)
            x2, y2 = _geo_to_pixel(bounds['south'], bounds['east'], geo_bounds, bw, bh)
            pad = 80
            cropped = basemap_img.crop((
                max(0, x1-pad), max(0, y1-pad),
                min(bw, x2+pad), min(bh, y2+pad)
            ))
            cw, ch = cropped.size
            if max(cw, ch) > 768:
                ratio = 768 / max(cw, ch)
                cropped = cropped.resize((int(cw*ratio), int(ch*ratio)), PILImage.LANCZOS)
            buf = io.BytesIO()
            cropped.save(buf, format='PNG', optimize=True)
            images['RGB'] = base64.b64encode(buf.getvalue()).decode('utf-8')
            print(f"  ✓ RGB (satellite)")
        except Exception as e:
            print(f"  ⚠ RGB failed: {e}")
    else:
        print("\n  === Step 3: FALLBACK (no basemap) ===")
        for idx, overlay_b64 in web_overlays.items():
            mean_key = f'{idx.lower()}_mean'
            images[idx] = _fallback_with_legend(overlay_b64, idx, kpis.get(mean_key))
            print(f"  ⚠ {idx} fallback (overlay+legend)")

    total_web = sum(1 for k in images if k.endswith('_WEB'))
    total_carto = len(images) - total_web
    print(f"\n  📊 Total: {len(images)} images ({total_web} web + {total_carto} carto)")
    return images


def _fallback_with_legend(overlay_b64, index_name, mean_value):
    try:
        from PIL import Image as PILImage
        img_bytes = base64.b64decode(overlay_b64)
        img = PILImage.open(io.BytesIO(img_bytes)).convert('RGB')
        result = _add_legend_pil(img, index_name, mean_value)
        buf = io.BytesIO()
        result.save(buf, format='PNG', optimize=True)
        return base64.b64encode(buf.getvalue()).decode('utf-8')
    except:
        return overlay_b64


# ############################################################################
#
#  SECCIÓN 4: COLECCIONES GEE, ÍNDICES, ERA5, VRA
#
# ############################################################################

def get_sentinel2_collection(roi, start_date, end_date):
    def mask_clouds(image):
        qa = image.select('QA60')
        scl = image.select('SCL')
        cloud_mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
        scl_mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
        return (image.updateMask(cloud_mask.And(scl_mask))
                .divide(10000).copyProperties(image, ['system:time_start']))
    return (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(roi).filterDate(start_date, end_date)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
        .map(mask_clouds))

def calculate_indices(image):
    nir, red, blue = image.select('B8'), image.select('B4'), image.select('B2')
    ndvi = image.normalizedDifference(['B8','B4']).rename('NDVI')
    ndwi = image.normalizedDifference(['B8','B11']).rename('NDWI')
    evi = image.expression(
        '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
        {'NIR': nir, 'RED': red, 'BLUE': blue}).rename('EVI')
    ndci = image.normalizedDifference(['B5','B4']).rename('NDCI')
    L = 0.5
    savi = nir.subtract(red).divide(nir.add(red).add(L)).multiply(1+L).rename('SAVI')
    osavi = nir.subtract(red).divide(nir.add(red).add(0.16)).multiply(1.16).rename('OSAVI')
    return image.addBands([ndvi, ndwi, evi, ndci, savi, osavi])

def get_modis_lst(roi, start_date, end_date):
    return (ee.ImageCollection('MODIS/061/MOD11A2')
        .filterBounds(roi).filterDate(start_date, end_date)
        .select('LST_Day_1km')
        .map(lambda img: img.multiply(0.02).subtract(273.15).rename('LST_C')
             .copyProperties(img, ['system:time_start']))
    ).median()


def calculate_vra_zones(composite_clipped, roi):
    """
    VRA v5.7: Score compuesto determinista (NDVI 60% + NDWI 25% + EVI 15%)
    Clasificación por percentiles P33/P66 del score.
    Reemplaza K-Means no determinista de v5.6.
    """
    try:
        ndvi = composite_clipped.select('NDVI')
        ndwi = composite_clipped.select('NDWI')
        evi  = composite_clipped.select('EVI')

        # Normalizar cada índice a 0-1 dentro de la parcela
        def normalize(img, name):
            stats = img.reduceRegion(
                ee.Reducer.minMax(), roi, 10, maxPixels=1e9).getInfo()
            mn = stats.get(f'{name}_min', 0) or 0
            mx = stats.get(f'{name}_max', 1) or 1
            if mx == mn:
                mx = mn + 0.001  # evitar división por cero
            return img.subtract(mn).divide(mx - mn).rename(name + '_norm')

        ndvi_n = normalize(ndvi, 'NDVI')
        ndwi_n = normalize(ndwi, 'NDWI')
        evi_n  = normalize(evi,  'EVI')

        # Score compuesto ponderado
        score = (ndvi_n.multiply(0.60)
                 .add(ndwi_n.multiply(0.25))
                 .add(evi_n.multiply(0.15))
                 .rename('score'))

        # Umbrales por percentiles del score calculados sobre la parcela
        percs = score.reduceRegion(
            ee.Reducer.percentile([33, 66]), roi, 10, maxPixels=1e9
        ).getInfo()
        p33 = percs.get('score_p33', 0.33)
        p66 = percs.get('score_p66', 0.66)

        print(f"  VRA score thresholds — P33: {p33:.3f}, P66: {p66:.3f}")

        # Clasificación: 0=bajo, 1=medio, 2=alto
        vra = (score.lt(p33).multiply(0)
               .add(score.gte(p33).And(score.lt(p66)).multiply(1))
               .add(score.gte(p66).multiply(2))
               .rename('zone')
               .updateMask(ndvi.mask()))

        # Estadísticas por zona
        vra_stats = []
        for z, label, rec in [(0, 'Bajo vigor', 'Dosis alta'),
                               (1, 'Vigor medio', 'Dosis media'),
                               (2, 'Alto vigor', 'Dosis baja')]:
            zm = vra.eq(z)
            area = zm.multiply(ee.Image.pixelArea()).reduceRegion(
                ee.Reducer.sum(), roi, 10, maxPixels=1e9).getInfo()
            idx = composite_clipped.select(['NDVI', 'NDWI', 'EVI']).updateMask(zm).reduceRegion(
                ee.Reducer.mean(), roi, 10, maxPixels=1e9).getInfo()
            vra_stats.append({
                'zone': z,
                'label': label,
                'recommendation': rec,
                'area_ha': round(area.get('zone', 0) / 10000, 2),
                'ndvi_mean': round(idx.get('NDVI', 0) or 0, 3),
                'ndwi_mean': round(idx.get('NDWI', 0) or 0, 3),
                'evi_mean':  round(idx.get('EVI',  0) or 0, 3),
            })

        return vra, vra_stats

    except Exception as e:
        print(f"Warning: VRA failed: {e}")
        return None, []


# ############################################################################
#  ERA5 WEATHER
# ############################################################################

def get_era5_weather(roi, start_date, end_date):
    weather_kpis = {}
    daily_series = []
    try:
        era5 = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
            .filterDate(start_date, end_date).filterBounds(roi))
        temp = era5.select(['temperature_2m_max','temperature_2m_min']).map(
            lambda img: img.subtract(273.15).copyProperties(img, ['system:time_start']))
        temp_feat = temp.map(lambda img: ee.Feature(None, {
            'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            'tmax': img.select('temperature_2m_max').reduceRegion(
                ee.Reducer.mean(), roi, 11132, maxPixels=1e9).get('temperature_2m_max'),
            'tmin': img.select('temperature_2m_min').reduceRegion(
                ee.Reducer.mean(), roi, 11132, maxPixels=1e9).get('temperature_2m_min'),
        }))
        water = era5.select(['total_precipitation_sum','total_evaporation_sum']).map(
            lambda img: ee.Image([
                img.select('total_precipitation_sum').multiply(1000).rename('precip_mm'),
                img.select('total_evaporation_sum').multiply(-1000).rename('et_mm')
            ]).copyProperties(img, ['system:time_start']))
        water_feat = water.map(lambda img: ee.Feature(None, {
            'date': ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            'precip': img.select('precip_mm').reduceRegion(
                ee.Reducer.mean(), roi, 11132, maxPixels=1e9).get('precip_mm'),
            'et': img.select('et_mm').reduceRegion(
                ee.Reducer.mean(), roi, 11132, maxPixels=1e9).get('et_mm'),
        }))
        print("  Fetching ERA5 temp + water...")
        temp_list = temp_feat.toList(50).getInfo()
        water_list = water_feat.toList(50).getInfo()
        tmax_by_date, tmin_by_date = {}, {}
        tmax_vals, tmin_vals = [], []
        heat_days, frost_days, gdd = 0, 0, 0
        for f in temp_list:
            p = f.get('properties', {})
            d, tx, tn = p.get('date',''), p.get('tmax'), p.get('tmin')
            if tx is not None:
                tmax_vals.append(tx); tmax_by_date[d] = tx
                if tx >= 35: heat_days += 1
            if tn is not None:
                tmin_vals.append(tn); tmin_by_date[d] = tn
                if tn <= 0: frost_days += 1
        for d in tmax_by_date:
            tx, tn = tmax_by_date.get(d), tmin_by_date.get(d)
            if tx is not None and tn is not None:
                gdd += max(0, (tx+tn)/2 - 10)
        weather_kpis['weather_tmax_mean'] = round(sum(tmax_vals)/len(tmax_vals), 1) if tmax_vals else None
        weather_kpis['weather_tmax_max'] = round(max(tmax_vals), 1) if tmax_vals else None
        weather_kpis['weather_tmin_mean'] = round(sum(tmin_vals)/len(tmin_vals), 1) if tmin_vals else None
        weather_kpis['weather_tmin_min'] = round(min(tmin_vals), 1) if tmin_vals else None
        weather_kpis['weather_heat_days'] = heat_days
        weather_kpis['weather_frost_days'] = frost_days
        weather_kpis['weather_gdd_base10'] = round(gdd, 1)
        precip_by_date, et_by_date = {}, {}
        precip_vals, et_vals = [], []
        rain_days = 0
        for f in water_list:
            p = f.get('properties', {})
            d, pr, et = p.get('date',''), p.get('precip'), p.get('et')
            if pr is not None:
                precip_vals.append(pr); precip_by_date[d] = pr
                if pr > 1: rain_days += 1
            if et is not None:
                et_vals.append(et); et_by_date[d] = et
        pt = sum(precip_vals) if precip_vals else 0
        ett = sum(et_vals) if et_vals else 0
        weather_kpis['weather_precip_total_mm'] = round(pt, 1) if precip_vals else None
        weather_kpis['weather_precip_max_daily_mm'] = round(max(precip_vals), 1) if precip_vals else None
        weather_kpis['weather_rain_days'] = rain_days
        weather_kpis['weather_et_total_mm'] = round(ett, 1) if et_vals else None
        weather_kpis['weather_water_balance_mm'] = round(pt - ett, 1)
        print("  Fetching ERA5 wind + soil...")
        try:
            wu = era5.select('u_component_of_wind_10m').mean()
            wv = era5.select('v_component_of_wind_10m').mean()
            wind = wu.pow(2).add(wv.pow(2)).sqrt().rename('wind')
            sm = era5.select('volumetric_soil_water_layer_1').reduce(
                ee.Reducer.mean().combine(ee.Reducer.min(), sharedInputs=True))
            combined = wind.addBands(sm).reduceRegion(
                ee.Reducer.mean(), roi, 11132, maxPixels=1e9).getInfo()
            wv_val = combined.get('wind')
            weather_kpis['weather_wind_mean_ms'] = round(wv_val, 1) if wv_val else None
            sm_m = combined.get('volumetric_soil_water_layer_1_mean')
            sm_mn = combined.get('volumetric_soil_water_layer_1_min')
            weather_kpis['weather_soil_moisture_mean'] = round(sm_m, 3) if sm_m else None
            weather_kpis['weather_soil_moisture_min'] = round(sm_mn, 3) if sm_mn else None
        except:
            weather_kpis['weather_wind_mean_ms'] = None
            weather_kpis['weather_soil_moisture_mean'] = None
        for d in sorted(set(list(tmax_by_date.keys()) + list(precip_by_date.keys()))):
            daily_series.append({
                'date': d, 'tmax_c': round(tmax_by_date.get(d, -9999), 1),
                'tmin_c': round(tmin_by_date.get(d, -9999), 1),
                'precip_mm': round(precip_by_date.get(d, 0), 1),
                'et_mm': round(et_by_date.get(d, 0), 1),
            })
    except Exception as e:
        print(f"Warning: ERA5 failed: {e}")
        for k in ['weather_tmax_mean','weather_tmin_mean','weather_heat_days',
                   'weather_frost_days','weather_gdd_base10','weather_precip_total_mm',
                   'weather_rain_days','weather_et_total_mm','weather_water_balance_mm',
                   'weather_wind_mean_ms','weather_soil_moisture_mean']:
            weather_kpis.setdefault(k, None)
    return weather_kpis, daily_series


# ############################################################################
#  PERSISTIR IMÁGENES
# ############################################################################

def persist_images_to_db(job_id, images_base64, bounds=None):
    if not images_base64:
        return []
    api_base = os.environ.get('API_BASE_URL', 'https://muorbita-api-production.up.railway.app')
    try:
        payload = json.dumps({'job_id': job_id, 'images': images_base64, 'bounds': bounds}).encode()
        req = urllib.request.Request(f'{api_base}/api/images/store', data=payload,
            headers={'Content-Type': 'application/json'}, method='POST')
        result = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
        if result.get('success'):
            stored = [d['index_type'] for d in result.get('details', [])]
            print(f"✅ Persisted {len(stored)} images: {stored}")
            return stored
    except Exception as e:
        print(f"⚠️ Persist failed: {e}")
    return []


# ############################################################################
#  ANÁLISIS BIWEEKLY
# ############################################################################

def execute_biweekly_analysis(args):
    print("=" * 60)
    print("  Mu.Orbita GEE v5.7 — BIWEEKLY ANALYSIS")
    print("  VRA determinista + serie temporal 1 año")
    print("=" * 60)
    roi = create_roi(args.roi, args.buffer)
    job_id = args.job_id
    bounds = get_bounds(roi)

    # ── Colección principal: período del job (30 días) ──
    collection = get_sentinel2_collection(roi, args.start_date, args.end_date)
    count = collection.size().getInfo()
    if count == 0:
        return {"error": "No images found", "job_id": job_id, "analysis_type": "biweekly",
                "start_date": args.start_date, "end_date": args.end_date}

    indexed = collection.map(calculate_indices)
    composite_clipped = indexed.median().clip(roi)
    composite_viz = indexed.median()

    # ── Colección extendida: 1 año para serie temporal ──
    end_dt = datetime.strptime(args.end_date, '%Y-%m-%d')
    start_1y = (end_dt - timedelta(days=365)).strftime('%Y-%m-%d')
    print(f"  Time series period: {start_1y} → {args.end_date} (1 year)")
    collection_ts = get_sentinel2_collection(roi, start_1y, args.end_date)
    indexed_ts = collection_ts.map(calculate_indices)

    try:
        latest_date = ee.Date(collection.sort('system:time_start', False).first()
                              .get('system:time_start')).format('YYYY-MM-dd').getInfo()
    except:
        latest_date = args.end_date

    print("Computing statistics...")
    stats = composite_clipped.select(['NDVI','NDWI','EVI','NDCI']).reduceRegion(
        reducer=ee.Reducer.mean()
            .combine(ee.Reducer.percentile([10,50,90]), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=roi, scale=10, maxPixels=1e9).getInfo()

    area_ha = roi.area().divide(10000).getInfo()
    stress_ha = composite_clipped.select('NDVI').lt(0.35).multiply(ee.Image.pixelArea()).reduceRegion(
        ee.Reducer.sum(), roi, 10, maxPixels=1e9).getInfo().get('NDVI', 0) / 10000
    stress_pct = (stress_ha / area_ha * 100) if area_ha > 0 else 0

    hist_stats = indexed_ts.select('NDVI').mean().reduceRegion(
        ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        roi, 20, maxPixels=1e9).getInfo()
    ndvi_mean = stats.get('NDVI_mean', 0) or 0
    hist_mean = hist_stats.get('NDVI_mean', ndvi_mean) or ndvi_mean
    hist_std = hist_stats.get('NDVI_stdDev', 0.1) or 0.1
    z_score = (ndvi_mean - hist_mean) / hist_std if hist_std > 0 else 0

    print("Fetching ERA5...")
    weather_kpis, weather_daily = get_era5_weather(roi, args.start_date, args.end_date)

    try:
        lst_unclipped = get_modis_lst(roi, args.start_date, args.end_date)
        lst_clipped = lst_unclipped.clip(roi)
        lst_mean = lst_clipped.reduceRegion(ee.Reducer.mean(), roi, 1000, maxPixels=1e9).getInfo().get('LST_C_mean')
    except:
        lst_unclipped, lst_mean = None, None

    # ── Serie temporal: usa colección de 1 año ──
    print("Computing time series (1 year)...")
    time_series = []
    try:
        ts = indexed_ts.select(['NDVI','NDWI','EVI']).map(lambda img:
            ee.Feature(None, img.reduceRegion(
                ee.Reducer.mean(), roi, 20, maxPixels=1e9
            )).set('date', ee.Date(img.get('system:time_start')).format('YYYY-MM-dd')))
        for f in ts.toList(100).getInfo():
            p = f.get('properties', {})
            if p.get('date'):
                time_series.append({'date': p['date'],
                    'ndvi': round(p.get('NDVI_mean',0) or 0, 3),
                    'ndwi': round(p.get('NDWI_mean',0) or 0, 3),
                    'evi': round(p.get('EVI_mean',0) or 0, 3)})
        time_series.sort(key=lambda x: x['date'])
        print(f"  ✓ Time series: {len(time_series)} points over 1 year")
    except Exception as e:
        print(f"Warning: time series: {e}")

    kpis = {
        'job_id': job_id, 'crop_type': args.crop, 'analysis_type': 'biweekly',
        'start_date': args.start_date, 'end_date': args.end_date,
        'latest_image_date': latest_date, 'images_processed': count,
        'area_hectares': round(area_ha, 2),
        'ndvi_mean': round(stats.get('NDVI_mean',0) or 0, 3),
        'ndvi_p10': round(stats.get('NDVI_p10',0) or 0, 3),
        'ndvi_p50': round(stats.get('NDVI_p50',0) or 0, 3),
        'ndvi_p90': round(stats.get('NDVI_p90',0) or 0, 3),
        'ndvi_stddev': round(stats.get('NDVI_stdDev',0) or 0, 3),
        'ndvi_zscore': round(z_score, 2),
        'ndwi_mean': round(stats.get('NDWI_mean',0) or 0, 3),
        'ndwi_p10': round(stats.get('NDWI_p10',0) or 0, 3),
        'ndwi_p90': round(stats.get('NDWI_p90',0) or 0, 3),
        'evi_mean': round(stats.get('EVI_mean',0) or 0, 3),
        'ndci_mean': round(stats.get('NDCI_mean',0) or 0, 3),
        'stress_area_ha': round(stress_ha, 2),
        'stress_area_pct': round(stress_pct, 1),
        'lst_mean_c': round(lst_mean, 1) if lst_mean else None,
        'bounds_south': bounds['south'] if bounds else None,
        'bounds_west': bounds['west'] if bounds else None,
        'bounds_north': bounds['north'] if bounds else None,
        'bounds_east': bounds['east'] if bounds else None,
    }
    kpis.update(weather_kpis)

    print("\nGenerating all images...")
    all_images = generate_all_images(composite_viz, roi, bounds, kpis,
                                      index_list=['NDVI','NDWI'])
    stored = persist_images_to_db(job_id, all_images, bounds)

    return {
        'success': True, 'job_id': job_id, 'analysis_type': 'baseline',
        'kpis': kpis, 'vra_stats': vra_stats, 'bounds': bounds,
        'weather': weather_kpis, 'weather_daily': weather_daily,  # ← NUEVO
        'time_series': time_series,
        'images_stored': stored, 'images_available': list(all_images.keys()),
        'images_base64': {} if stored else all_images,
        'tasks': [], 'task_count': 0,
        'message': f'Baseline v5.8 complete. {len(stored)} images in DB.'
    }


# ############################################################################
#  ANÁLISIS BASELINE
# ############################################################################

def execute_analysis(args):
    print("=" * 60)
    print("  Mu.Orbita GEE v5.7 — BASELINE ANALYSIS")
    print("  VRA determinista + serie temporal 1 año")
    print("=" * 60)
    roi = create_roi(args.roi, args.buffer)
    job_id = args.job_id
    bounds = get_bounds(roi)

    # ── Colección principal: 6 meses (composite, mapas, VRA, KPIs) ──
    collection = get_sentinel2_collection(roi, args.start_date, args.end_date)
    count = collection.size().getInfo()
    if count == 0:
        return {"error": "No images found", "job_id": job_id,
                "start_date": args.start_date, "end_date": args.end_date}

    indexed = collection.map(calculate_indices)
    composite_clipped = indexed.median().clip(roi)
    composite_viz = indexed.median()

    # ── Colección extendida: 1 año para serie temporal del gráfico ──
    end_dt = datetime.strptime(args.end_date, '%Y-%m-%d')
    start_1y = (end_dt - timedelta(days=365)).strftime('%Y-%m-%d')
    print(f"  Composite period:    {args.start_date} → {args.end_date} (6 months)")
    print(f"  Time series period:  {start_1y} → {args.end_date} (1 year)")
    collection_ts = get_sentinel2_collection(roi, start_1y, args.end_date)
    indexed_ts = collection_ts.map(calculate_indices)

    try:
        latest_date = ee.Date(collection.sort('system:time_start', False).first()
                              .get('system:time_start')).format('YYYY-MM-dd').getInfo()
    except:
        latest_date = args.end_date

    print("Computing statistics...")
    stats = composite_clipped.select(['NDVI','NDWI','EVI','NDCI','SAVI','OSAVI']).reduceRegion(
        reducer=ee.Reducer.mean()
            .combine(ee.Reducer.percentile([10,50,90]), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True)
            .combine(ee.Reducer.count(), sharedInputs=True),
        geometry=roi, scale=10, maxPixels=1e9).getInfo()

    area_ha = roi.area().divide(10000).getInfo()
    stress_ha = composite_clipped.select('NDVI').lt(0.35).multiply(ee.Image.pixelArea()).reduceRegion(
        ee.Reducer.sum(), roi, 10, maxPixels=1e9).getInfo().get('NDVI', 0) / 10000
    stress_pct = (stress_ha / area_ha * 100) if area_ha > 0 else 0

    # Z-score histórico: usa colección de 1 año para más contexto
    hist_stats = indexed_ts.select('NDVI').mean().reduceRegion(
        ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        roi, 20, maxPixels=1e9).getInfo()
    ndvi_mean = stats.get('NDVI_mean', 0) or 0
    hist_mean = hist_stats.get('NDVI_mean', ndvi_mean) or ndvi_mean
    hist_std = hist_stats.get('NDVI_stdDev', 0.1) or 0.1
    z_score = (ndvi_mean - hist_mean) / hist_std if hist_std > 0 else 0

    try:
        lst_unclipped = get_modis_lst(roi, args.start_date, args.end_date)
        lst_clipped = lst_unclipped.clip(roi)
        lst_stats = lst_clipped.reduceRegion(
            ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True),
            roi, 1000, maxPixels=1e9).getInfo()
        lst_mean = lst_stats.get('LST_C_mean')
        lst_min = lst_stats.get('LST_C_min')
        lst_max = lst_stats.get('LST_C_max')
    except:
        lst_unclipped = None
        lst_mean = lst_min = lst_max = None


# ── ERA5 Weather (nuevo en baseline v5.8) ──
    print("Computing ERA5 weather...")
    try:
        weather_kpis, weather_daily = get_era5_weather(roi, args.start_date, args.end_date)
    except Exception as e:
        print(f"Warning: ERA5 weather failed: {e}")
        weather_kpis, weather_daily = {}, []

   
    # VRA: sobre composite de 6 meses (coherente con mapas)
    print("Computing VRA (deterministic score)...")
    vra_image, vra_stats = calculate_vra_zones(composite_clipped, roi)

    kpis = {
        'job_id': job_id, 'crop_type': args.crop, 'analysis_type': args.analysis_type,
        'start_date': args.start_date, 'end_date': args.end_date,
        'latest_image_date': latest_date, 'images_processed': count,
        'area_hectares': round(area_ha, 2),
        'ndvi_mean': round(stats.get('NDVI_mean',0) or 0, 3),
        'ndvi_p10': round(stats.get('NDVI_p10',0) or 0, 3),
        'ndvi_p50': round(stats.get('NDVI_p50',0) or 0, 3),
        'ndvi_p90': round(stats.get('NDVI_p90',0) or 0, 3),
        'ndvi_stddev': round(stats.get('NDVI_stdDev',0) or 0, 3),
        'ndvi_zscore': round(z_score, 2),
        'ndwi_mean': round(stats.get('NDWI_mean',0) or 0, 3),
        'ndwi_p10': round(stats.get('NDWI_p10',0) or 0, 3),
        'ndwi_p90': round(stats.get('NDWI_p90',0) or 0, 3),
        'evi_mean': round(stats.get('EVI_mean',0) or 0, 3),
        'evi_p10': round(stats.get('EVI_p10',0) or 0, 3),
        'evi_p90': round(stats.get('EVI_p90',0) or 0, 3),
        'ndci_mean': round(stats.get('NDCI_mean',0) or 0, 3),
        'savi_mean': round(stats.get('SAVI_mean',0) or 0, 3),
        'osavi_mean': round(stats.get('OSAVI_mean',0) or 0, 3),
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
   kpis.update(weather_kpis)

    print("\nGenerating all images...")
    all_images = generate_all_images(
        composite_viz, roi, bounds, kpis,
        index_list=['NDVI','NDWI','EVI','NDCI','SAVI'],
        vra_image=vra_image, lst_unclipped=lst_unclipped
    )

    # ── Serie temporal: usa colección de 1 año ──
    print("Computing time series (1 year)...")
    time_series = []
    try:
        ts = indexed_ts.select(['NDVI','NDWI','EVI']).map(lambda img:
            ee.Feature(None, img.reduceRegion(
                reducer=ee.Reducer.mean().combine(ee.Reducer.percentile([10,90]), sharedInputs=True),
                geometry=roi, scale=20, maxPixels=1e9
            )).set('date', ee.Date(img.get('system:time_start')).format('YYYY-MM-dd')))
        for f in ts.toList(100).getInfo():
            p = f.get('properties', {})
            if p.get('date'):
                time_series.append({'date': p['date'],
                    'ndvi': round(p.get('NDVI_mean',0) or 0, 3),
                    'ndwi': round(p.get('NDWI_mean',0) or 0, 3),
                    'evi': round(p.get('EVI_mean',0) or 0, 3)})
        time_series.sort(key=lambda x: x['date'])
        print(f"  ✓ Time series: {len(time_series)} points over 1 year")
    except Exception as e:
        print(f"Warning: time series: {e}")

    stored = persist_images_to_db(job_id, all_images, bounds)

    return {
        'success': True, 'job_id': job_id, 'analysis_type': 'baseline',
        'kpis': kpis, 'vra_stats': vra_stats, 'bounds': bounds,
        'weather': weather_kpis, 'weather_daily': weather_daily,  # ← NUEVO
        'time_series': time_series,
        'images_stored': stored, 'images_available': list(all_images.keys()),
        'images_base64': {} if stored else all_images,
        'tasks': [], 'task_count': 0,
        'message': f'Baseline v5.8 complete. {len(stored)} images in DB.'
    }


# ############################################################################
#  LEGACY + MAIN
# ############################################################################

def check_status(args):
    return {'job_id': args.job_id, 'all_complete': True, 'progress_pct': 100, 'message': 'v5.7: Sync.'}
def download_results(args):
    return {'job_id': args.job_id, 'status': 'ready', 'download_ready': True, 'message': 'v5.7: In response.'}
def start_tasks(args):
    return {'job_id': args.job_id, 'started': 0, 'message': 'v5.7: No tasks.'}

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
