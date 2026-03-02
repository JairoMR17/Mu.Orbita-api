"""
MU.ORBITA - Router de Imágenes Satelitales v5.0 (NO-DRIVE)
============================================================

CAMBIOS V5.0:
✅ Sirve PNGs directamente desde BD (base64 → bytes)
✅ Eliminada dependencia de Google Drive
✅ Eliminado endpoint convert-from-drive (ya no hay GeoTIFFs)
✅ Eliminado endpoint register (gee.py guarda directamente)
✅ Nuevo endpoint /store para que n8n pueda guardar PNGs extra
✅ Dashboard sigue llamando: /api/images/{job_id}/PNG_NDVI.png → funciona igual
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
import re
import base64

from app.database import get_db
from app.models.gee_image import GEEImage

router = APIRouter(prefix="/api/images", tags=["Satellite Images"])


# =====================================================
# SERVIR PNGs DESDE BD — endpoint principal del dashboard
# =====================================================

@router.get("/{job_id}/{filename}")
async def get_satellite_image(
    job_id: str,
    filename: str,
    db: Session = Depends(get_db)
):
    """
    El dashboard llama: /api/images/MUORBITA_xxx/PNG_NDVI.png
    
    V4: Buscaba gdrive_file_id en BD → redirigía a Drive
    V5: Busca png_base64 en BD → devuelve bytes PNG directamente
    
    Mucho más rápido y sin dependencia externa.
    """
    # Validar job_id
    if not re.match(r'^[A-Za-z0-9_]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job_id format")

    # Validar filename
    valid_files = [
        'PNG_NDVI.png', 'PNG_NDWI.png', 'PNG_EVI.png',
        'PNG_NDCI.png', 'PNG_SAVI.png', 'PNG_VRA.png', 'PNG_LST.png'
    ]
    if filename not in valid_files:
        raise HTTPException(status_code=400, detail=f"Invalid filename: {filename}")

    # Extraer index_type del filename: "PNG_NDVI.png" → "NDVI"
    index_type = filename.replace('PNG_', '').replace('.png', '')

    # Buscar en BD
    image_record = db.query(GEEImage).filter(
        GEEImage.job_id == job_id,
        GEEImage.index_type == index_type
    ).first()

    if not image_record:
        raise HTTPException(status_code=404, detail=f"Image not found: {job_id}/{filename}")

    # Intentar servir desde base64 (v5.0)
    if image_record.png_base64:
        try:
            png_bytes = base64.b64decode(image_record.png_base64)
            return Response(
                content=png_bytes,
                media_type="image/png",
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "X-Image-Source": "database",
                    "X-Job-Id": job_id,
                    "X-Index-Type": index_type
                }
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"Error decoding image: {str(e)}"
            )
    
    # Fallback v4: si aún tiene gdrive_file_id (datos legacy)
    if hasattr(image_record, 'gdrive_file_id') and image_record.gdrive_file_id:
        from fastapi.responses import RedirectResponse
        gdrive_url = f"https://drive.google.com/uc?export=view&id={image_record.gdrive_file_id}"
        return RedirectResponse(url=gdrive_url)

    raise HTTPException(status_code=404, detail=f"No image data for: {job_id}/{filename}")


# =====================================================
# LISTAR IMÁGENES DE UN JOB
# =====================================================

@router.get("/{job_id}")
async def list_job_images(
    job_id: str,
    db: Session = Depends(get_db)
):
    """Lista todas las imágenes disponibles para un job."""
    if not re.match(r'^[A-Za-z0-9_]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job_id format")

    images = db.query(GEEImage).filter(GEEImage.job_id == job_id).all()

    if not images:
        raise HTTPException(status_code=404, detail=f"No images found for job: {job_id}")

    result_images = {}
    bounds = None
    
    for img in images:
        result_images[img.index_type] = {
            "url": f"/api/images/{job_id}/{img.filename}",
            "has_data": bool(img.png_base64),
            "source": "database" if img.png_base64 else "legacy_drive"
        }
        # Extraer bounds del primer registro que los tenga
        if not bounds and img.bounds_north is not None:
            bounds = {
                "north": img.bounds_north,
                "south": img.bounds_south,
                "east": img.bounds_east,
                "west": img.bounds_west
            }

    return {
        "job_id": job_id,
        "count": len(images),
        "bounds": bounds,
        "images": result_images
    }


# =====================================================
# GUARDAR IMÁGENES DESDE N8N (reemplaza /register)
# =====================================================

class StoreImageRequest(BaseModel):
    job_id: str
    images: dict  # {"NDVI": "base64...", "NDWI": "base64..."}
    bounds: Optional[dict] = None  # {"north":..., "south":..., "east":..., "west":...}


@router.post("/store")
async def store_images(
    request: StoreImageRequest,
    db: Session = Depends(get_db)
):
    """
    Guarda PNGs (base64) en la BD.
    
    Normalmente gee.py ya guarda las imágenes automáticamente tras execute.
    Este endpoint es para casos donde n8n necesita guardar imágenes extra
    (ej: PNGs generados por report_png con cabecera Mu.Orbita).
    
    Body:
    {
        "job_id": "MUORBITA_xxx",
        "images": {
            "NDVI": "iVBORw0KGgo...",
            "NDWI": "iVBORw0KGgo..."
        },
        "bounds": {"north": 37.5, "south": 37.4, "east": -4.0, "west": -4.1}
    }
    """
    saved = []
    
    for index_type, b64_data in request.images.items():
        if not b64_data or not isinstance(b64_data, str):
            continue
        
        # Validar que es base64 real
        try:
            decoded = base64.b64decode(b64_data)
            if len(decoded) < 100:
                continue
        except Exception:
            continue
        
        filename = f"PNG_{index_type}.png"
        
        existing = db.query(GEEImage).filter(
            GEEImage.job_id == request.job_id,
            GEEImage.index_type == index_type
        ).first()
        
        if existing:
            existing.png_base64 = b64_data
            if request.bounds:
                existing.bounds_north = request.bounds.get('north')
                existing.bounds_south = request.bounds.get('south')
                existing.bounds_east = request.bounds.get('east')
                existing.bounds_west = request.bounds.get('west')
            saved.append({"index_type": index_type, "action": "updated", "size_kb": round(len(b64_data) / 1024)})
        else:
            new_image = GEEImage(
                job_id=request.job_id,
                index_type=index_type,
                filename=filename,
                png_base64=b64_data,
                bounds_north=request.bounds.get('north') if request.bounds else None,
                bounds_south=request.bounds.get('south') if request.bounds else None,
                bounds_east=request.bounds.get('east') if request.bounds else None,
                bounds_west=request.bounds.get('west') if request.bounds else None,
            )
            db.add(new_image)
            saved.append({"index_type": index_type, "action": "created", "size_kb": round(len(b64_data) / 1024)})
    
    db.commit()
    
    return {
        "success": True,
        "job_id": request.job_id,
        "saved": len(saved),
        "details": saved
    }


# =====================================================
# MAP-DATA para dashboard (bounds + image URLs)
# =====================================================

@router.get("/{job_id}/map-data")
async def get_map_data(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    Devuelve bounds y URLs de imágenes para el dashboard map.
    El dashboard usa esto para cargar las capas satelitales en Leaflet.
    """
    if not re.match(r'^[A-Za-z0-9_]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job_id format")

    images = db.query(GEEImage).filter(GEEImage.job_id == job_id).all()
    
    if not images:
        return {"job_id": job_id, "bounds": None, "images": {}}

    bounds = None
    image_urls = {}
    
    for img in images:
        if img.png_base64:
            image_urls[img.index_type] = f"/api/images/{job_id}/{img.filename}"
        
        if not bounds and img.bounds_north is not None:
            bounds = {
                "north": img.bounds_north,
                "south": img.bounds_south,
                "east": img.bounds_east,
                "west": img.bounds_west
            }

    return {
        "job_id": job_id,
        "bounds": bounds,
        "images": image_urls
    }


# =====================================================
# LEGACY ENDPOINTS (backward compatibility)
# =====================================================

@router.post("/convert-from-drive")
async def convert_tiff_from_drive_legacy(request: Request):
    """
    LEGACY v4 — Ya no se usa en v5.0
    Las imágenes se generan como PNG directamente en GEE.
    """
    return JSONResponse({
        "success": False,
        "error": "v5.0: Este endpoint ya no se usa. Las imágenes PNG se generan directamente en GEE y se guardan en la BD. No hay GeoTIFFs ni Drive.",
        "migration": "Use POST /gee/execute que guarda imágenes automáticamente, o POST /api/images/store para guardar manualmente."
    }, status_code=410)


class RegisterImageRequestLegacy(BaseModel):
    job_id: str
    images: List[dict]

@router.post("/register")
async def register_images_legacy(request: RegisterImageRequestLegacy):
    """
    LEGACY v4 — Ya no se usa en v5.0
    Use POST /api/images/store con base64 en lugar de gdrive_file_id.
    """
    return JSONResponse({
        "success": False,
        "error": "v5.0: Use POST /api/images/store con formato {images: {NDVI: 'base64...'}}"
    }, status_code=410)
