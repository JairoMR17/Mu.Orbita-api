#!/usr/bin/env python3
"""
Mu.Orbita — GeoTIFF Satellite Imagery Converter
================================================
Convierte los GeoTIFFs coloreados exportados por GEE a PNGs
listos para web/dashboard y para insertar en informes PDF.

USO DESDE n8n (Execute Command node):
    python geotiff_to_png.py --job-id JOB_123 --input-dir /tmp/geotiffs --output-dir /tmp/pngs

USO DIRECTO CON GOOGLE DRIVE:
    python geotiff_to_png.py --job-id JOB_123 --drive-folder MuOrbita_Outputs --output-dir /tmp/pngs

SALIDA:
    - PNG_NDVI.png, PNG_NDWI.png, etc. (web: fondo transparente, georreferenciado)
    - PNG_NDVI_report.png (PDF: con leyenda, título, escala)
    - metadata.json con bounds para Leaflet
"""

import os
import sys
import json
import argparse
import numpy as np
from pathlib import Path
from io import BytesIO
import base64

try:
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.plot import reshape_as_image
    from PIL import Image, ImageDraw, ImageFont
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False
    print("WARNING: rasterio not available, using PIL-only mode")
    from PIL import Image, ImageDraw

# ============================================================================
# PALETAS Y METADATOS DE CAPAS
# ============================================================================

LAYER_METADATA = {
    'PNG_NDVI': {
        'name': 'NDVI — Vigor Vegetativo',
        'unit': '',
        'min': 0.0,
        'max': 0.8,
        'palette_labels': ['0.0 (Suelo/Estrés)', '0.2', '0.4 (Moderado)', '0.6 (Alto vigor)', '0.8+'],
        'palette_colors': [(139,0,0), (255,0,0), (255,255,0), (50,205,50), (0,100,0)],
        'description': 'Índice de vegetación de diferencia normalizada'
    },
    'PNG_NDWI': {
        'name': 'NDWI — Estado Hídrico',
        'unit': '',
        'min': -0.3,
        'max': 0.4,
        'palette_labels': ['-0.3 (Seco)', '-0.1', '0.1', '0.3 (Húmedo)', '0.4+'],
        'palette_colors': [(139,69,19), (244,164,96), (224,255,255), (70,130,180), (0,0,139)],
        'description': 'Índice de agua de diferencia normalizada'
    },
    'PNG_EVI': {
        'name': 'EVI — Productividad',
        'unit': '',
        'min': 0.0,
        'max': 0.6,
        'palette_labels': ['0.0', '0.15', '0.3 (Media)', '0.45', '0.6+'],
        'palette_colors': [(139,0,0), (240,128,128), (255,255,224), (127,255,0), (0,100,0)],
        'description': 'Índice de vegetación mejorado (productividad)'
    },
    'PNG_NDCI': {
        'name': 'NDCI — Clorofila',
        'unit': '',
        'min': -0.2,
        'max': 0.6,
        'palette_labels': ['-0.2', '0.0', '0.2', '0.4', '0.6+'],
        'palette_colors': [(139,0,0), (255,99,71), (255,165,0), (50,205,50), (0,100,0)],
        'description': 'Índice de contenido en clorofila'
    },
    'PNG_SAVI': {
        'name': 'SAVI — Vigor Ajustado',
        'unit': '',
        'min': 0.0,
        'max': 0.8,
        'palette_labels': ['0.0', '0.2', '0.4', '0.6', '0.8+'],
        'palette_colors': [(139,0,0), (255,0,0), (255,255,0), (50,205,50), (0,100,0)],
        'description': 'NDVI ajustado por reflectancia del suelo'
    },
    'PNG_VRA': {
        'name': 'Zonas VRA — Manejo Variable',
        'unit': '',
        'min': 0,
        'max': 2,
        'palette_labels': ['Bajo vigor (Dosis alta)', 'Vigor medio (Dosis media)', 'Alto vigor (Dosis baja)'],
        'palette_colors': [(231,76,60), (241,196,15), (39,174,96)],
        'description': 'Zonificación para aplicación a tasa variable'
    },
    'PNG_LST': {
        'name': 'LST — Temperatura Superficial',
        'unit': '°C',
        'min': 15,
        'max': 45,
        'palette_labels': ['15°C', '22°C', '30°C', '37°C', '45°C'],
        'palette_colors': [(0,0,255), (0,255,255), (0,255,0), (255,255,0), (255,0,0)],
        'description': 'Temperatura superficial del suelo (MODIS)'
    }
}

# ============================================================================
# CONVERSIÓN PRINCIPAL
# ============================================================================

def geotiff_to_png_web(input_path, output_path, target_size=(1024, 1024)):
    """
    Convierte GeoTIFF coloreado a PNG transparente para web/Leaflet.

    El GeoTIFF ya viene coloreado desde GEE (visualize() aplicado),
    por lo que solo necesitamos extraer RGB y añadir transparencia.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        print(f"ERROR: File not found: {input_path}")
        return False

    try:
        if HAS_RASTERIO:
            with rasterio.open(input_path) as src:
                count = src.count

                if count >= 3:
                    r = src.read(1)
                    g = src.read(2)
                    b = src.read(3)
                elif count == 1:
                    band = src.read(1)
                    r = g = b = band
                else:
                    r = src.read(1)
                    g = src.read(1) if count < 2 else src.read(2)
                    b = src.read(1) if count < 3 else src.read(3)

                if count == 4:
                    alpha = src.read(4)
                else:
                    nodata_mask = (r == 0) & (g == 0) & (b == 0)
                    alpha = np.where(nodata_mask, 0, 255).astype(np.uint8)

                def normalize_band(arr):
                    if arr.dtype in [np.float32, np.float64]:
                        arr_min, arr_max = arr.min(), arr.max()
                        if arr_max > arr_min:
                            arr = ((arr - arr_min) / (arr_max - arr_min) * 255).astype(np.uint8)
                        else:
                            arr = np.zeros_like(arr, dtype=np.uint8)
                    return arr.astype(np.uint8)

                r = normalize_band(r)
                g = normalize_band(g)
                b = normalize_band(b)

                rgba = np.stack([r, g, b, alpha], axis=-1)
                img = Image.fromarray(rgba, 'RGBA')

                bounds = {
                    'west':  src.bounds.left,
                    'south': src.bounds.bottom,
                    'east':  src.bounds.right,
                    'north': src.bounds.top,
                    'crs':   str(src.crs)
                }
        else:
            img = Image.open(input_path)
            if img.mode == 'RGB':
                r, g, b = img.split()
                r_arr = np.array(r)
                g_arr = np.array(g)
                b_arr = np.array(b)
                nodata_mask = (r_arr == 0) & (g_arr == 0) & (b_arr == 0)
                alpha_arr = np.where(nodata_mask, 0, 255).astype(np.uint8)
                alpha = Image.fromarray(alpha_arr)
                img = Image.merge('RGBA', (r, g, b, alpha))
            bounds = None

        w, h = img.size
        if w > target_size[0] or h > target_size[1]:
            img.thumbnail(target_size, Image.LANCZOS)

        img.save(output_path, 'PNG', optimize=True)
        print(f"✓ Web PNG: {output_path} ({img.size[0]}x{img.size[1]}px)")

        return bounds if HAS_RASTERIO else True

    except Exception as e:
        print(f"ERROR converting {input_path}: {e}")
        import traceback
        traceback.print_exc()
        return False


def geotiff_to_png_report(input_path, output_path, layer_key, metadata=None,
                           title=None, client_name=None, date_str=None):
    """
    Convierte GeoTIFF a PNG de alta calidad para insertar en PDF.
    Añade: título, leyenda, metadatos del cliente, escala visual.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        print(f"ERROR: File not found: {input_path}")
        return False

    layer_meta = LAYER_METADATA.get(layer_key, {
        'name': layer_key,
        'palette_colors': [(0,0,255), (255,255,0), (255,0,0)],
        'palette_labels': ['Bajo', 'Medio', 'Alto'],
        'description': ''
    })

    try:
        if HAS_RASTERIO:
            with rasterio.open(input_path) as src:
                count = src.count
                if count >= 3:
                    r = src.read(1).astype(np.uint8)
                    g = src.read(2).astype(np.uint8)
                    b = src.read(3).astype(np.uint8)
                    rgb = np.stack([r, g, b], axis=-1)
                    base_img = Image.fromarray(rgb, 'RGB')
                else:
                    band = src.read(1)
                    band_norm = ((band - band.min()) / (band.max() - band.min() + 1e-10) * 255).astype(np.uint8)
                    rgb = np.stack([band_norm, band_norm, band_norm], axis=-1)
                    base_img = Image.fromarray(rgb, 'RGB')
        else:
            base_img = Image.open(input_path).convert('RGB')

        MAP_W, MAP_H = 900, 700
        LEGEND_H = 120
        MARGIN = 30
        HEADER_H = 70

        total_w = MAP_W + 2 * MARGIN
        total_h = HEADER_H + MAP_H + LEGEND_H + 2 * MARGIN

        canvas = Image.new('RGB', (total_w, total_h), '#F8F6F1')
        draw = ImageDraw.Draw(canvas)

        draw.rectangle([0, 0, total_w, HEADER_H], fill='#3E2B1D')

        layer_name = title or layer_meta.get('name', layer_key)
        draw.text((MARGIN, 15), "Mu.Orbita", fill='#9E7E46', font=None)
        draw.text((MARGIN, 38), layer_name, fill='white', font=None)

        if client_name:
            draw.text((total_w - 200, 15), f"Cliente: {client_name}", fill='#DBCDBA', font=None)
        if date_str:
            draw.text((total_w - 200, 38), f"Análisis: {date_str}", fill='#DBCDBA', font=None)

        map_img = base_img.copy()
        map_img = map_img.resize((MAP_W, MAP_H), Image.LANCZOS)

        map_x, map_y = MARGIN, HEADER_H + MARGIN // 2
        draw.rectangle([map_x - 2, map_y - 2, map_x + MAP_W + 2, map_y + MAP_H + 2],
                       outline='#DBCDBA', width=2)
        canvas.paste(map_img, (map_x, map_y))

        legend_y = HEADER_H + MAP_H + MARGIN

        draw.rectangle([MARGIN, legend_y, total_w - MARGIN, legend_y + LEGEND_H - 10],
                       fill='#F0EBE0', outline='#DBCDBA', width=1)

        draw.text((MARGIN + 10, legend_y + 8), "LEYENDA", fill='#7A6555', font=None)

        palette_colors = layer_meta.get('palette_colors', [(128,128,128)])
        palette_labels = layer_meta.get('palette_labels', [''])

        if palette_colors:
            n_colors = len(palette_colors)
            legend_bar_x = MARGIN + 10
            legend_bar_y = legend_y + 28
            legend_bar_w = MAP_W - 20
            legend_bar_h = 25

            bar_step = legend_bar_w // n_colors
            for i, color in enumerate(palette_colors):
                x0 = legend_bar_x + i * bar_step
                x1 = legend_bar_x + (i + 1) * bar_step
                draw.rectangle([x0, legend_bar_y, x1, legend_bar_y + legend_bar_h], fill=color)

            label_y = legend_bar_y + legend_bar_h + 5
            for i, label in enumerate(palette_labels):
                if i < n_colors:
                    label_x = legend_bar_x + i * bar_step
                    draw.text((label_x, label_y), str(label), fill='#3E2B1D', font=None)

        desc = layer_meta.get('description', '')
        if desc:
            draw.text((MARGIN + 10, legend_y + LEGEND_H - 25), f"  {desc}", fill='#7A6555', font=None)

        draw.text((total_w - 120, total_h - 20), "© Mu.Orbita 2025", fill='#DBCDBA', font=None)

        canvas.save(output_path, 'PNG', dpi=(150, 150))
        print(f"✓ Report PNG: {output_path} ({canvas.size[0]}x{canvas.size[1]}px)")
        return True

    except Exception as e:
        print(f"ERROR generating report PNG for {input_path}: {e}")
        import traceback
        traceback.print_exc()
        return False


def convert_all_geotiffs(input_dir, output_dir, job_id, client_name=None,
                         date_str=None, layers=None):
    """
    Convierte todos los GeoTIFFs de un job a PNGs web y PDF.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if layers is None:
        layers = list(LAYER_METADATA.keys())

    results = {
        'job_id': job_id,
        'web_pngs': {},
        'report_pngs': {},
        'bounds': None,
        'errors': []
    }

    for layer_key in layers:
        tiff_candidates = [
            input_dir / f"{layer_key}.tif",
            input_dir / f"{layer_key}.tiff",
            input_dir / f"{job_id}_{layer_key}.tif",
        ]

        tiff_path = None
        for candidate in tiff_candidates:
            if candidate.exists():
                tiff_path = candidate
                break

        if tiff_path is None:
            print(f"  SKIP: {layer_key} — no GeoTIFF found in {input_dir}")
            continue

        web_png_path = output_dir / f"{layer_key}.png"
        bounds = geotiff_to_png_web(tiff_path, web_png_path)

        if bounds is not False:
            results['web_pngs'][layer_key] = str(web_png_path)
            if isinstance(bounds, dict) and results['bounds'] is None:
                results['bounds'] = bounds
        else:
            results['errors'].append(f"Failed web PNG: {layer_key}")

        report_png_path = output_dir / f"{layer_key}_report.png"
        success = geotiff_to_png_report(
            tiff_path, report_png_path,
            layer_key=layer_key,
            client_name=client_name,
            date_str=date_str
        )

        if success:
            results['report_pngs'][layer_key] = str(report_png_path)
        else:
            results['errors'].append(f"Failed report PNG: {layer_key}")

    return results


def png_to_base64(png_path):
    """Convierte PNG a base64 para embeber en HTML/PDF directamente."""
    with open(png_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


# ============================================================================
# INTEGRACIÓN CON GOOGLE DRIVE
# ============================================================================

def download_from_drive(job_id, drive_folder, output_dir, credentials_json=None):
    """
    Descarga GeoTIFFs de Google Drive para el job_id dado.
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        from google.oauth2 import service_account
        import io

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if credentials_json:
            if isinstance(credentials_json, str):
                if os.path.exists(credentials_json):
                    with open(credentials_json) as f:
                        creds_data = json.load(f)
                else:
                    creds_data = json.loads(credentials_json)
            else:
                creds_data = credentials_json

            creds = service_account.Credentials.from_service_account_info(
                creds_data,
                scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
        else:
            import google.auth
            creds, _ = google.auth.default(
                scopes=['https://www.googleapis.com/auth/drive.readonly']
            )

        service = build('drive', 'v3', credentials=creds)

        folder_query = f"name='{job_id}' and mimeType='application/vnd.google-apps.folder'"
        folder_results = service.files().list(q=folder_query, fields='files(id,name)').execute()
        folders = folder_results.get('files', [])

        downloaded = []

        if folders:
            job_folder_id = folders[0]['id']

            web_query = f"name='WEB' and '{job_folder_id}' in parents and mimeType='application/vnd.google-apps.folder'"
            web_results = service.files().list(q=web_query, fields='files(id,name)').execute()
            web_folders = web_results.get('files', [])

            if web_folders:
                web_folder_id = web_folders[0]['id']

                files_query = f"'{web_folder_id}' in parents and name contains 'PNG_'"
                files_results = service.files().list(
                    q=files_query,
                    fields='files(id,name,size)'
                ).execute()

                for file_info in files_results.get('files', []):
                    file_name = file_info['name']
                    file_id   = file_info['id']
                    output_path = output_dir / file_name

                    print(f"  Downloading: {file_name}...")
                    request = service.files().get_media(fileId=file_id)
                    fh = io.BytesIO()
                    downloader = MediaIoBaseDownload(fh, request)

                    done = False
                    while not done:
                        status, done = downloader.next_chunk()

                    with open(output_path, 'wb') as f:
                        f.write(fh.getvalue())

                    downloaded.append(str(output_path))
                    print(f"  ✓ Downloaded: {output_path}")

        return downloaded

    except Exception as e:
        print(f"Drive download error: {e}")
        return []


# ============================================================================
# MODO n8n
# ============================================================================

def process_n8n_input(input_data):
    """
    Procesa input de n8n (JSON con paths de GeoTIFFs).
    """
    job_id      = input_data.get('job_id', 'unknown')
    tiff_files  = input_data.get('tiff_files', {})
    output_dir  = Path(input_data.get('output_dir', f'/tmp/muorbita/{job_id}/pngs'))
    client_name = input_data.get('client_name', '')
    date_str    = input_data.get('date_str', '')
    mode        = input_data.get('mode', 'both')

    output_dir.mkdir(parents=True, exist_ok=True)

    results = {
        'job_id':       job_id,
        'web_pngs':     {},
        'report_pngs':  {},
        'base64_pngs':  {},
        'bounds':       None,
        'errors':       []
    }

    for layer_key, tiff_path in tiff_files.items():
        tiff_path = Path(tiff_path)
        if not tiff_path.exists():
            results['errors'].append(f"Not found: {tiff_path}")
            continue

        normalized_key = layer_key if layer_key.startswith('PNG_') else f'PNG_{layer_key}'

        if mode in ['web', 'both']:
            web_png = output_dir / f"{normalized_key}.png"
            bounds  = geotiff_to_png_web(tiff_path, web_png)
            if bounds is not False:
                results['web_pngs'][normalized_key] = str(web_png)
                if isinstance(bounds, dict) and results['bounds'] is None:
                    results['bounds'] = bounds
                results['base64_pngs'][normalized_key] = png_to_base64(web_png)

        if mode in ['report', 'both']:
            report_png = output_dir / f"{normalized_key}_report.png"
            success    = geotiff_to_png_report(
                tiff_path, report_png,
                layer_key=normalized_key,
                client_name=client_name,
                date_str=date_str
            )
            if success:
                results['report_pngs'][normalized_key] = str(report_png)

    return results


# ============================================================================
# MAIN
# ============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description='Mu.Orbita GeoTIFF→PNG Converter')
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--input-dir')
    parser.add_argument('--output-dir', default='/tmp/muorbita_pngs')
    parser.add_argument('--drive-folder')
    parser.add_argument('--credentials')
    parser.add_argument('--client-name', default='')
    parser.add_argument('--date-str', default='')
    parser.add_argument('--layers', nargs='+',
                        default=['PNG_NDVI','PNG_NDWI','PNG_EVI','PNG_NDCI','PNG_SAVI','PNG_VRA','PNG_LST'])
    parser.add_argument('--mode', choices=['web','report','both'], default='both')
    parser.add_argument('--stdin', action='store_true')
    return parser.parse_args()


def main():
    args = parse_args()

    if args.stdin:
        input_data = json.loads(sys.stdin.read())
        results = process_n8n_input(input_data)
        print(json.dumps(results, indent=2))
        return

    output_dir = Path(args.output_dir)

    if args.drive_folder and not args.input_dir:
        print(f"Downloading from Google Drive: {args.drive_folder}/{args.job_id}/WEB/")
        downloaded = download_from_drive(
            args.job_id, args.drive_folder,
            output_dir / 'geotiffs', args.credentials
        )
        if downloaded:
            args.input_dir = str(output_dir / 'geotiffs')
        else:
            print("ERROR: No files downloaded from Drive")
            sys.exit(1)

    if not args.input_dir:
        print("ERROR: --input-dir or --drive-folder required")
        sys.exit(1)

    results = convert_all_geotiffs(
        input_dir=args.input_dir,
        output_dir=output_dir,
        job_id=args.job_id,
        client_name=args.client_name,
        date_str=args.date_str,
        layers=args.layers
    )

    print(f"\n{'='*50}")
    print(f"RESULTADO para job {args.job_id}:")
    print(f"  Web PNGs:    {len(results['web_pngs'])}")
    print(f"  Report PNGs: {len(results['report_pngs'])}")
    for err in results.get('errors', []):
        print(f"  ERROR: {err}")

    print(json.dumps(results, indent=2))
    return results


if __name__ == '__main__':
    main()


# ============================================================================
# WRAPPERS PARA API — ACEPTAN BytesIO (sin escritura en disco)
# Llamados desde images.py → endpoint POST /convert-from-drive
# ============================================================================

def tiff_to_web_png(bytesio_or_path, layer_key: str) -> dict:
    """
    Convierte GeoTIFF (BytesIO o path) a PNG web transparente.
    Devuelve { "base64": "...", "bounds": { north, south, east, west } }
    """
    import tempfile

    # Ruta óptima: rasterio lee BytesIO en memoria con MemoryFile (sin disco)
    if HAS_RASTERIO and isinstance(bytesio_or_path, (bytes, BytesIO)):
        try:
            from rasterio.io import MemoryFile

            data = bytesio_or_path.read() if hasattr(bytesio_or_path, 'read') else bytesio_or_path

            with MemoryFile(data) as memfile:
                with memfile.open() as src:
                    count = src.count

                    if count >= 3:
                        r, g, b = src.read(1), src.read(2), src.read(3)
                    else:
                        band = src.read(1)
                        r = g = b = band

                    if count == 4:
                        alpha = src.read(4)
                    else:
                        nodata_mask = (r == 0) & (g == 0) & (b == 0)
                        alpha = np.where(nodata_mask, 0, 255).astype(np.uint8)

                    def _norm(arr):
                        if arr.dtype in [np.float32, np.float64]:
                            mn, mx = arr.min(), arr.max()
                            if mx > mn:
                                arr = ((arr - mn) / (mx - mn) * 255).astype(np.uint8)
                            else:
                                arr = np.zeros_like(arr, dtype=np.uint8)
                        return arr.astype(np.uint8)

                    rgba = np.stack([_norm(r), _norm(g), _norm(b), alpha], axis=-1)
                    img  = Image.fromarray(rgba, 'RGBA')

                    bounds = {
                        'north': src.bounds.top,
                        'south': src.bounds.bottom,
                        'east':  src.bounds.right,
                        'west':  src.bounds.left,
                        'crs':   str(src.crs)
                    }

            if img.size[0] > 1024 or img.size[1] > 1024:
                img.thumbnail((1024, 1024), Image.LANCZOS)

            buf = BytesIO()
            img.save(buf, 'PNG', optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

            return {'base64': b64, 'bounds': bounds}

        except Exception as e:
            return {'base64': None, 'bounds': None, 'error': str(e)}

    # Fallback: archivo temporal
    tmp_in_path = tmp_out_path = None
    try:
        if hasattr(bytesio_or_path, 'read') or isinstance(bytesio_or_path, bytes):
            with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp_in:
                tmp_in.write(bytesio_or_path.read() if hasattr(bytesio_or_path, 'read') else bytesio_or_path)
                tmp_in_path = tmp_in.name
            src_path = tmp_in_path
        else:
            src_path = str(bytesio_or_path)

        tmp_out_path = src_path.replace('.tif', '_web.png')
        bounds       = geotiff_to_png_web(src_path, tmp_out_path)

        with open(tmp_out_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')

        return {'base64': b64, 'bounds': bounds if isinstance(bounds, dict) else None}

    except Exception as e:
        return {'base64': None, 'bounds': None, 'error': str(e)}
    finally:
        for p in [tmp_in_path, tmp_out_path]:
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass


def tiff_to_report_png(bytesio_or_path, layer_key: str,
                       client_name: str = '', date_str: str = '') -> dict:
    """
    Convierte GeoTIFF (BytesIO o path) a PNG de informe con cabecera y leyenda.
    Devuelve { "base64": "..." }
    """
    import tempfile

    tmp_in_path = tmp_out_path = None
    try:
        if hasattr(bytesio_or_path, 'read') or isinstance(bytesio_or_path, bytes):
            with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp_in:
                tmp_in.write(bytesio_or_path.read() if hasattr(bytesio_or_path, 'read') else bytesio_or_path)
                tmp_in_path = tmp_in.name
            input_path = tmp_in_path
        else:
            input_path = str(bytesio_or_path)

        tmp_out_path = (tmp_in_path or input_path).replace('.tif', '_report.png')

        success = geotiff_to_png_report(
            input_path, tmp_out_path,
            layer_key=layer_key,
            client_name=client_name,
            date_str=date_str
        )

        if not success:
            return {'base64': None, 'error': 'geotiff_to_png_report failed'}

        with open(tmp_out_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')

        return {'base64': b64}

    except Exception as e:
        return {'base64': None, 'error': str(e)}
    finally:
        for p in [tmp_in_path, tmp_out_path]:
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass
