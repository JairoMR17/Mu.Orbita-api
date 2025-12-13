from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, Any
import base64

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
        generate_report(data, output_path)
        
        # Leer el PDF y convertir a base64
        with open(output_path, 'rb') as f:
            pdf_bytes = f.read()
        
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        return {
            "success": True,
            "job_id": request.job_id,
            "pdf_path": output_path,
            "pdf_base64": pdf_base64,
            "filename": f"Informe_MUORBITA_{request.job_id}.pdf",
            "message": "PDF generado correctamente"
        }
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}")
