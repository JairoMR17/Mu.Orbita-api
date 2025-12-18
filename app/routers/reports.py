from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional, Any, List, Dict
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
    
    # NDVI
    ndvi_mean: Optional[float] = 0
    ndvi_p10: Optional[float] = 0
    ndvi_p50: Optional[float] = 0
    ndvi_p90: Optional[float] = 0
    ndvi_stddev: Optional[float] = 0
    ndvi_zscore: Optional[float] = 0
    
    # NDWI
    ndwi_mean: Optional[float] = 0
    ndwi_p10: Optional[float] = 0
    ndwi_p90: Optional[float] = 0
    
    # EVI
    evi_mean: Optional[float] = 0
    evi_p10: Optional[float] = 0
    evi_p90: Optional[float] = 0
    
    # Otros índices
    ndci_mean: Optional[float] = 0
    savi_mean: Optional[float] = 0
    
    # Estrés
    stress_area_ha: Optional[float] = 0
    stress_area_pct: Optional[float] = 0
    
    # Temperatura
    lst_mean_c: Optional[float] = 0
    lst_min_c: Optional[float] = 0
    lst_max_c: Optional[float] = 0
    
    # Heterogeneidad
    heterogeneity: Optional[float] = 0
    
    # Contenido
    html_report: Optional[str] = ""
    markdown_analysis: Optional[str] = ""
    
    # Series temporales - acepta ambos nombres
    time_series: Optional[List[Dict]] = Field(default=None, alias="timeseries")
    
    class Config:
        populate_by_name = True


@router.post("/generate-pdf")
async def generate_pdf(request: Request):
    """
    Genera un informe PDF profesional.
    Acepta datos directamente o anidados en 'body'.
    """
    try:
        # Obtener JSON del request
        raw_data = await request.json()
        
        # Si los datos vienen anidados en 'body', extraerlos
        if 'body' in raw_data and isinstance(raw_data['body'], dict):
            data = raw_data['body']
        else:
            data = raw_data
        
        # Normalizar time_series/timeseries
        if 'time_series' in data and 'timeseries' not in data:
            data['timeseries'] = data['time_series']
        
        # Validar con Pydantic
        pdf_request = PDFRequest(**data)
        
        from app.services.generate_pdf_report import generate_report
        
        output_path = f"/tmp/Informe_{pdf_request.job_id}.pdf"
        
        # Convertir a dict para el generador
        report_data = pdf_request.model_dump(by_alias=False)
        
        # Asegurar que time_series esté disponible
        if pdf_request.time_series:
            report_data['time_series'] = pdf_request.time_series
        elif 'time_series' in data:
            report_data['time_series'] = data['time_series']
        
        # Generar el PDF
        generate_report(report_data, output_path)
        
        # Leer y convertir a base64
        with open(output_path, 'rb') as f:
            pdf_bytes = f.read()
        
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        return {
            "success": True,
            "job_id": pdf_request.job_id,
            "pdf_path": output_path,
            "pdf_base64": pdf_base64,
            "filename": f"Informe_MUORBITA_{pdf_request.job_id}.pdf",
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
    return {"status": "ok", "service": "reports"}
