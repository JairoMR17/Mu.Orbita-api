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

@router.post("/execute")
async def execute_gee(request: GEERequest):
    try:
        from app.services.gee_automation import execute_analysis, check_status, download_results, start_tasks
        
        # Crear objeto args similar a argparse
        args = SimpleNamespace(
            mode=request.mode,
            job_id=request.job_id,
            roi=json.dumps(request.roi_geojson) if request.roi_geojson else "{}",
            start_date=request.start_date,
            end_date=request.end_date,
            crop=request.crop_type,
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
            raise HTTPException(status_code=400, detail=f"Unknown mode: {request.mode}")
        
        return {"success": True, "result": result}
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}")
