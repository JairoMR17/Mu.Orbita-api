"""
Mu.Orbita API - Dashboard Router
Endpoints para el dashboard del cliente
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import date, datetime, timedelta
import httpx

from app.database import get_db
from app.models import Client, Parcel, Job, Kpi, Report
from app.schemas import (
    DashboardSummary, DashboardAlert,
    ParcelResponse, ParcelWithLatestKpi, ParcelCreate, ParcelUpdate,
    KpiResponse, KpiTimeSeries,
    JobResponse, ReportResponse
)
from app.dependencies import get_current_client, get_current_active_client

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


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
    
    # NDVI promedio últimos 30 días
    thirty_days_ago = date.today() - timedelta(days=30)
    parcel_ids = db.query(Parcel.id).filter(
        Parcel.client_id == current_client.id,
        Parcel.is_active == True
    ).all()
    parcel_ids = [p[0] for p in parcel_ids]
    
    avg_ndvi = None
    if parcel_ids:
        avg_ndvi = db.query(func.avg(Kpi.ndvi_mean)).filter(
            Kpi.parcel_id.in_(parcel_ids),
            Kpi.observation_date >= thirty_days_ago
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
    
    return DashboardSummary(
        client_name=current_client.client_name,
        total_parcels=total_parcels,
        total_hectares=float(total_hectares),
        total_reports=total_reports,
        avg_ndvi=float(avg_ndvi) if avg_ndvi else None,
        ndvi_trend="stable",  # TODO: calcular tendencia real
        last_analysis_date=last_job.completed_at if last_job else None,
        days_until_next_report=days_until_next,
        alerts_count=alerts_count
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
    # Calcular centroide del polígono (simplificado)
    centroid_lat = None
    centroid_lon = None
    
    if parcel.roi_geojson and "coordinates" in parcel.roi_geojson:
        coords = parcel.roi_geojson["coordinates"][0]  # Primer anillo del polígono
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
        six_months_ago = date.today() - timedelta(days=180)
        query = query.filter(Kpi.observation_date >= six_months_ago)
    
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
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Descarga PDF de un reporte
    """
    report = db.query(Report).filter(
        Report.id == report_id,
        Report.client_id == current_client.id
    ).first()
    
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reporte no encontrado"
        )
    
    if not report.pdf_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF no disponible"
        )
    
    # Si es URL de Google Drive, redirigir
    # Si es archivo local, servir directamente
    # Por ahora, redirigimos a la URL del PDF
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=report.pdf_url)


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
