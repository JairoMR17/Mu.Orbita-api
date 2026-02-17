"""
MU.ORBITA - Router de Imágenes Satelitales
Redirige peticiones de imágenes a Google Drive
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
import re

from app.database import get_db
from app.models.gee_image import GEEImage

router = APIRouter(prefix="/api/images", tags=["Satellite Images"])


def extract_gdrive_id(url: str) -> Optional[str]:
    """Extrae el file ID de una URL de Google Drive"""
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
    """Convierte file_id a URL directa de descarga/visualización"""
    return f"https://drive.google.com/uc?export=view&id={file_id}"


@router.get("/{job_id}/{filename}")
async def get_satellite_image(
    job_id: str, 
    filename: str,
    db: Session = Depends(get_db)
):
    """
    Redirige a la imagen PNG en Google Drive.
    
    El frontend llama: /api/images/JOB_123/PNG_NDVI.png
    Este endpoint busca la URL en la DB y redirige.
    """
    
    # Validar job_id
    if not re.match(r'^JOB_\d+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job_id format")
    
    # Validar filename
    valid_files = [
        'PNG_NDVI.png', 'PNG_NDWI.png', 'PNG_EVI.png', 
        'PNG_NDCI.png', 'PNG_SAVI.png', 'PNG_VRA.png', 'PNG_LST.png'
    ]
    
    if filename not in valid_files:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    # Buscar en base de datos
    image_record = db.query(GEEImage).filter(
        GEEImage.job_id == job_id,
        GEEImage.filename == filename
    ).first()
    
    if not image_record or not image_record.gdrive_file_id:
        raise HTTPException(status_code=404, detail=f"Image not found: {job_id}/{filename}")
    
    direct_url = gdrive_direct_url(image_record.gdrive_file_id)
    return RedirectResponse(url=direct_url)


@router.get("/{job_id}")
async def list_job_images(
    job_id: str,
    db: Session = Depends(get_db)
):
    """Lista todas las imágenes disponibles para un job"""
    
    if not re.match(r'^JOB_\d+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job_id format")
    
    # Consultar DB
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
# ENDPOINT PARA QUE N8N REGISTRE IMÁGENES
# =====================================================

from pydantic import BaseModel
from typing import List

class RegisterImageRequest(BaseModel):
    job_id: str
    images: List[dict]  # [{"index_type": "NDVI", "gdrive_file_id": "abc123"}, ...]

@router.post("/register")
async def register_images(
    request: RegisterImageRequest,
    db: Session = Depends(get_db)
):
    """
    Endpoint para que n8n registre las imágenes después de subirlas a Drive.
    
    Body:
    {
        "job_id": "JOB_123456789",
        "images": [
            {"index_type": "NDVI", "gdrive_file_id": "1abc123..."},
            {"index_type": "NDWI", "gdrive_file_id": "1def456..."},
            ...
        ]
    }
    """
    created = []
    
    for img_data in request.images:
        index_type = img_data.get("index_type")
        gdrive_file_id = img_data.get("gdrive_file_id")
        folder = img_data.get("folder", "WEB")
        
        if not index_type or not gdrive_file_id:
            continue
        
        # Verificar si ya existe
        existing = db.query(GEEImage).filter(
            GEEImage.job_id == request.job_id,
            GEEImage.index_type == index_type,
            GEEImage.gdrive_folder == folder
        ).first()
        
        if existing:
            # Actualizar
            existing.gdrive_file_id = gdrive_file_id
            created.append({"index_type": index_type, "action": "updated"})
        else:
            # Crear nuevo
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
