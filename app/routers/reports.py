"""
Mu.Orbita Reports Router v1.1
- Añade images_base64 al modelo Pydantic (documentación)
- El endpoint sigue usando request.json() para pasar TODOS los campos
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional, List, Dict

router = APIRouter(prefix="/api/v1", tags=["Reports"])


class PDFRequest(BaseModel):
    job_id: str
    client_name: Optional[str] = "Cliente"
    crop_type: Optional[str] = "olivar"
    analysis_type: Optional[str] = "baseline"
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""
    area_hectares: Optional[float] = 0
    images_processed: Optional[int] = 0
    latest_image_date: Optional[str] = ""

    # Vegetation indices
    ndvi_mean: Optional[float] = 0
    ndvi_p10: Optional[float] = 0
    ndvi_p50: Optional[float] = 0
    ndvi_p90: Optional[float] = 0
    ndvi_stddev: Optional[float] = 0
    ndvi_zscore: Optional[float] = 0
    ndwi_mean: Optional[float] = 0
    ndwi_p10: Optional[float] = 0
    ndwi_p90: Optional[float] = 0
    evi_mean: Optional[float] = 0
    evi_p10: Optional[float] = 0
    evi_p90: Optional[float] = 0
    ndci_mean: Optional[float] = 0
    savi_mean: Optional[float] = 0

    # Stress & thermal
    stress_area_ha: Optional[float] = 0
    stress_area_pct: Optional[float] = 0
    lst_mean_c: Optional[float] = 0
    lst_min_c: Optional[float] = 0
    lst_max_c: Optional[float] = 0
    heterogeneity: Optional[float] = 0

    # Analysis text
    html_report: Optional[str] = ""
    markdown_analysis: Optional[str] = ""

    # Time series & images
    time_series: Optional[List[Dict]] = None
    png_images: Optional[List[Dict]] = None
    images_base64: Optional[Dict[str, str]] = None  # v1.1: GEE composites {NDVI: "base64...", ...}
    drive_images: Optional[List[Dict]] = None

    class Config:
        populate_by_name = True


@router.post("/generate-pdf")
async def generate_pdf(request: Request):
    """
    Genera un informe PDF profesional.
    
    Acepta imágenes satelitales en DOS formatos:
    - png_images: [{name: "NDVI", base64: "..."}, ...]  (array, from n8n)
    - images_base64: {NDVI: "base64...", NDWI: "base64..."}  (dict, direct from GEE)
    
    El generador v3.2 busca ambos y usa KEY_ALIASES para mapear claves.
    """
    try:
        from app.services.generate_pdf_report import generate_muorbita_report

        # Obtener JSON del request (bypasses Pydantic to pass ALL fields)
        raw_data = await request.json()

        # Si los datos vienen anidados en 'body', extraerlos
        if 'body' in raw_data and isinstance(raw_data['body'], dict):
            data = raw_data['body']
        else:
            data = raw_data

        # Normalizar time_series/timeseries
        if 'time_series' in data and 'timeseries' not in data:
            data['timeseries'] = data['time_series']

        # Log para debugging
        png_count = len(data.get('png_images', []) or [])
        b64_count = len(data.get('images_base64', {}) or {})
        print(f"📄 generate-pdf: job={data.get('job_id','?')} | png_images={png_count} | images_base64={b64_count}")

        result = generate_muorbita_report(data)

        return result

    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=500,
            detail=f"Error generando PDF: {str(e)}\n{traceback.format_exc()}"
        )


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "reports"}
