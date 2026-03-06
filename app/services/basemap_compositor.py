"""
Mu.Orbita Basemap Compositor v1.0
==================================
Descarga tiles de Esri World Imagery y compone el índice GEE encima.
Resultado: aspecto idéntico a GEE Code Editor / QGIS.

Dependencias: PIL (Pillow), urllib (stdlib)
NO requiere: contextily, mercantile, rasterio

Uso desde gee_automation.py:
    from basemap_compositor import create_cartographic_png
    
    b64 = create_cartographic_png(
        index_b64=get_leaflet_overlay_png(...),  # índice clipado a parcela
        bounds={'south': 37.3, 'north': 37.35, 'west': -4.1, 'east': -4.05},
        roi_geojson=roi.getInfo(),               # para dibujar contorno
        index_name='NDVI',
        mean_value=0.62
    )
"""

import io
import math
import base64
import urllib.request
from typing import Dict, List, Tuple, Optional


# ============================================================================
# TILE MATH
# ============================================================================

def _lat_lon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """Convierte lat/lon a coordenadas de tile (x, y) para el zoom dado."""
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _tile_to_lat_lon(x: int, y: int, zoom: int) -> Tuple[float, float]:
    """Convierte tile (x, y) a lat/lon (esquina noroeste del tile)."""
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_rad)
    return lat, lon


def _get_optimal_zoom(bounds: Dict, target_width: int = 768) -> int:
    """Calcula el zoom óptimo para que el área quepa bien en el PNG."""
    lat_span = bounds['north'] - bounds['south']
    lon_span = bounds['east'] - bounds['west']
    
    # Queremos ~3-6 tiles de ancho para buena resolución sin exceso
    for z in range(18, 8, -1):
        x_min, _ = _lat_lon_to_tile(bounds['south'], bounds['west'], z)
        x_max, _ = _lat_lon_to_tile(bounds['south'], bounds['east'], z)
        tiles_x = x_max - x_min + 1
        if tiles_x <= 8:  # máximo 8 tiles de ancho
            return z
    return 14  # fallback


# ============================================================================
# TILE FETCHING
# ============================================================================

ESRI_TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"

def _fetch_tile(x: int, y: int, z: int) -> Optional[bytes]:
    """Descarga un tile de Esri World Imagery."""
    url = ESRI_TILE_URL.format(z=z, y=y, x=x)
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'MuOrbita/5.5')
        req.add_header('Referer', 'https://muorbita.com')
        response = urllib.request.urlopen(req, timeout=15)
        return response.read()
    except Exception as e:
        print(f"  Warning: tile fetch failed ({z}/{y}/{x}): {e}")
        return None


def _fetch_basemap(bounds: Dict, zoom: int, padding_tiles: int = 1):
    """
    Descarga y stitchea todos los tiles necesarios para cubrir los bounds.
    
    Returns:
        (PIL.Image, geo_bounds): imagen stitcheada y sus bounds geográficos reales
    """
    from PIL import Image as PILImage
    
    # Calcular rango de tiles
    x_min, y_min = _lat_lon_to_tile(bounds['north'], bounds['west'], zoom)
    x_max, y_max = _lat_lon_to_tile(bounds['south'], bounds['east'], zoom)
    
    # Añadir padding
    x_min -= padding_tiles
    x_max += padding_tiles
    y_min -= padding_tiles
    y_max += padding_tiles
    
    tiles_x = x_max - x_min + 1
    tiles_y = y_max - y_min + 1
    
    print(f"  Fetching {tiles_x}x{tiles_y} = {tiles_x * tiles_y} tiles at zoom {zoom}...")
    
    # Crear imagen final
    tile_size = 256
    canvas = PILImage.new('RGB', (tiles_x * tile_size, tiles_y * tile_size), (180, 176, 168))
    
    for ty in range(y_min, y_max + 1):
        for tx in range(x_min, x_max + 1):
            tile_bytes = _fetch_tile(tx, ty, zoom)
            if tile_bytes:
                try:
                    tile_img = PILImage.open(io.BytesIO(tile_bytes))
                    px = (tx - x_min) * tile_size
                    py = (ty - y_min) * tile_size
                    canvas.paste(tile_img, (px, py))
                except Exception:
                    pass
    
    # Bounds geográficos reales de la imagen stitcheada
    nw_lat, nw_lon = _tile_to_lat_lon(x_min, y_min, zoom)
    se_lat, se_lon = _tile_to_lat_lon(x_max + 1, y_max + 1, zoom)
    
    geo_bounds = {
        'north': nw_lat, 'south': se_lat,
        'west': nw_lon, 'east': se_lon
    }
    
    print(f"  Basemap: {canvas.size[0]}x{canvas.size[1]} px")
    return canvas, geo_bounds


# ============================================================================
# COMPOSICIÓN
# ============================================================================

def _geo_to_pixel(lat: float, lon: float, geo_bounds: Dict, 
                  img_w: int, img_h: int) -> Tuple[int, int]:
    """Convierte coordenadas geográficas a píxeles en la imagen."""
    x = int((lon - geo_bounds['west']) / (geo_bounds['east'] - geo_bounds['west']) * img_w)
    y = int((geo_bounds['north'] - lat) / (geo_bounds['north'] - geo_bounds['south']) * img_h)
    return max(0, min(x, img_w - 1)), max(0, min(y, img_h - 1))


def _draw_parcel_boundary(img, roi_coords: List, geo_bounds: Dict,
                          color=(255, 255, 255), width=3, shadow=True):
    """Dibuja el contorno de la parcela sobre la imagen."""
    from PIL import ImageDraw
    
    draw = ImageDraw.Draw(img)
    w, h = img.size
    
    # Extraer coordenadas del polígono exterior
    if isinstance(roi_coords, dict):
        coords = roi_coords.get('coordinates', [[]])[0]
    elif isinstance(roi_coords, list):
        # Podría ser [[[lon,lat],...]] o [[lon,lat],...]
        if roi_coords and isinstance(roi_coords[0], list) and isinstance(roi_coords[0][0], list):
            coords = roi_coords[0]
        else:
            coords = roi_coords
    else:
        return
    
    if not coords:
        return
    
    # Convertir a píxeles
    points = []
    for c in coords:
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            px, py = _geo_to_pixel(c[1], c[0], geo_bounds, w, h)
            points.append((px, py))
    
    if len(points) < 3:
        return
    
    # Sombra negra debajo
    if shadow:
        shadow_points = [(p[0] + 2, p[1] + 2) for p in points]
        draw.polygon(shadow_points, outline=(0, 0, 0), fill=None)
        for i in range(len(shadow_points) - 1):
            draw.line([shadow_points[i], shadow_points[i+1]], fill=(0, 0, 0), width=width + 2)
    
    # Contorno principal
    for i in range(len(points) - 1):
        draw.line([points[i], points[i+1]], fill=color, width=width)
    # Cerrar polígono
    if points[0] != points[-1]:
        draw.line([points[-1], points[0]], fill=color, width=width)


def _overlay_index(basemap, index_b64: str, parcel_bounds: Dict, 
                   geo_bounds: Dict, opacity: float = 0.65):
    """
    Superpone el PNG del índice (clipado a parcela) sobre el basemap.
    El índice solo tiene píxeles dentro de la parcela — el resto es transparente/negro.
    """
    from PIL import Image as PILImage
    
    # Decodificar índice
    index_bytes = base64.b64decode(index_b64)
    index_img = PILImage.open(io.BytesIO(index_bytes)).convert('RGBA')
    
    bw, bh = basemap.size
    
    # Calcular posición del índice sobre el basemap
    # El índice cubre parcel_bounds (roi.bounds())
    x1, y1 = _geo_to_pixel(parcel_bounds['north'], parcel_bounds['west'], geo_bounds, bw, bh)
    x2, y2 = _geo_to_pixel(parcel_bounds['south'], parcel_bounds['east'], geo_bounds, bw, bh)
    
    target_w = max(x2 - x1, 1)
    target_h = max(y2 - y1, 1)
    
    # Resize el índice para que encaje
    index_resized = index_img.resize((target_w, target_h), PILImage.LANCZOS)
    
    # Crear máscara: píxeles no-transparentes del índice con opacidad aplicada
    # Los píxeles negros/transparentes (fuera de la parcela en el clip) se ignoran
    r, g, b, a = index_resized.split()
    
    # Aplicar opacidad a la máscara alpha
    from PIL import ImageEnhance
    alpha_adjusted = a.point(lambda p: int(p * opacity) if p > 10 else 0)
    index_resized.putalpha(alpha_adjusted)
    
    # Componer sobre basemap
    basemap_rgba = basemap.convert('RGBA')
    basemap_rgba.paste(index_resized, (x1, y1), index_resized)
    
    return basemap_rgba.convert('RGB')


def _dim_exterior(basemap, parcel_bounds: Dict, geo_bounds: Dict, 
                  dim_factor: float = 0.55):
    """
    Atenúa ligeramente el exterior de la parcela para que la parcela destaque.
    Crea un overlay semi-transparente blanco fuera de la parcela.
    """
    from PIL import Image as PILImage, ImageDraw
    
    bw, bh = basemap.size
    
    # Crear overlay blanco semi-transparente para TODA la imagen
    overlay = PILImage.new('RGBA', (bw, bh), (255, 255, 255, int(255 * (1 - dim_factor))))
    
    # Recortar un hueco donde está la parcela (dejar el basemap al 100%)
    # Simplificación: usamos un rectángulo por los bounds
    x1, y1 = _geo_to_pixel(parcel_bounds['north'], parcel_bounds['west'], geo_bounds, bw, bh)
    x2, y2 = _geo_to_pixel(parcel_bounds['south'], parcel_bounds['east'], geo_bounds, bw, bh)
    
    draw = ImageDraw.Draw(overlay)
    draw.rectangle([x1, y1, x2, y2], fill=(255, 255, 255, 0))  # Transparente en la parcela
    
    result = basemap.convert('RGBA')
    result = PILImage.alpha_composite(result, overlay)
    return result.convert('RGB')


# ============================================================================
# LEYENDA
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


def _add_legend(img, index_name: str, mean_value: float = None):
    """Añade leyenda profesional debajo de la imagen."""
    from PIL import Image as PILImage, ImageDraw, ImageFont
    
    viz = VIZ_PALETTES.get(index_name)
    if not viz:
        return img
    
    legend_h, pad, bar_h = 90, 20, 18
    bar_w = min(350, img.width - 2 * pad)
    
    bg_color = (249, 247, 242)
    new_img = PILImage.new('RGB', (img.width, img.height + legend_h), bg_color)
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
    accent, dark, muted = (139, 69, 19), (51, 51, 51), (136, 136, 136)
    
    label = viz.get('label', index_name)
    draw.text((pad, y0), label, fill=accent, font=ft)
    if mean_value is not None:
        try:
            tw = draw.textbbox((0, 0), label, font=ft)[2]
        except AttributeError:
            tw = len(label) * 8
        draw.text((pad + tw + 20, y0 + 1), f"Media: {mean_value:.2f}", fill=dark, font=fv)
    
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
    
    unit = viz.get('unit', '')
    draw.text((bar_x, bar_y + bar_h + 3), f"{viz['min']}{unit}", fill=muted, font=fs)
    mx_txt = f"{viz['max']}{unit}"
    try:
        mx_w = draw.textbbox((0, 0), mx_txt, font=fs)[2]
    except AttributeError:
        mx_w = len(mx_txt) * 6
    draw.text((bar_x + bar_w - mx_w, bar_y + bar_h + 3), mx_txt, fill=muted, font=fs)
    
    if mean_value is not None:
        rng = viz['max'] - viz['min']
        if rng > 0:
            t = max(0, min(1, (mean_value - viz['min']) / rng))
            mx = bar_x + int(t * bar_w)
            draw.polygon([(mx, bar_y - 2), (mx - 6, bar_y - 8), (mx + 6, bar_y - 8)], fill=dark)
    
    return new_img


# ============================================================================
# CROP & RESIZE FINAL
# ============================================================================

def _crop_to_parcel(img, parcel_bounds: Dict, geo_bounds: Dict, 
                    padding_px: int = 80, max_dim: int = 768):
    """Recorta la imagen stitcheada al área de la parcela + padding."""
    from PIL import Image as PILImage
    
    w, h = img.size
    x1, y1 = _geo_to_pixel(parcel_bounds['north'], parcel_bounds['west'], geo_bounds, w, h)
    x2, y2 = _geo_to_pixel(parcel_bounds['south'], parcel_bounds['east'], geo_bounds, w, h)
    
    # Añadir padding
    x1 = max(0, x1 - padding_px)
    y1 = max(0, y1 - padding_px)
    x2 = min(w, x2 + padding_px)
    y2 = min(h, y2 + padding_px)
    
    cropped = img.crop((x1, y1, x2, y2))
    
    # Resize si es demasiado grande
    cw, ch = cropped.size
    if max(cw, ch) > max_dim:
        ratio = max_dim / max(cw, ch)
        cropped = cropped.resize((int(cw * ratio), int(ch * ratio)), PILImage.LANCZOS)
    
    return cropped


# ============================================================================
# PUBLIC API
# ============================================================================

def create_cartographic_png(
    index_b64: str,
    bounds: Dict,
    roi_coords,
    index_name: str = 'NDVI',
    mean_value: float = None,
    opacity: float = 0.65,
    dim_exterior: float = 0.55,
    max_dim: int = 768,
    boundary_color: Tuple = (255, 255, 255),
    boundary_width: int = 3
) -> Optional[str]:
    """
    Crea un PNG cartográfico profesional: basemap Esri + índice + contorno.
    
    Args:
        index_b64:      PNG base64 del índice clipado a parcela (de get_leaflet_overlay_png)
        bounds:         {'south', 'north', 'east', 'west'} de la parcela
        roi_coords:     Coordenadas del polígono [[lon,lat], ...] para el contorno
        index_name:     'NDVI', 'NDWI', etc. (para leyenda)
        mean_value:     Valor medio del índice (para leyenda)
        opacity:        Opacidad del índice sobre el basemap (0.65 = bueno)
        dim_exterior:   Brillo del exterior (0.55 = ligeramente atenuado)
        max_dim:        Dimensión máxima del PNG final
        boundary_color: Color RGB del contorno
        boundary_width: Grosor del contorno en px
    
    Returns:
        str: PNG base64 del resultado, o None si falla
    """
    try:
        print(f"  [compositor] Creating cartographic {index_name}...")
        
        # 1. Determinar zoom óptimo
        zoom = _get_optimal_zoom(bounds, max_dim)
        print(f"  [compositor] Zoom: {zoom}")
        
        # 2. Descargar basemap tiles
        basemap, geo_bounds = _fetch_basemap(bounds, zoom, padding_tiles=1)
        
        # 3. Atenuar exterior
        basemap = _dim_exterior(basemap, bounds, geo_bounds, dim_exterior)
        
        # 4. Superponer índice
        basemap = _overlay_index(basemap, index_b64, bounds, geo_bounds, opacity)
        
        # 5. Dibujar contorno de parcela
        _draw_parcel_boundary(basemap, roi_coords, geo_bounds, 
                             color=boundary_color, width=boundary_width)
        
        # 6. Recortar al área de interés
        result = _crop_to_parcel(basemap, bounds, geo_bounds, 
                                padding_px=80, max_dim=max_dim)
        
        # 7. Añadir leyenda
        result = _add_legend(result, index_name, mean_value)
        
        # 8. Exportar a base64
        buf = io.BytesIO()
        result.save(buf, format='PNG', optimize=True)
        buf.seek(0)
        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        
        print(f"  [compositor] {index_name}: {result.size[0]}x{result.size[1]} px, "
              f"{len(b64) // 1024} KB")
        return b64
        
    except Exception as e:
        print(f"  [compositor] Failed for {index_name}: {e}")
        import traceback
        traceback.print_exc()
        return None


def create_satellite_only_png(
    bounds: Dict,
    roi_coords,
    max_dim: int = 768,
    dim_exterior: float = 0.55,
    boundary_color: Tuple = (255, 255, 255),
    boundary_width: int = 3
) -> Optional[str]:
    """
    PNG satelital puro (sin overlay de índice). Para la imagen RGB del PDF.
    """
    try:
        print(f"  [compositor] Creating satellite-only RGB...")
        
        zoom = _get_optimal_zoom(bounds, max_dim)
        basemap, geo_bounds = _fetch_basemap(bounds, zoom, padding_tiles=1)
        basemap = _dim_exterior(basemap, bounds, geo_bounds, dim_exterior)
        _draw_parcel_boundary(basemap, roi_coords, geo_bounds,
                             color=boundary_color, width=boundary_width)
        result = _crop_to_parcel(basemap, bounds, geo_bounds,
                                padding_px=80, max_dim=max_dim)
        
        buf = io.BytesIO()
        result.save(buf, format='PNG', optimize=True)
        buf.seek(0)
        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        print(f"  [compositor] RGB: {result.size[0]}x{result.size[1]} px")
        return b64
        
    except Exception as e:
        print(f"  [compositor] RGB failed: {e}")
        return None
