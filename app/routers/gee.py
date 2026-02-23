"""
Mu.Orbita API - GEE Router
Endpoints para ejecutar análisis en Google Earth Engine
VERSIÓN 3.2 - Con soporte para contexto fenológico
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import json
from types import SimpleNamespace

router = APIRouter(prefix="/api/v1/gee", tags=["GEE"])


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


def normalize_crop_type(crop_type: str) -> str:
    """
    Normaliza el tipo de cultivo al formato esperado por GEE.
    
    Args:
        crop_type: Tipo de cultivo del usuario (puede venir en varios formatos)
    
    Returns:
        Tipo normalizado: 'olivo', 'vina', 'almendro', o 'otro'
    """
    crop_map = {
        # Olivo
        'olivo': 'olivo',
        'olivar': 'olivo',
        'oliva': 'olivo',
        'olive': 'olivo',
        
        # Viña
        'viña': 'vina',
        'vina': 'vina',
        'viñedo': 'vina',
        'vinedo': 'vina',
        'vid': 'vina',
        'vineyard': 'vina',
        
        # Almendro
        'almendro': 'almendro',
        'almendra': 'almendro',
        'almendral': 'almendro',
        'almond': 'almendro',
    }
    
    normalized = crop_type.lower().strip() if crop_type else 'otro'
    return crop_map.get(normalized, 'otro')


@router.post("/execute")
async def execute_gee(request: GEERequest):
    """
    Ejecuta análisis GEE v3.2 con soporte para contexto fenológico.
    
    Modos disponibles:
    - execute: Ejecuta el análisis completo
    - check-status: Verifica estado de tareas
    - download-results: Descarga resultados de Drive
    - start-tasks: Inicia tareas de exportación
    - generate-script: Solo genera el script (para debug)
    """
    try:
        from app.services.gee_automation import (
            execute_analysis, 
            check_status, 
            download_results, 
            start_tasks
        )
        
        # Normalizar tipo de cultivo para curvas fenológicas
        normalized_crop = normalize_crop_type(request.crop_type)
        
        # Crear objeto args similar a argparse
        args = SimpleNamespace(
            mode=request.mode,
            job_id=request.job_id,
            roi=json.dumps(request.roi_geojson) if request.roi_geojson else "{}",
            start_date=request.start_date,
            end_date=request.end_date,
            crop=normalized_crop,  # Usar tipo normalizado
            crop_type=normalized_crop,  # Alias para compatibilidad
            buffer=request.buffer_meters,
            analysis_type=request.analysis_type,
            output_dir=request.output_dir or f"/tmp/muorbita_{request.job_id}",
            drive_folder=request.drive_folder
        )
        
        if request.mode == 'execute':
            result = execute_analysis(args)
            
        elif request.mode == 'check-status':
            result = check_status(args)
            
        elif request.mode == 'download-results':
            result = download_results(args)
            
        elif request.mode == 'start-tasks':
            result = start_tasks(args)
            
        elif request.mode == 'generate-script':
            # Modo debug: solo genera el script sin ejecutar
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
                "crop_type_normalized": normalized_crop,
                "script_length": len(script),
                "script_preview": script[:500] + "...",
                "message": "Script generated (debug mode)"
            }
            
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"Unknown mode: {request.mode}. Valid modes: execute, check-status, download-results, start-tasks, generate-script"
            )
        
        # Añadir info de fenología a la respuesta
        return {
            "success": True, 
            "result": result,
            "phenology_info": {
                "crop_type_original": request.crop_type,
                "crop_type_normalized": normalized_crop,
                "phenology_enabled": normalized_crop in ['olivo', 'vina', 'almendro']
            }
        }
        
    except ImportError as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error importing GEE modules: {str(e)}"
        )
    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=500, 
            detail=f"{str(e)}\n{traceback.format_exc()}"
        )


@router.get("/crop-types")
async def get_crop_types():
    """
    Devuelve los tipos de cultivo soportados con curvas fenológicas.
    """
    return {
        "supported_with_phenology": [
            {
                "id": "olivo",
                "aliases": ["olivar", "oliva", "olive"],
                "name_es": "Olivo",
                "peak_ndvi_month": "Junio",
                "peak_ndvi_value": 0.62
            },
            {
                "id": "vina",
                "aliases": ["viña", "viñedo", "vid", "vineyard"],
                "name_es": "Viña",
                "peak_ndvi_month": "Junio",
                "peak_ndvi_value": 0.58
            },
            {
                "id": "almendro",
                "aliases": ["almendra", "almendral", "almond"],
                "name_es": "Almendro",
                "peak_ndvi_month": "Junio",
                "peak_ndvi_value": 0.65
            }
        ],
        "fallback": {
            "id": "otro",
            "description": "Para otros cultivos se usa z-score estacional sin curva fenológica específica"
        }
    }


@router.get("/health")
async def gee_health():
    """
    Health check del servicio GEE.
    """
    try:
        # Intentar importar módulos necesarios
        from app.services.gee_automation import execute_analysis
        from app.services.gee_script_generator import generate_gee_script
        
        return {
            "status": "ok",
            "service": "gee",
            "version": "3.2",
            "features": {
                "phenological_curves": True,
                "seasonal_zscore": True,
                "supported_crops": ["olivo", "vina", "almendro"]
            }
        }
    except ImportError as e:
        return {
            "status": "degraded",
            "service": "gee",
            "error": str(e)
        }
