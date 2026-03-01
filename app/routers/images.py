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
from app.services.geotiff_to_png import convert_job_geotiffs

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


# =====================================================
# CONVERTIR GEOTIFFS → PNGs SATELITALES (NUEVO)
# =====================================================

@router.post("/convert-geotiffs")
async def convert_geotiffs_endpoint(request: Request):
    """
    Convierte los GeoTIFFs de GEE a PNGs reales del mapa para web y PDF.

    n8n llama aquí en lugar del antiguo /generate-pngs.

    Body:
    {
        "job_id":      "MUORBITA_xxx",
        "tiff_dir":    "/tmp/muorbita/MUORBITA_xxx/geotiffs",
        "client_name": "Nombre del cliente",
        "date_str":    "24/02/2026",
        "layers":      ["PNG_NDVI", "PNG_NDWI", ...]   <- opcional
    }

    Respuesta:
    {
        "job_id": "...",
        "web_pngs":    { "PNG_NDVI": { "base64": "...", "bounds": {...} }, ... },
        "report_pngs": { "PNG_NDVI": { "base64": "..." }, ... },
        "bounds":      { "north": ..., "south": ..., "east": ..., "west": ... },
        "errors":      []
    }
    """
    data = await request.json()

    job_id      = data.get("job_id", "")
    tiff_dir    = data.get("tiff_dir", f"/tmp/muorbita/{job_id}/geotiffs")
    client_name = data.get("client_name", "")
    date_str    = data.get("date_str", "")
    layers      = data.get("layers", None)

    if not job_id:
        return JSONResponse({"error": "job_id requerido"}, status_code=400)

    result = convert_job_geotiffs(
        job_id=job_id,
        tiff_dir=tiff_dir,
        client_name=client_name,
        date_str=date_str,
        layers=layers,
    )
    return JSONResponse(content=result)


# =====================================================
# SERVIR PNGs DESDE DISCO (para Leaflet dashboard)
# =====================================================

@router.get("/{job_id}/{filename}")
async def get_satellite_image(
    job_id: str,
    filename: str,
    db: Session = Depends(get_db)
):
    """
    Sirve imágenes satelitales para el dashboard.

    Intenta primero desde disco local (/tmp/muorbita/...),
    si no está redirige a Google Drive (comportamiento anterior).
    """

    # Validar job_id — ahora acepta formato MUORBITA_xxx además de JOB_xxx
    if not re.match(r'^[A-Z_0-9]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job_id format")

    valid_files = [
        'PNG_NDVI.png', 'PNG_NDWI.png', 'PNG_EVI.png',
        'PNG_NDCI.png', 'PNG_SAVI.png', 'PNG_VRA.png', 'PNG_LST.png'
    ]
    if filename not in valid_files:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # 1. Buscar en disco local (generado por convert-geotiffs)
    local_path = f"/tmp/muorbita/{job_id}/pngs/{filename}"
    if os.path.exists(local_path):
        return FileResponse(
            local_path,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*",
            }
        )

    # 2. Fallback: buscar en BD y redirigir a Drive
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
    """Lista todas las imágenes disponibles para un job"""

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
# REGISTRAR IMÁGENES DESDE N8N (sin cambios)
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
    n8n registra las imágenes después de subirlas a Drive.

    Body:
    {
        "job_id": "MUORBITA_xxx",
        "images": [
            {"index_type": "NDVI", "gdrive_file_id": "1abc123..."},
            ...
        ]
    }
    """
    created = []

    for img_data in request.images:
        index_type    = img_data.get("index_type")
        gdrive_file_id = img_data.get("gdrive_file_id")
        folder        = img_data.get("folder", "WEB")

        if not index_type or not gdrive_file_id:
            continue

        existing = db.query(GEEImage).filter(
            GEEImage.job_id == request.job_id,
            GEEImage.index_type == index_type,
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
        "success": True,
        "job_id": request.job_id,
        "processed": len(created),
        "details": created
    }
