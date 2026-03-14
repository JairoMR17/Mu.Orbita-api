"""
Mu.Orbita API - Dashboard Router
Endpoints para el dashboard del cliente
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import date, datetime, timedelta
from pydantic import BaseModel
import json
import uuid

from app.database import get_db
from app.models import Client, Parcel, Job, Kpi, Report
from app.models.gee_image import GEEImage
from app.schemas import (
    DashboardSummary, DashboardAlert,
    ParcelResponse, ParcelWithLatestKpi, ParcelCreate, ParcelUpdate,
    KpiResponse, KpiTimeSeries,
    JobResponse, ReportResponse
)
from app.dependencies import get_current_client, get_current_active_client

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ============================================================================
# HELPER: Parsear GeoJSON (puede venir como string o dict)
# ============================================================================

def parse_geojson(roi_geojson):
    """Parsea GeoJSON que puede estar como string o dict, con múltiples niveles de encoding"""
    if roi_geojson is None:
        return None
    
    parsed = roi_geojson
    
    # Parsear mientras sea string (puede haber doble encoding)
    while isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return None
    
    return parsed


def extract_geometry(geojson):
    """Extrae la geometría de un GeoJSON (Feature, FeatureCollection, o Geometry directa)"""
    if geojson is None:
        return None
    
    if geojson.get("type") == "Feature":
        return geojson.get("geometry")
    elif geojson.get("type") == "FeatureCollection":
        features = geojson.get("features", [])
        if features:
            return features[0].get("geometry")
    elif geojson.get("type") in ["Polygon", "MultiPolygon"]:
        return geojson
    
    return None


def calculate_bounds(geometry):
    """Calcula bounds de una geometría"""
    if geometry is None:
        return None
    
    coords = []
    geom_type = geometry.get("type")
    
    if geom_type == "Polygon":
        coords = geometry.get("coordinates", [[]])[0]
    elif geom_type == "MultiPolygon":
        # Flatten all coordinates from all polygons
        for polygon in geometry.get("coordinates", []):
            if polygon:
                coords.extend(polygon[0])
    
    if not coords:
        return None
    
    lngs = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    
    return {
        "south": min(lats),
        "west": min(lngs),
        "north": max(lats),
        "east": max(lngs)
    }


# ============================================================================
# SUMMARY
# ============================================================================

@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene resumen general para el dashboard principal
    """
    # Contar parcelas
    total_parcels = db.query(func.count(Parcel.id)).filter(
        Parcel.client_id == current_client.id,
        Parcel.is_active == True
    ).scalar() or 0
    
    # Sumar hectáreas
    total_hectares = db.query(func.sum(Parcel.hectares)).filter(
        Parcel.client_id == current_client.id,
        Parcel.is_active == True
    ).scalar() or 0
    
    # Contar reportes
    total_reports = db.query(func.count(Report.id)).filter(
        Report.client_id == current_client.id
    ).scalar() or 0
    
    # Último análisis
    last_job = db.query(Job).filter(
        Job.client_id == current_client.id,
        Job.status == "completed"
    ).order_by(desc(Job.completed_at)).first()
    
    # NDVI promedio últimos 90 días
    ninety_days_ago = date.today() - timedelta(days=90)
    parcel_ids = db.query(Parcel.id).filter(
        Parcel.client_id == current_client.id,
        Parcel.is_active == True
    ).all()
    parcel_ids = [p[0] for p in parcel_ids]
    
    avg_ndvi = None
    avg_ndwi = None
    stress_area_pct = None
    if parcel_ids:
        avg_ndvi = db.query(func.avg(Kpi.ndvi_mean)).filter(
            Kpi.parcel_id.in_(parcel_ids),
            Kpi.observation_date >= ninety_days_ago
        ).scalar()
        
        avg_ndwi = db.query(func.avg(Kpi.ndwi_mean)).filter(
            Kpi.parcel_id.in_(parcel_ids),
            Kpi.observation_date >= ninety_days_ago
        ).scalar()
        
        stress_area_pct = db.query(func.avg(Kpi.stress_area_pct)).filter(
            Kpi.parcel_id.in_(parcel_ids),
            Kpi.observation_date >= ninety_days_ago
        ).scalar()
    
    # Contar alertas (parcelas con estrés)
    alerts_count = 0
    if parcel_ids:
        # Subquery para último KPI de cada parcela
        latest_kpis = db.query(Kpi).filter(
            Kpi.parcel_id.in_(parcel_ids)
        ).order_by(Kpi.parcel_id, desc(Kpi.observation_date)).distinct(Kpi.parcel_id).all()
        
        alerts_count = sum(1 for k in latest_kpis if k.ndvi_mean and k.ndvi_mean < 0.45)
    
    # Días hasta próximo informe (asumiendo bisemanales)
    days_until_next = None
    if last_job and last_job.completed_at:
        next_report_date = last_job.completed_at + timedelta(days=14)
        days_until_next = (next_report_date.date() - date.today()).days
        if days_until_next < 0:
            days_until_next = 0
    
    # Obtener datos fenológicos del último job si existen
    pheno_phase = None
    pheno_status = None
    ndvi_expected = None
    ndvi_deviation_pct = None
    
    if last_job:
        pheno_phase = getattr(last_job, 'pheno_phase', None)
        pheno_status = getattr(last_job, 'pheno_status', None)
        ndvi_expected = getattr(last_job, 'ndvi_expected', None)
        ndvi_deviation_pct = getattr(last_job, 'ndvi_deviation_pct', None)
    
    return DashboardSummary(
        client_name=current_client.client_name,
        total_parcels=total_parcels,
        total_hectares=float(total_hectares),
        total_reports=total_reports,
        avg_ndvi=float(avg_ndvi) if avg_ndvi else None,
        avg_ndwi=float(avg_ndwi) if avg_ndwi else None,
        stress_area_pct=float(stress_area_pct) if stress_area_pct else None,
        ndvi_trend="stable",  # TODO: calcular tendencia real
        last_analysis_date=last_job.completed_at if last_job else None,
        days_until_next_report=days_until_next,
        alerts_count=alerts_count,
        # Campos fenológicos
        pheno_phase=pheno_phase,
        pheno_status=pheno_status,
        ndvi_expected=float(ndvi_expected) if ndvi_expected else None,
        ndvi_deviation_pct=float(ndvi_deviation_pct) if ndvi_deviation_pct else None
    )


# ============================================================================
# PARCELS
# ============================================================================

@router.get("/parcels", response_model=List[ParcelWithLatestKpi])
async def get_parcels(
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene todas las parcelas del cliente con su último KPI
    """
    parcels = db.query(Parcel).filter(
        Parcel.client_id == current_client.id,
        Parcel.is_active == True
    ).all()
    
    result = []
    for parcel in parcels:
        # Obtener último KPI
        latest_kpi = db.query(Kpi).filter(
            Kpi.parcel_id == parcel.id
        ).order_by(desc(Kpi.observation_date)).first()
        
        parcel_data = ParcelWithLatestKpi(
            id=parcel.id,
            client_id=parcel.client_id,
            parcel_name=parcel.parcel_name,
            parcel_code=parcel.parcel_code,
            hectares=float(parcel.hectares),
            crop_type=parcel.crop_type,
            crop_variety=parcel.crop_variety,
            planting_year=parcel.planting_year,
            irrigation_type=parcel.irrigation_type,
            location_name=parcel.location_name,
            municipality=parcel.municipality,
            province=parcel.province,
            roi_geojson=parcel.roi_geojson,
            is_active=parcel.is_active,
            centroid_lat=float(parcel.centroid_lat) if parcel.centroid_lat else None,
            centroid_lon=float(parcel.centroid_lon) if parcel.centroid_lon else None,
            created_at=parcel.created_at,
            latest_ndvi=float(latest_kpi.ndvi_mean) if latest_kpi and latest_kpi.ndvi_mean else None,
            latest_ndwi=float(latest_kpi.ndwi_mean) if latest_kpi and latest_kpi.ndwi_mean else None,
            latest_observation_date=latest_kpi.observation_date if latest_kpi else None,
            stress_area_pct=float(latest_kpi.stress_area_pct) if latest_kpi and latest_kpi.stress_area_pct else None
        )
        result.append(parcel_data)
    
    return result


@router.post("/parcels", response_model=ParcelResponse)
async def create_parcel(
    parcel: ParcelCreate,
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Crea una nueva parcela para el cliente
    """
    # Calcular centroide del polígono
    centroid_lat = None
    centroid_lon = None
    
    if parcel.roi_geojson:
        parsed = parse_geojson(parcel.roi_geojson)
        geometry = extract_geometry(parsed)
        
        if geometry and geometry.get("coordinates"):
            coords = geometry["coordinates"][0] if geometry["type"] == "Polygon" else geometry["coordinates"][0][0]
            if coords:
                lats = [c[1] for c in coords]
                lons = [c[0] for c in coords]
                centroid_lat = sum(lats) / len(lats)
                centroid_lon = sum(lons) / len(lons)
    
    new_parcel = Parcel(
        client_id=current_client.id,
        parcel_name=parcel.parcel_name,
        parcel_code=parcel.parcel_code,
        hectares=parcel.hectares,
        crop_type=parcel.crop_type,
        crop_variety=parcel.crop_variety,
        planting_year=parcel.planting_year,
        irrigation_type=parcel.irrigation_type,
        location_name=parcel.location_name,
        municipality=parcel.municipality,
        province=parcel.province,
        roi_geojson=parcel.roi_geojson,
        centroid_lat=centroid_lat,
        centroid_lon=centroid_lon,
    )
    
    db.add(new_parcel)
    db.commit()
    db.refresh(new_parcel)
    
    return new_parcel


@router.get("/parcels/{parcel_id}", response_model=ParcelWithLatestKpi)
async def get_parcel(
    parcel_id: str,
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene detalle de una parcela específica
    """
    parcel = db.query(Parcel).filter(
        Parcel.id == parcel_id,
        Parcel.client_id == current_client.id
    ).first()
    
    if not parcel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parcela no encontrada"
        )
    
    # Último KPI
    latest_kpi = db.query(Kpi).filter(
        Kpi.parcel_id == parcel.id
    ).order_by(desc(Kpi.observation_date)).first()
    
    return ParcelWithLatestKpi(
        id=parcel.id,
        client_id=parcel.client_id,
        parcel_name=parcel.parcel_name,
        parcel_code=parcel.parcel_code,
        hectares=float(parcel.hectares),
        crop_type=parcel.crop_type,
        crop_variety=parcel.crop_variety,
        planting_year=parcel.planting_year,
        irrigation_type=parcel.irrigation_type,
        location_name=parcel.location_name,
        municipality=parcel.municipality,
        province=parcel.province,
        roi_geojson=parcel.roi_geojson,
        is_active=parcel.is_active,
        centroid_lat=float(parcel.centroid_lat) if parcel.centroid_lat else None,
        centroid_lon=float(parcel.centroid_lon) if parcel.centroid_lon else None,
        created_at=parcel.created_at,
        latest_ndvi=float(latest_kpi.ndvi_mean) if latest_kpi and latest_kpi.ndvi_mean else None,
        latest_ndwi=float(latest_kpi.ndwi_mean) if latest_kpi and latest_kpi.ndwi_mean else None,
        latest_observation_date=latest_kpi.observation_date if latest_kpi else None,
        stress_area_pct=float(latest_kpi.stress_area_pct) if latest_kpi and latest_kpi.stress_area_pct else None
    )


@router.patch("/parcels/{parcel_id}", response_model=ParcelResponse)
async def update_parcel(
    parcel_id: str,
    parcel_update: ParcelUpdate,
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Actualiza una parcela
    """
    parcel = db.query(Parcel).filter(
        Parcel.id == parcel_id,
        Parcel.client_id == current_client.id
    ).first()
    
    if not parcel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parcela no encontrada"
        )
    
    # Actualizar solo campos proporcionados
    update_data = parcel_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(parcel, field, value)
    
    db.commit()
    db.refresh(parcel)
    
    return parcel


@router.delete("/parcels/{parcel_id}")
async def delete_parcel(
    parcel_id: str,
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Desactiva una parcela (soft delete)
    """
    parcel = db.query(Parcel).filter(
        Parcel.id == parcel_id,
        Parcel.client_id == current_client.id
    ).first()
    
    if not parcel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parcela no encontrada"
        )
    
    parcel.is_active = False
    db.commit()
    
    return {"message": "Parcela desactivada correctamente"}


# ============================================================================
# KPIs
# ============================================================================

@router.get("/parcels/{parcel_id}/kpis", response_model=List[KpiTimeSeries])
async def get_parcel_kpis(
    parcel_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene serie temporal de KPIs de una parcela (para gráficas)
    """
    # Verificar que la parcela pertenece al cliente
    parcel = db.query(Parcel).filter(
        Parcel.id == parcel_id,
        Parcel.client_id == current_client.id
    ).first()
    
    if not parcel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parcela no encontrada"
        )
    
    # Query KPIs
    query = db.query(Kpi).filter(Kpi.parcel_id == parcel_id)
    
    if start_date:
        query = query.filter(Kpi.observation_date >= start_date)
    if end_date:
        query = query.filter(Kpi.observation_date <= end_date)
    
    # Por defecto, últimos 6 meses
    if not start_date and not end_date:
        one_year_ago = date.today() - timedelta(days=365)
        query = query.filter(Kpi.observation_date >= one_year_ago)
    
    kpis = query.order_by(Kpi.observation_date).all()
    
    return [
        KpiTimeSeries(
            observation_date=k.observation_date,
            ndvi_mean=float(k.ndvi_mean) if k.ndvi_mean else None,
            ndvi_p10=float(k.ndvi_p10) if k.ndvi_p10 else None,
            ndvi_p90=float(k.ndvi_p90) if k.ndvi_p90 else None,
            ndwi_mean=float(k.ndwi_mean) if k.ndwi_mean else None,
            stress_area_pct=float(k.stress_area_pct) if k.stress_area_pct else None
        )
        for k in kpis
    ]


# ============================================================================
# JOBS
# ============================================================================

@router.get("/jobs", response_model=List[JobResponse])
async def get_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene historial de jobs del cliente
    """
    query = db.query(Job).filter(Job.client_id == current_client.id)
    
    if status:
        query = query.filter(Job.status == status)
    
    jobs = query.order_by(desc(Job.created_at)).offset(offset).limit(limit).all()
    
    return jobs


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene detalle de un job específico
    """
    job = db.query(Job).filter(
        Job.job_id == job_id,
        Job.client_id == current_client.id
    ).first()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job no encontrado"
        )
    
    return job


# ============================================================================
# REPORTS
# ============================================================================

@router.get("/reports", response_model=List[ReportResponse])
async def get_reports(
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene historial de reportes del cliente
    """
    reports = db.query(Report).filter(
        Report.client_id == current_client.id
    ).order_by(desc(Report.generated_at)).offset(offset).limit(limit).all()
    
    return reports


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: str,
    db: Session = Depends(get_db)
):
    try:
        report_uuid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de reporte inválido")

    report = db.query(Report).filter(Report.id == report_uuid).first()

    if not report:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")

    if not report.pdf_url:
        raise HTTPException(status_code=404, detail="PDF no disponible")

    pdf_url = report.pdf_url
    if 'drive.google.com/file/d/' in pdf_url:
        file_id = pdf_url.split('/file/d/')[1].split('/')[0]
        pdf_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    return {"url": pdf_url}

# ============================================================================
# REPORTS - Guardar Link en BD (llamado desde n8n)
# ============================================================================

class ReportLinkCreate(BaseModel):
    job_id_string: str
    client_email: str
    report_type: str = "baseline"
    pdf_url: Optional[str] = None
    pdf_drive_id: Optional[str] = None


@router.post("/reports/register")
async def create_report_link(
    data: ReportLinkCreate,
    db: Session = Depends(get_db)
):
    """
    Crea o actualiza registro de reporte con link de Google Drive (llamado desde n8n).
    UPSERT: si job-completed ya creó el report, solo actualiza pdf_url/pdf_drive_id.
    """
    # Buscar job por job_id string
    job = db.query(Job).filter(Job.job_id == data.job_id_string).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job no encontrado: {data.job_id_string}"
        )
    
    # Buscar client por email
    client = db.query(Client).filter(Client.email == data.client_email).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente no encontrado: {data.client_email}"
        )
    
    # ── UPSERT: buscar report existente por job_id ──
    existing_report = db.query(Report).filter(
        Report.job_id == job.id
    ).first()
    
    if existing_report:
        # Ya existe (creado por job-completed) → actualizar con datos de Drive
        if data.pdf_url:
            existing_report.pdf_url = data.pdf_url
        if data.pdf_drive_id:
            existing_report.pdf_drive_id = data.pdf_drive_id
        db.commit()
        db.refresh(existing_report)
        print(f"📝 Report actualizado con Drive URL para job {data.job_id_string}")
        return {
            "success": True,
            "report_id": str(existing_report.id),
            "pdf_url": existing_report.pdf_url,
            "action": "updated"
        }
    
    # No existe → crear nuevo
    new_report = Report(
        job_id=job.id,
        client_id=client.id,
        report_type=data.report_type,
        pdf_url=data.pdf_url,
    )
    
    db.add(new_report)
    db.commit()
    db.refresh(new_report)
    
    return {
        "success": True,
        "report_id": str(new_report.id),
        "pdf_url": data.pdf_url,
        "action": "created"
    }


# ============================================================================
# ALERTS
# ============================================================================

@router.get("/alerts", response_model=List[DashboardAlert])
async def get_alerts(
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene alertas activas (parcelas con estrés)
    """
    parcels = db.query(Parcel).filter(
        Parcel.client_id == current_client.id,
        Parcel.is_active == True
    ).all()
    
    alerts = []
    for parcel in parcels:
        latest_kpi = db.query(Kpi).filter(
            Kpi.parcel_id == parcel.id
        ).order_by(desc(Kpi.observation_date)).first()
        
        if not latest_kpi:
            continue
        
        # Verificar umbrales
        if latest_kpi.ndvi_mean and latest_kpi.ndvi_mean < 0.35:
            alerts.append(DashboardAlert(
                parcel_id=parcel.id,
                parcel_name=parcel.parcel_name,
                alert_type="stress",
                severity="critical",
                message=f"NDVI crítico: {latest_kpi.ndvi_mean:.2f}. Requiere inspección inmediata.",
                detected_at=latest_kpi.created_at
            ))
        elif latest_kpi.ndvi_mean and latest_kpi.ndvi_mean < 0.45:
            alerts.append(DashboardAlert(
                parcel_id=parcel.id,
                parcel_name=parcel.parcel_name,
                alert_type="low_vigor",
                severity="warning",
                message=f"NDVI bajo: {latest_kpi.ndvi_mean:.2f}. Monitorizar evolución.",
                detected_at=latest_kpi.created_at
            ))
        
        if latest_kpi.stress_area_pct and latest_kpi.stress_area_pct > 20:
            alerts.append(DashboardAlert(
                parcel_id=parcel.id,
                parcel_name=parcel.parcel_name,
                alert_type="stress_area",
                severity="warning",
                message=f"{latest_kpi.stress_area_pct:.1f}% del área con estrés.",
                detected_at=latest_kpi.created_at
            ))
    
    return alerts


# ============================================================================
# MAP DATA - Datos para capas satelitales
# ============================================================================

@router.get("/parcels/{parcel_id}/map-data")
async def get_parcel_map_data(
    parcel_id: str,
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene datos completos para renderizar el mapa con capas satelitales.
    Incluye: geometría, bounds, KPIs, y URLs de imágenes PNG.
    """
    # Verificar parcela
    parcel = db.query(Parcel).filter(
        Parcel.id == parcel_id,
        Parcel.client_id == current_client.id
    ).first()
    
    if not parcel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parcela no encontrada"
        )
    
    # Obtener último job completado para esta parcela
    last_job = db.query(Job).filter(
        Job.client_id == current_client.id,
        Job.status == "completed"
    ).order_by(desc(Job.completed_at)).first()
    
    # Parsear ROI y calcular bounds
    parsed_roi = parse_geojson(parcel.roi_geojson)
    geometry = extract_geometry(parsed_roi)
    bounds = calculate_bounds(geometry)
    
    # Obtener último KPI
    latest_kpi = db.query(Kpi).filter(
        Kpi.parcel_id == parcel.id
    ).order_by(desc(Kpi.observation_date)).first()
    
    # Obtener URLs de imágenes si hay job
    images = {}
    job_id = None
    if last_job:
        job_id = last_job.job_id
        
        # Buscar imágenes registradas para este job
        try:
            gee_images = db.query(GEEImage).filter(
                GEEImage.job_id == job_id,
                GEEImage.png_base64.isnot(None)   # solo imágenes que realmente tienen datos
            ).all()

            for img in gee_images:
                images[img.index_type] = f"/api/images/{job_id}/{img.filename}"
        except Exception as e:
            # Si la tabla GEEImage no existe o hay error, continuar sin imágenes
            print(f"Warning: Could not fetch GEE images: {e}")
    
    # Construir respuesta
    return {
        "parcel_id": parcel_id,
        "parcel_name": parcel.parcel_name,
        "job_id": job_id,
        
        "farm": {
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "name": parcel.parcel_name,
                "hectareas": float(parcel.hectares) if parcel.hectares else None,
                "tipo_cultivo": parcel.crop_type,
                "ubicacion": parcel.location_name or parcel.municipality
            }
        } if geometry else None,
        
        "bounds": bounds,
        
        "kpis": {
            "ndvi_mean": float(latest_kpi.ndvi_mean) if latest_kpi and latest_kpi.ndvi_mean else None,
            "ndvi_p10": float(latest_kpi.ndvi_p10) if latest_kpi and latest_kpi.ndvi_p10 else None,
            "ndvi_p90": float(latest_kpi.ndvi_p90) if latest_kpi and latest_kpi.ndvi_p90 else None,
            "ndwi_mean": float(latest_kpi.ndwi_mean) if latest_kpi and latest_kpi.ndwi_mean else None,
            "stress_area_pct": float(latest_kpi.stress_area_pct) if latest_kpi and latest_kpi.stress_area_pct else None,
            "observation_date": latest_kpi.observation_date.isoformat() if latest_kpi and latest_kpi.observation_date else None,
            "bounds_south": bounds["south"] if bounds else None,
            "bounds_west": bounds["west"] if bounds else None,
            "bounds_north": bounds["north"] if bounds else None,
            "bounds_east": bounds["east"] if bounds else None,
        } if latest_kpi or bounds else None,
        
        "images": images if images else None,
        
        "has_satellite_layers": len(images) > 0
    }


@router.get("/map-data")
async def get_client_map_data(
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene datos del mapa para la primera parcela activa del cliente.
    Útil para el dashboard principal.
    """
    # Obtener primera parcela activa
    parcel = db.query(Parcel).filter(
        Parcel.client_id == current_client.id,
        Parcel.is_active == True
    ).first()
    
    if not parcel:
        return {
            "error": "No hay parcelas activas",
            "bounds": None,
            "images": None,
            "has_satellite_layers": False
        }
    
    # Reutilizar el endpoint de parcela específica
    return await get_parcel_map_data(
        parcel_id=str(parcel.id),
        current_client=current_client,
        db=db
    )
