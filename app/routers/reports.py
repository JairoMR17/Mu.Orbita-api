from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, Any
import base64

router = APIRouter(prefix="/api/v1", tags=["Reports"])


class PDFRequest(BaseModel):
    """Modelo de datos para generación de informes PDF"""
    
    # Identificación
    job_id: str
    client_name: Optional[str] = "Cliente"
    crop_type: Optional[str] = "olivar"
    analysis_type: Optional[str] = "baseline"
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""
    
    # Área y procesamiento
    area_hectares: Optional[float] = 0
    images_processed: Optional[int] = 0
    latest_image_date: Optional[str] = ""
    
    # NDVI (Índice de Vegetación)
    ndvi_mean: Optional[float] = 0
    ndvi_p10: Optional[float] = 0
    ndvi_p50: Optional[float] = 0
    ndvi_p90: Optional[float] = 0
    ndvi_stddev: Optional[float] = 0
    ndvi_zscore: Optional[float] = 0
    
    # NDWI (Índice de Agua)
    ndwi_mean: Optional[float] = 0
    ndwi_p10: Optional[float] = 0
    ndwi_p90: Optional[float] = 0
    
    # EVI (Índice de Vegetación Mejorado)
    evi_mean: Optional[float] = 0
    evi_p10: Optional[float] = 0
    evi_p90: Optional[float] = 0
    
    # Otros índices
    ndci_mean: Optional[float] = 0
    savi_mean: Optional[float] = 0
    
    # Estrés
    stress_area_ha: Optional[float] = 0
    stress_area_pct: Optional[float] = 0
    
    # Temperatura (LST)
    lst_mean_c: Optional[float] = 0
    lst_min_c: Optional[float] = 0
    lst_max_c: Optional[float] = 0
    
    # Heterogeneidad
    heterogeneity: Optional[float] = 0
    
    # Contenido del informe
    html_report: Optional[str] = ""
    markdown_analysis: Optional[str] = ""
    
    # Series temporales (opcional)
    timeseries: Optional[list] = None


@router.post("/generate-pdf")
async def generate_pdf(request: PDFRequest):
    """
    Genera un informe PDF profesional a partir de los datos de análisis satelital.
    
    Retorna el PDF en base64 para que n8n pueda adjuntarlo a emails.
    """
    try:
        from app.services.generate_pdf_report import generate_report
        
        output_path = f"/tmp/Informe_{request.job_id}.pdf"
        
        # Convertir request a dict para el generador
        data = request.dict()
        
        # Generar el PDF
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
        raise HTTPException(
            status_code=500, 
            detail=f"Error generando PDF: {str(e)}\n{traceback.format_exc()}"
        )


@router.get("/health")
async def health_check():
    """Endpoint de health check para el servicio de reportes"""
    return {"status": "ok", "service": "reports"}
