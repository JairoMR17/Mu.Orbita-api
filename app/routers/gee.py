from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import json
import sys
import os

# Añadir services al path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'services'))

router = APIRouter(prefix="/api/v1/gee", tags=["GEE"])

class GEERequest(BaseModel):
    mode: str
    job_id: str
    roi_geojson: dict
    start_date: str
    end_date: str
    crop_type: str = "olivar"
    buffer_meters: int = 0
    analysis_type: str = "baseline"

@router.post("/execute")
async def execute_gee(request: GEERequest):
    try:
        from services.gee_automation import main as gee_main
        
        result = gee_main(
            mode=request.mode,
            job_id=request.job_id,
            roi=json.dumps(request.roi_geojson),
            start_date=request.start_date,
            end_date=request.end_date,
            crop=request.crop_type,
            buffer=request.buffer_meters,
            analysis_type=request.analysis_type
        )
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
