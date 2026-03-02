"""
Mu.Orbita API - GEE Router v5.0 (NO-DRIVE)
============================================

CAMBIOS V5.0:
✅ execute devuelve images_base64 directamente → se guardan en BD
✅ Eliminados: start-tasks, check-status, download-results (legacy stubs)
✅ Nuevo: guarda PNGs en tabla gee_images como base64
✅ Nuevo: guarda KPIs y time_series en respuesta para n8n
✅ Compatible con n8n workflow simplificado (sin loop Drive)
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


# =====================================================
# REQUEST MODEL
# =====================================================

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
    drive_folder: Optional[str] = "MuOrbita_Outputs"  # legacy, unused


# =====================================================
# HELPERS
# =====================================================

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
    """
    Guarda las imágenes PNG (base64) directamente en la BD.
    Reemplaza el flujo anterior: Drive export → search → download → convert.
    
    images_base64: {"NDVI": "iVBOR...", "NDWI": "iVBOR...", ...}
    """
    saved = []
    
    for index_type, b64_data in images_base64.items():
        if not b64_data:
            continue
        
        filename = f"PNG_{index_type}.png"
        
        # Upsert: actualizar si ya existe, crear si no
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


# =====================================================
# EXECUTE ENDPOINT
# =====================================================

@router.post("/execute")
async def execute_gee(request: GEERequest, db: Session = Depends(get_db)):
    """
    Ejecuta análisis GEE v5.0 — sin Drive, PNGs directos.
    
    Flujo:
    1. Llama a gee_automation.execute_analysis() o execute_biweekly_analysis()
    2. Recibe KPIs + images_base64 + time_series en el JSON
    3. Guarda imágenes PNG en la BD automáticamente
    4. Devuelve todo a n8n para generar informe Claude + PDF
    
    n8n ya NO necesita: start-tasks, wait, download-results, buscar TIF en Drive
    """
    try:
        normalized_crop = normalize_crop_type(request.crop_type)
        
        # Modo generate-script (debug)
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
                return {
                    "success": True,
                    "mode": "generate-script",
                    "job_id": request.job_id,
                    "script_length": len(script),
                    "script_preview": script[:1000] + "..." if len(script) > 1000 else script
                }
            except ImportError:
                return {"success": False, "error": "gee_script_generator not available"}
        
        # Importar módulo GEE
        try:
            from app.services.gee_automation import (
                execute_analysis,
                execute_biweekly_analysis,
            )
        except ImportError as e:
            raise HTTPException(
                status_code=500, 
                detail=f"GEE automation module not available: {str(e)}"
            )
        
        # Crear args compatibles
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
            # ========== EJECUTAR ANÁLISIS ==========
            if request.analysis_type == 'biweekly':
                result = execute_biweekly_analysis(args)
            else:
                result = execute_analysis(args)
            
            # ========== GUARDAR IMÁGENES EN BD ==========
            images_base64 = result.get('images_base64', {})
            bounds = result.get('bounds', {})
            
            if images_base64:
                saved_images = save_images_to_db(db, request.job_id, images_base64, bounds)
                result['images_saved'] = saved_images
                result['images_saved_count'] = len(saved_images)
            
            # Eliminar base64 pesado del JSON de respuesta para n8n
            # (n8n no necesita los bytes, ya están en BD)
            # Pero MANTENER las keys para que n8n sepa qué capas hay
            if images_base64:
                result['images_available'] = list(images_base64.keys())
                # Limpiar base64 del resultado para no saturar n8n
                result['images_base64'] = {
                    k: f"[saved_to_db:{len(v)} chars]" 
                    for k, v in images_base64.items() if v
                }
        
        elif request.mode in ('check-status', 'start-tasks', 'download-results'):
            # Legacy stubs — v5.0 no tiene tasks asíncronos
            result = {
                'job_id': request.job_id,
                'all_complete': True,
                'progress_pct': 100,
                'tasks': [],
                'message': 'v5.0: All data returned synchronously in execute response.'
            }
        
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown mode: {request.mode}. Valid: execute, generate-script"
            )
        
        return {
            "success": True,
            "result": result,
            "analysis_info": {
                "analysis_type": request.analysis_type,
                "crop_type_original": request.crop_type,
                "crop_type_normalized": normalized_crop,
                "phenology_enabled": normalized_crop in ['olivo', 'vina', 'almendro'],
                "is_biweekly": request.analysis_type == 'biweekly',
                "version": "5.0",
                "drive_used": False
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"GEE execution error: {str(e)}\n{traceback.format_exc()}"
        )


# =====================================================
# INFO ENDPOINTS (sin cambios)
# =====================================================

@router.get("/crop-types")
async def get_crop_types():
    return {
        "supported_with_phenology": [
            {
                "id": "olivo",
                "aliases": ["olivar", "oliva", "olive"],
                "name_es": "Olivo",
                "peak_ndvi_month": "Junio",
                "peak_ndvi_value": 0.62,
            },
            {
                "id": "vina",
                "aliases": ["viña", "viñedo", "vid", "vineyard"],
                "name_es": "Viña",
                "peak_ndvi_month": "Junio-Julio",
                "peak_ndvi_value": 0.58,
            },
            {
                "id": "almendro",
                "aliases": ["almendra", "almendral", "almond"],
                "name_es": "Almendro",
                "peak_ndvi_month": "Junio",
                "peak_ndvi_value": 0.65,
            }
        ],
        "fallback": {
            "id": "otro",
            "description": "Z-score estacional sin curva fenológica"
        }
    }


@router.get("/analysis-types")
async def get_analysis_types():
    return {
        "types": [
            {
                "id": "baseline",
                "name": "Análisis Baseline",
                "description": "Análisis completo con todos los índices, VRA y PNGs",
                "processing_time": "2-5 minutos (v5.0, sin Drive)",
                "includes_weather": False,
                "includes_vra": True,
                "images": ["NDVI", "NDWI", "EVI", "NDCI", "SAVI", "VRA", "LST"]
            },
            {
                "id": "biweekly",
                "name": "Seguimiento Bisemanal",
                "description": "Análisis ligero con meteorología ERA5",
                "processing_time": "1-3 minutos (v5.0, sin Drive)",
                "includes_weather": True,
                "includes_vra": False,
                "images": ["NDVI", "NDWI"]
            }
        ]
    }


@router.get("/health")
async def gee_health():
    modules_status = {}
    
    try:
        from app.services.gee_automation import execute_analysis
        modules_status["gee_automation"] = True
    except ImportError:
        modules_status["gee_automation"] = False
    
    try:
        from app.services.gee_automation import execute_biweekly_analysis
        modules_status["gee_automation_biweekly"] = True
    except ImportError:
        modules_status["gee_automation_biweekly"] = False
    
    try:
        import ee
        modules_status["ee_available"] = True
    except ImportError:
        modules_status["ee_available"] = False
    
    all_ok = all(modules_status.values())
    
    return {
        "status": "ok" if all_ok else "degraded",
        "service": "gee",
        "version": "5.0",
        "drive_dependency": False,
        "modules": modules_status,
        "features": {
            "direct_png_generation": True,
            "drive_export": False,
            "phenological_curves": True,
            "era5_weather": True,
            "analysis_types": ["baseline", "biweekly"]
        }
    }
