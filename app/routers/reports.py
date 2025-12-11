from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any

router = APIRouter(prefix="/api/v1", tags=["Reports"])

class PDFRequest(BaseModel):
    job_id: str
    client_name: Optional[str] = "Cliente"
    client_email: Optional[str] = ""
    crop_type: Optional[str] = "olivar"
    analysis_type: Optional[str] = "baseline"
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""
    kpis: Optional[Any] = None
    claude_analysis: Optional[str] = ""
    html_report: Optional[str] = ""

@router.post("/generate-pdf")
async def generate_pdf(request: PDFRequest):
    try:
        from app.services.generate_pdf_report import generate_report
        
        output_path = f"/tmp/Informe_{request.job_id}.pdf"
        
        data = request.dict()
        result = generate_report(data, output_path)
        
        return {
            "success": True,
            "job_id": request.job_id,
            "pdf_path": output_path,
            "message": "PDF generado correctamente"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
