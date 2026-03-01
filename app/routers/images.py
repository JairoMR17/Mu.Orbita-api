"""
MU.ORBITA - Router de Imágenes Satelitales
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import re
import os

from app.database import get_db
from app.models.gee_image import GEEImage
from app.services.geotiff_to_png import tiff_to_web_png, tiff_to_report_png

router = APIRouter(prefix="/api/images", tags=["Satellite Images"])


# =====================================================
# HELPERS
# =====================================================

def extract_gdrive_id(url: str) -> Optional[str]:
    patterns = [
        r'/file/d/([a-zA-Z0-9_-]+)',
        r'[?&]id=([a-zA-Z0-9_-]+)',
        r'/d/([a-zA-Z0-9_-]+)/'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def gdrive_direct_url(file_id: str) -> str:
    return f"https://drive.google.com/uc?export=view&id={file_id}"


def get_drive_service():
    """
    Crea cliente de Google Drive usando las credenciales GEE
    que ya están en Railway como variable de entorno.
    """
    import json
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    key_json = os.environ.get("GEE_SERVICE_ACCOUNT_KEY", "{}")
    key_data = json.loads(key_json)

    creds = service_account.Credentials.from_service_account_info(
        key_data,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)


# =====================================================
# CONVERTIR GEOTIFF DESDE DRIVE → PNG EN MEMORIA
# =====================================================

@router.post("/convert-from-drive")
async def convert_tiff_from_drive(request: Request):
    """
    Recibe el Drive file ID de un GeoTIFF exportado por GEE,
    lo descarga en RAM (sin escritura en disco), lo convierte a PNG
    y devuelve base64 para web (Leaflet) y para PDF.

    n8n llama este endpoint UNA VEZ por cada capa (NDVI, NDWI, etc.)

    Body:
    {
        "job_id":          "MUORBITA_xxx",
        "gdrive_file_id":  "1abc123...",
        "layer":           "PNG_NDVI",
        "client_name":     "Nombre del cliente",
        "date_str":        "01/03/2026"
    }

    Respuesta:
    {
        "success":     true,
        "job_id":      "MUORBITA_xxx",
        "layer":       "PNG_NDVI",
        "web_png":     { "base64": "...", "bounds": { "north":..., "south":..., "east":..., "west":... } },
        "report_png":  { "base64": "..." }
    }
    """
    import io
    from googleapiclient.http import MediaIoBaseDownload

    data           = await request.json()
    job_id         = data.get("job_id", "")
    gdrive_file_id = data.get("gdrive_file_id", "")
    layer          = data.get("layer", "PNG_NDVI")
    client_name    = data.get("client_name", "")
    date_str       = data.get("date_str", "")

    if not gdrive_file_id:
        return JSONResponse({"error": "gdrive_file_id requerido"}, status_code=400)

    if not job_id:
        return JSONResponse({"error": "job_id requerido"}, status_code=400)

    try:
        # Descargar GeoTIFF de Drive en memoria (BytesIO, sin tocar disco)
        service = get_drive_service()
        req     = service.files().get_media(fileId=gdrive_file_id)
        fh      = io.BytesIO()
        dl      = MediaIoBaseDownload(fh, req)
        done    = False
        while not done:
            _, done = dl.next_chunk()
        fh.seek(0)

        # PNG para el dashboard Leaflet (transparente, con bounds geoespaciales)
        web_result = tiff_to_web_png(fh, layer)

        # PNG para el PDF (con cabecera Mu.Orbita, leyenda de colores)
        fh.seek(0)
        report_result = tiff_to_report_png(fh, layer, client_name, date_str)

        return JSONResponse({
            "success":    True,
            "job_id":     job_id,
            "layer":      layer,
            "web_png":    web_result,
            "report_png": report_result
        })

    except Exception as e:
        return JSONResponse({
            "success": False,
            "job_id":  job_id,
            "layer":   layer,
            "error":   str(e)
        }, status_code=500)


# =====================================================
# SERVIR PNGs — redirige a Drive por file_id en BD
# =====================================================

@router.get("/{job_id}/{filename}")
async def get_satellite_image(
    job_id: str,
    filename: str,
    db: Session = Depends(get_db)
):
    """
    El dashboard llama: /api/images/MUORBITA_xxx/PNG_NDVI.png
    Busca el file_id en la BD y redirige a Google Drive.
    """

    if not re.match(r'^[A-Z_0-9]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job_id format")

    valid_files = [
        'PNG_NDVI.png', 'PNG_NDWI.png', 'PNG_EVI.png',
        'PNG_NDCI.png', 'PNG_SAVI.png', 'PNG_VRA.png', 'PNG_LST.png'
    ]
    if filename not in valid_files:
        raise HTTPException(status_code=400, detail="Invalid filename")

    image_record = db.query(GEEImage).filter(
        GEEImage.job_id == job_id,
        GEEImage.filename == filename
    ).first()

    if not image_record or not image_record.gdrive_file_id:
        raise HTTPException(status_code=404, detail=f"Image not found: {job_id}/{filename}")

    return RedirectResponse(url=gdrive_direct_url(image_record.gdrive_file_id))


# =====================================================
# LISTAR IMÁGENES DE UN JOB
# =====================================================

@router.get("/{job_id}")
async def list_job_images(
    job_id: str,
    db: Session = Depends(get_db)
):
    """Lista todas las imágenes disponibles para un job."""

    if not re.match(r'^[A-Z_0-9]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job_id format")

    images = db.query(GEEImage).filter(GEEImage.job_id == job_id).all()

    if not images:
        raise HTTPException(status_code=404, detail=f"No images found for job: {job_id}")

    return JSONResponse({
        "job_id": job_id,
        "count": len(images),
        "images": {
            img.index_type: f"/api/images/{job_id}/{img.filename}"
            for img in images
        }
    })


# =====================================================
# REGISTRAR IMÁGENES DESDE N8N
# =====================================================

from pydantic import BaseModel

class RegisterImageRequest(BaseModel):
    job_id: str
    images: List[dict]


@router.post("/register")
async def register_images(
    request: RegisterImageRequest,
    db: Session = Depends(get_db)
):
    """
    n8n registra los file_ids de Drive después de subir los PNGs.

    Body:
    {
        "job_id": "MUORBITA_xxx",
        "images": [
            {"index_type": "NDVI", "gdrive_file_id": "1abc123...", "folder": "WEB"},
            ...
        ]
    }
    """
    created = []

    for img_data in request.images:
        index_type     = img_data.get("index_type")
        gdrive_file_id = img_data.get("gdrive_file_id")
        folder         = img_data.get("folder", "WEB")

        if not index_type or not gdrive_file_id:
            continue

        existing = db.query(GEEImage).filter(
            GEEImage.job_id        == request.job_id,
            GEEImage.index_type    == index_type,
            GEEImage.gdrive_folder == folder
        ).first()

        if existing:
            existing.gdrive_file_id = gdrive_file_id
            created.append({"index_type": index_type, "action": "updated"})
        else:
            new_image = GEEImage.create_for_job(
                job_id=request.job_id,
                index_type=index_type,
                gdrive_file_id=gdrive_file_id,
                folder=folder
            )
            db.add(new_image)
            created.append({"index_type": index_type, "action": "created"})

    db.commit()

    return {
        "success":   True,
        "job_id":    request.job_id,
        "processed": len(created),
        "details":   created
    }
