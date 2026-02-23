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


def normalize_crop_type(crop_type: str) -> str:
    """
    Normaliza el tipo de cultivo al formato esperado por GEE.
    
    Args:
        crop_type: Tipo de cultivo del usuario (puede venir en varios formatos)
    
    Returns:
        Tipo normalizado: 'olivo', 'vina', 'almendro', o 'otro'
    """
    if not crop_type:
        return 'otro'
    
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
        
        # Otros
        'other': 'otro',
        'otro': 'otro',
    }
    
    normalized = crop_type.lower().strip()
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
        # Normalizar tipo de cultivo para curvas fenológicas
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
                    "crop_type_original": request.crop_type,
                    "crop_type_normalized": normalized_crop,
                    "phenology_enabled": normalized_crop in ['olivo', 'vina', 'almendro'],
                    "script_length": len(script),
                    "script_preview": script[:1000] + "..." if len(script) > 1000 else script,
                    "message": "Script generated successfully (debug mode)"
                }
            except ImportError:
                return {
                    "success": False,
                    "error": "gee_script_generator module not available"
                }
        
        # Importar módulos GEE
        try:
            from app.services.gee_automation import (
                execute_analysis, 
                check_status, 
                download_results, 
                start_tasks
            )
        except ImportError as e:
            raise HTTPException(
                status_code=500, 
                detail=f"GEE automation module not available: {str(e)}"
            )
        
        # Crear objeto args similar a argparse
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
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=500, 
            detail=f"GEE execution error: {str(e)}\n{traceback.format_exc()}"
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
                "peak_ndvi_value": 0.62,
                "phases": ["Reposo invernal", "Brotación", "Floración", "Cuajado", "Envero", "Maduración", "Post-cosecha"]
            },
            {
                "id": "vina",
                "aliases": ["viña", "viñedo", "vid", "vineyard"],
                "name_es": "Viña",
                "peak_ndvi_month": "Junio-Julio",
                "peak_ndvi_value": 0.58,
                "phases": ["Reposo invernal", "Lloro", "Brotación", "Floración", "Cuajado", "Envero", "Maduración", "Post-vendimia"]
            },
            {
                "id": "almendro",
                "aliases": ["almendra", "almendral", "almond"],
                "name_es": "Almendro",
                "peak_ndvi_month": "Junio",
                "peak_ndvi_value": 0.65,
                "phases": ["Reposo invernal", "Floración", "Cuajado", "Desarrollo fruto", "Maduración", "Post-cosecha"]
            }
        ],
        "fallback": {
            "id": "otro",
            "description": "Para otros cultivos se usa z-score estacional sin curva fenológica específica",
            "method": "Comparación con histórico del mismo período (±15 días)"
        }
    }


@router.get("/health")
async def gee_health():
    """
    Health check del servicio GEE.
    """
    modules_status = {
        "gee_automation": False,
        "gee_script_generator": False,
        "ee_initialized": False
    }
    
    # Verificar módulos
    try:
        from app.services.gee_automation import execute_analysis
        modules_status["gee_automation"] = True
    except ImportError:
        pass
    
    try:
        from app.services.gee_script_generator import generate_gee_script
        modules_status["gee_script_generator"] = True
    except ImportError:
        pass
    
    try:
        import ee
        # No inicializamos aquí, solo verificamos que está disponible
        modules_status["ee_available"] = True
    except ImportError:
        modules_status["ee_available"] = False
    
    all_ok = all([
        modules_status.get("gee_automation", False),
        modules_status.get("ee_available", False)
    ])
    
    return {
        "status": "ok" if all_ok else "degraded",
        "service": "gee",
        "version": "3.2",
        "modules": modules_status,
        "features": {
            "phenological_curves": True,
            "seasonal_zscore": True,
            "supported_crops": ["olivo", "vina", "almendro"],
            "png_export": True
        }
    }
