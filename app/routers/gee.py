"""
Mu.Orbita API - GEE Router v5.1 (NO-DRIVE)
============================================

V5.1: Mantiene images_base64 en respuesta para que n8n use en PDF.
      Parámetro strip_images=true para limpiar si no se necesitan.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
import json
import traceback
from types import SimpleNamespace

from app.database import get_db
from app.models.gee_image import GEEImage

router = APIRouter(prefix="/gee", tags=["GEE"])


class GEERequest(BaseModel):
    mode: str
    job_id: str
    roi_geojson: Optional[dict] = {}
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""
    crop_type: str = "olivar"
    buffer_meters: int = 0
    analysis_type: str = "baseline"
    output_dir: Optional[str] = ""
    drive_folder: Optional[str] = "MuOrbita_Outputs"
    strip_images: Optional[bool] = False  # Si true, no devuelve base64 en respuesta


def normalize_crop_type(crop_type: str) -> str:
    if not crop_type:
        return 'otro'
    crop_map = {
        'olivo': 'olivo', 'olivar': 'olivo', 'oliva': 'olivo', 'olive': 'olivo',
        'viña': 'vina', 'vina': 'vina', 'viñedo': 'vina', 'vinedo': 'vina',
        'vid': 'vina', 'vineyard': 'vina',
        'almendro': 'almendro', 'almendra': 'almendro', 'almendral': 'almendro',
        'almond': 'almendro',
        'other': 'otro', 'otro': 'otro',
    }
    return crop_map.get(crop_type.lower().strip(), 'otro')


def save_images_to_db(db: Session, job_id: str, images_base64: dict, bounds: dict = None):
    saved = []
    for index_type, b64_data in images_base64.items():
        if not b64_data:
            continue
        filename = f"PNG_{index_type}.png"
        existing = db.query(GEEImage).filter(
            GEEImage.job_id == job_id,
            GEEImage.index_type == index_type
        ).first()
        if existing:
            existing.png_base64 = b64_data
            if bounds:
                existing.bounds_north = bounds.get('north')
                existing.bounds_south = bounds.get('south')
                existing.bounds_east = bounds.get('east')
                existing.bounds_west = bounds.get('west')
            saved.append({"index_type": index_type, "action": "updated"})
        else:
            new_image = GEEImage(
                job_id=job_id,
                index_type=index_type,
                filename=filename,
                png_base64=b64_data,
                bounds_north=bounds.get('north') if bounds else None,
                bounds_south=bounds.get('south') if bounds else None,
                bounds_east=bounds.get('east') if bounds else None,
                bounds_west=bounds.get('west') if bounds else None,
            )
            db.add(new_image)
            saved.append({"index_type": index_type, "action": "created"})
    db.commit()
    return saved


@router.post("/execute")
async def execute_gee(request: GEERequest, db: Session = Depends(get_db)):
    try:
        normalized_crop = normalize_crop_type(request.crop_type)
        
        if request.mode == 'generate-script':
            try:
                from app.services.gee_script_generator import generate_gee_script
                script = generate_gee_script(
                    job_id=request.job_id,
                    roi_geojson=request.roi_geojson,
                    crop_type=normalized_crop,
                    start_date=request.start_date,
                    end_date=request.end_date
                )
                return {"success": True, "mode": "generate-script", "job_id": request.job_id, "script_length": len(script)}
            except ImportError:
                return {"success": False, "error": "gee_script_generator not available"}
        
        try:
            from app.services.gee_automation import execute_analysis, execute_biweekly_analysis
        except ImportError as e:
            raise HTTPException(status_code=500, detail=f"GEE module not available: {str(e)}")
        
        args = SimpleNamespace(
            mode=request.mode,
            job_id=request.job_id,
            roi=json.dumps(request.roi_geojson) if request.roi_geojson else "{}",
            start_date=request.start_date,
            end_date=request.end_date,
            crop=normalized_crop,
            crop_type=normalized_crop,
            buffer=request.buffer_meters,
            analysis_type=request.analysis_type,
            output_dir=request.output_dir or f"/tmp/muorbita_{request.job_id}",
            drive_folder=request.drive_folder,
            export_png=True
        )
        
        if request.mode == 'execute':
            if request.analysis_type == 'biweekly':
                result = execute_biweekly_analysis(args)
            else:
                result = execute_analysis(args)
            
            # Guardar imágenes en BD
            images_base64 = result.get('images_base64', {})
            bounds = result.get('bounds', {})
            
            if images_base64:
                saved_images = save_images_to_db(db, request.job_id, images_base64, bounds)
                result['images_saved'] = saved_images
                result['images_saved_count'] = len(saved_images)
            
            result['images_available'] = list(images_base64.keys()) if images_base64 else []
            
            # Por defecto MANTENER base64 para que n8n use en PDF
            # Solo limpiar si strip_images=true
            if request.strip_images and images_base64:
                result['images_base64'] = {
                    k: f"[stripped:{len(v)} chars]"
                    for k, v in images_base64.items() if v
                }
        
        elif request.mode in ('check-status', 'start-tasks', 'download-results'):
            result = {
                'job_id': request.job_id,
                'all_complete': True,
                'progress_pct': 100,
                'tasks': [],
                'message': 'v5: No async tasks. Data in execute response.'
            }
        else:
            raise HTTPException(status_code=400, detail=f"Unknown mode: {request.mode}")
        
        return {
            "success": True,
            "result": result,
            "analysis_info": {
                "analysis_type": request.analysis_type,
                "crop_type_original": request.crop_type,
                "crop_type_normalized": normalized_crop,
                "phenology_enabled": normalized_crop in ['olivo', 'vina', 'almendro'],
                "is_biweekly": request.analysis_type == 'biweekly',
                "version": "5.1",
                "drive_used": False
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GEE error: {str(e)}\n{traceback.format_exc()}")


@router.get("/crop-types")
async def get_crop_types():
    return {
        "supported_with_phenology": [
            {"id": "olivo", "aliases": ["olivar", "oliva", "olive"], "name_es": "Olivo"},
            {"id": "vina", "aliases": ["viña", "viñedo", "vid", "vineyard"], "name_es": "Viña"},
            {"id": "almendro", "aliases": ["almendra", "almendral", "almond"], "name_es": "Almendro"}
        ],
        "fallback": {"id": "otro"}
    }

@router.get("/analysis-types")
async def get_analysis_types():
    return {
        "types": [
            {"id": "baseline", "processing_time": "2-5 min", "images": ["NDVI","NDWI","EVI","NDCI","SAVI","VRA","LST"]},
            {"id": "biweekly", "processing_time": "1-3 min", "images": ["NDVI","NDWI"]}
        ]
    }

@router.get("/health")
async def gee_health():
    modules = {}
    try:
        from app.services.gee_automation import execute_analysis
        modules["gee_automation"] = True
    except ImportError:
        modules["gee_automation"] = False
    try:
        from app.services.gee_automation import execute_biweekly_analysis
        modules["biweekly"] = True
    except ImportError:
        modules["biweekly"] = False
    try:
        import ee
        modules["ee"] = True
    except ImportError:
        modules["ee"] = False
    return {"status": "ok" if all(modules.values()) else "degraded", "version": "5.1", "drive": False, "modules": modules}
