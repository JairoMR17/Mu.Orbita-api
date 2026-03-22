"""
Mu.Orbita API - Dashboard Router
Endpoints para el dashboard del cliente

v2.0 — Dashboard Professional Upgrade
──────────────────────────────────────
CAMBIOS vs v1.x:
  1. FIX:  get_parcel_kpis() ahora devuelve evi_mean (faltaba en KpiTimeSeries)
  2. FIX:  download_report() ahora requiere autenticación del cliente
  3. NEW:  /recommendations — Recomendaciones del último informe
  4. NEW:  /weather-forecast — Proxy Open-Meteo con centroide de la parcela
  5. NEW:  /climate-summary — Resumen climático últimas 2 semanas (ERA5 de KPIs)
  6. NEW:  /summary ahora incluye deltas, EVI, risk levels del último report
  7. NEW:  Modelos Pydantic extendidos definidos inline (no rompe schemas.py)
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional, Any
from datetime import date, datetime, timedelta
from pydantic import BaseModel
from uuid import UUID
import json
import uuid
import httpx

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
# v2.0: MODELOS EXTENDIDOS (inline — no modifica schemas.py)
# ============================================================================

class KpiTimeSeriesV2(BaseModel):
    """Timeseries extendido con EVI + campos climáticos para dashboard v2"""
    observation_date: date
    ndvi_mean: Optional[float] = None
    ndvi_p10: Optional[float] = None
    ndvi_p90: Optional[float] = None
    ndwi_mean: Optional[float] = None
    evi_mean: Optional[float] = None
    stress_area_pct: Optional[float] = None
    # Clima (opcional — solo los que tengan datos)
    lst_mean: Optional[float] = None
    tmax_mean: Optional[float] = None
    precip_mm: Optional[float] = None


class DashboardSummaryV2(BaseModel):
    """Summary extendido con deltas, EVI, risk levels"""
    # --- Campos originales ---
    client_name: str
    total_parcels: int
    total_hectares: float
    total_reports: int
    avg_ndvi: Optional[float] = None
    avg_ndwi: Optional[float] = None
    avg_evi: Optional[float] = None                     # NEW
    stress_area_pct: Optional[float] = None
    ndvi_trend: Optional[str] = None
    last_analysis_date: Optional[datetime] = None
    days_until_next_report: Optional[int] = None
    alerts_count: int = 0
    # Fenológicos
    pheno_phase: Optional[str] = None
    pheno_status: Optional[str] = None
    ndvi_expected: Optional[float] = None
    ndvi_deviation_pct: Optional[float] = None
    # --- v2.0: Deltas vs informe anterior ---
    ndvi_delta: Optional[float] = None                  # NEW
    ndvi_delta_pct: Optional[float] = None              # NEW
    ndwi_delta: Optional[float] = None                  # NEW
    evi_delta: Optional[float] = None                   # NEW
    stress_delta: Optional[float] = None                # NEW
    # --- v2.0: Risk levels del último report ---
    risk_hydric_level: Optional[str] = None             # NEW
    risk_thermal_level: Optional[str] = None            # NEW
    risk_heterogeneity_level: Optional[str] = None      # NEW


class RecommendationItem(BaseModel):
    """Recomendación individual del informe"""
    title: str
    priority: str
    deadline_days: int
    trigger: Optional[str] = None
    zone: Optional[str] = None
    justification: Optional[str] = None


class RecommendationsResponse(BaseModel):
    """Respuesta del endpoint de recomendaciones"""
    recommendations: List[RecommendationItem]
    report_type: Optional[str] = None
    report_date: Optional[str] = None
    report_id: Optional[str] = None


class ClimateSummaryResponse(BaseModel):
    """Resumen climático de las últimas semanas"""
    period_days: int
    tmax_mean: Optional[float] = None
    tmin_mean: Optional[float] = None
    precip_total_mm: Optional[float] = None
    lst_mean: Optional[float] = None
    observations_count: int = 0


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
# v2.0 HELPER: Extraer risk levels de report_metadata o narratives
# ============================================================================

def _extract_risk_levels(report: Report) -> dict:
    """Extrae risk levels del último report (desde report_metadata o recommendations)"""
    result = {
        "risk_hydric_level": None,
        "risk_thermal_level": None,
        "risk_heterogeneity_level": None,
    }
    if not report or not report.report_metadata:
        return result

    meta = report.report_metadata
    # Si el PDF generator guardó los risk levels en metadata
    result["risk_hydric_level"] = meta.get("risk_hydric_level")
    result["risk_thermal_level"] = meta.get("risk_thermal_level")
    result["risk_heterogeneity_level"] = meta.get("risk_heterogeneity_level")
    return result


# ============================================================================
# SUMMARY  —  v2.0: ampliado con deltas, EVI, risk levels
# ============================================================================

@router.get("/summary", response_model=DashboardSummaryV2)
async def get_dashboard_summary(
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene resumen general para el dashboard principal.
    v2.0: incluye deltas vs último informe, EVI, y risk levels.
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
    
    # IDs de parcelas activas
    parcel_ids = db.query(Parcel.id).filter(
        Parcel.client_id == current_client.id,
        Parcel.is_active == True
    ).all()
    parcel_ids = [p[0] for p in parcel_ids]
    
    # ── KPIs promedio últimos 90 días ──
    avg_ndvi = None
    avg_ndwi = None
    avg_evi = None
    stress_area_pct = None
    if parcel_ids:
        ninety_days_ago = date.today() - timedelta(days=90)
        
        avg_ndvi = db.query(func.avg(Kpi.ndvi_mean)).filter(
            Kpi.parcel_id.in_(parcel_ids),
            Kpi.observation_date >= ninety_days_ago
        ).scalar()
        
        avg_ndwi = db.query(func.avg(Kpi.ndwi_mean)).filter(
            Kpi.parcel_id.in_(parcel_ids),
            Kpi.observation_date >= ninety_days_ago
        ).scalar()
        
        avg_evi = db.query(func.avg(Kpi.evi_mean)).filter(
            Kpi.parcel_id.in_(parcel_ids),
            Kpi.observation_date >= ninety_days_ago
        ).scalar()
        
        stress_area_pct = db.query(func.avg(Kpi.stress_area_pct)).filter(
            Kpi.parcel_id.in_(parcel_ids),
            Kpi.observation_date >= ninety_days_ago
        ).scalar()
    
    # ── v2.0: Calcular deltas entre los 2 últimos KPIs ──
    ndvi_delta = None
    ndvi_delta_pct = None
    ndwi_delta = None
    evi_delta = None
    stress_delta = None
    
    if parcel_ids:
        # Últimos 2 KPIs de la primera parcela (ordenados desc)
        last_two_kpis = db.query(Kpi).filter(
            Kpi.parcel_id.in_(parcel_ids),
            Kpi.ndvi_mean.isnot(None)
        ).order_by(desc(Kpi.observation_date)).limit(2).all()
        
        if len(last_two_kpis) >= 2:
            curr = last_two_kpis[0]
            prev = last_two_kpis[1]
            
            if curr.ndvi_mean is not None and prev.ndvi_mean is not None:
                ndvi_delta = float(curr.ndvi_mean) - float(prev.ndvi_mean)
                if float(prev.ndvi_mean) > 0:
                    ndvi_delta_pct = (ndvi_delta / float(prev.ndvi_mean)) * 100
            
            if curr.ndwi_mean is not None and prev.ndwi_mean is not None:
                ndwi_delta = float(curr.ndwi_mean) - float(prev.ndwi_mean)
            
            if curr.evi_mean is not None and prev.evi_mean is not None:
                evi_delta = float(curr.evi_mean) - float(prev.evi_mean)
            
            if curr.stress_area_pct is not None and prev.stress_area_pct is not None:
                stress_delta = float(curr.stress_area_pct) - float(prev.stress_area_pct)
    
    # ── Contar alertas ──
    alerts_count = 0
    if parcel_ids:
        latest_kpis = db.query(Kpi).filter(
            Kpi.parcel_id.in_(parcel_ids)
        ).order_by(Kpi.parcel_id, desc(Kpi.observation_date)).distinct(Kpi.parcel_id).all()
        
        alerts_count = sum(1 for k in latest_kpis if k.ndvi_mean and k.ndvi_mean < 0.45)
    
    # ── Días hasta próximo informe ──
    days_until_next = None
    if last_job and last_job.completed_at:
        next_report_date = last_job.completed_at + timedelta(days=14)
        days_until_next = (next_report_date.date() - date.today()).days
        if days_until_next < 0:
            days_until_next = 0
    
    # ── Datos fenológicos del último job ──
    pheno_phase = None
    pheno_status = None
    ndvi_expected = None
    ndvi_deviation_pct = None
    
    if last_job:
        pheno_phase = getattr(last_job, 'pheno_phase', None)
        pheno_status = getattr(last_job, 'pheno_status', None)
        ndvi_expected = getattr(last_job, 'ndvi_expected', None)
        ndvi_deviation_pct = getattr(last_job, 'ndvi_deviation_pct', None)
    
    # ── v2.0: Risk levels del último report ──
    risk_levels = {"risk_hydric_level": None, "risk_thermal_level": None, "risk_heterogeneity_level": None}
    latest_report = db.query(Report).filter(
        Report.client_id == current_client.id,
        Report.report_type.in_(["baseline", "biweekly"])
    ).order_by(desc(Report.generated_at)).first()
    
    if latest_report:
        risk_levels = _extract_risk_levels(latest_report)
    
    # ── Tendencia NDVI (simple: comparar último vs anterior) ──
    ndvi_trend = "stable"
    if ndvi_delta is not None:
        if ndvi_delta > 0.02:
            ndvi_trend = "up"
        elif ndvi_delta < -0.02:
            ndvi_trend = "down"
    
    return DashboardSummaryV2(
        client_name=current_client.client_name,
        total_parcels=total_parcels,
        total_hectares=float(total_hectares),
        total_reports=total_reports,
        avg_ndvi=round(float(avg_ndvi), 3) if avg_ndvi else None,
        avg_ndwi=round(float(avg_ndwi), 3) if avg_ndwi else None,
        avg_evi=round(float(avg_evi), 3) if avg_evi else None,
        stress_area_pct=round(float(stress_area_pct), 1) if stress_area_pct else None,
        ndvi_trend=ndvi_trend,
        last_analysis_date=last_job.completed_at if last_job else None,
        days_until_next_report=days_until_next,
        alerts_count=alerts_count,
        # Fenológicos
        pheno_phase=pheno_phase,
        pheno_status=pheno_status,
        ndvi_expected=float(ndvi_expected) if ndvi_expected else None,
        ndvi_deviation_pct=float(ndvi_deviation_pct) if ndvi_deviation_pct else None,
        # v2.0: Deltas
        ndvi_delta=round(ndvi_delta, 3) if ndvi_delta is not None else None,
        ndvi_delta_pct=round(ndvi_delta_pct, 1) if ndvi_delta_pct is not None else None,
        ndwi_delta=round(ndwi_delta, 3) if ndwi_delta is not None else None,
        evi_delta=round(evi_delta, 3) if evi_delta is not None else None,
        stress_delta=round(stress_delta, 1) if stress_delta is not None else None,
        # v2.0: Risk levels
        **risk_levels,
    )


# ============================================================================
# PARCELS  (sin cambios)
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
    """Crea una nueva parcela para el cliente"""
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
    """Obtiene detalle de una parcela específica"""
    parcel = db.query(Parcel).filter(
        Parcel.id == parcel_id,
        Parcel.client_id == current_client.id
    ).first()
    
    if not parcel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parcela no encontrada")
    
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
    """Actualiza una parcela"""
    parcel = db.query(Parcel).filter(
        Parcel.id == parcel_id,
        Parcel.client_id == current_client.id
    ).first()
    
    if not parcel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parcela no encontrada")
    
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
    """Desactiva una parcela (soft delete)"""
    parcel = db.query(Parcel).filter(
        Parcel.id == parcel_id,
        Parcel.client_id == current_client.id
    ).first()
    
    if not parcel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parcela no encontrada")
    
    parcel.is_active = False
    db.commit()
    
    return {"message": "Parcela desactivada correctamente"}


# ============================================================================
# KPIs  —  v2.0: ahora devuelve evi_mean + campos climáticos
# ============================================================================

@router.get("/parcels/{parcel_id}/kpis", response_model=List[KpiTimeSeriesV2])
async def get_parcel_kpis(
    parcel_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene serie temporal de KPIs de una parcela (para gráficas).
    v2.0: ahora incluye evi_mean, lst_mean, tmax_mean, precip_mm.
    """
    parcel = db.query(Parcel).filter(
        Parcel.id == parcel_id,
        Parcel.client_id == current_client.id
    ).first()
    
    if not parcel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parcela no encontrada")
    
    query = db.query(Kpi).filter(Kpi.parcel_id == parcel_id)
    
    if start_date:
        query = query.filter(Kpi.observation_date >= start_date)
    if end_date:
        query = query.filter(Kpi.observation_date <= end_date)
    
    # Por defecto, último año
    if not start_date and not end_date:
        one_year_ago = date.today() - timedelta(days=365)
        query = query.filter(Kpi.observation_date >= one_year_ago)
    
    kpis = query.order_by(Kpi.observation_date).all()
    
    return [
        KpiTimeSeriesV2(
            observation_date=k.observation_date,
            ndvi_mean=float(k.ndvi_mean) if k.ndvi_mean else None,
            ndvi_p10=float(k.ndvi_p10) if k.ndvi_p10 else None,
            ndvi_p90=float(k.ndvi_p90) if k.ndvi_p90 else None,
            ndwi_mean=float(k.ndwi_mean) if k.ndwi_mean else None,
            evi_mean=float(k.evi_mean) if k.evi_mean else None,          # ← FIX: antes faltaba
            stress_area_pct=float(k.stress_area_pct) if k.stress_area_pct else None,
            lst_mean=float(k.lst_mean) if k.lst_mean else None,          # ← NEW
            tmax_mean=float(k.tmax_mean) if k.tmax_mean else None,       # ← NEW
            precip_mm=float(k.precip_mm) if k.precip_mm else None,       # ← NEW
        )
        for k in kpis
    ]


# ============================================================================
# JOBS  (sin cambios)
# ============================================================================

@router.get("/jobs", response_model=List[JobResponse])
async def get_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """Obtiene historial de jobs del cliente"""
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
    """Obtiene detalle de un job específico"""
    job = db.query(Job).filter(
        Job.job_id == job_id,
        Job.client_id == current_client.id
    ).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job no encontrado")
    return job


# ============================================================================
# REPORTS  —  v2.0: download ahora requiere auth
# ============================================================================

@router.get("/reports", response_model=List[ReportResponse])
async def get_reports(
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """Obtiene historial de reportes del cliente"""
    reports = db.query(Report).filter(
        Report.client_id == current_client.id
    ).order_by(desc(Report.generated_at)).offset(offset).limit(limit).all()
    return reports


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: str,
    current_client: Client = Depends(get_current_active_client),   # ← FIX: ahora requiere auth
    db: Session = Depends(get_db)
):
    """
    Descarga un reporte. v2.0: requiere autenticación.
    FIX: Para biweekly, si pdf_url no existe, intentar reconstruir la URL de Drive.
    """
    try:
        report_uuid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de reporte inválido")

    report = db.query(Report).filter(
        Report.id == report_uuid,
        Report.client_id == current_client.id           # ← FIX: verificar que es del cliente
    ).first()

    if not report:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")

    if not report.pdf_url:
        # v2.0: Si no tiene pdf_url, intentar con pdf_drive_id
        if report.pdf_drive_id:
            pdf_url = f"https://drive.google.com/uc?export=download&id={report.pdf_drive_id}"
            return {"url": pdf_url}
        raise HTTPException(
            status_code=404,
            detail="PDF no disponible. El reporte puede estar procesándose — inténtalo de nuevo en unos minutos."
        )

    pdf_url = report.pdf_url
    if 'drive.google.com/file/d/' in pdf_url:
        file_id = pdf_url.split('/file/d/')[1].split('/')[0]
        pdf_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    return {"url": pdf_url}


# ============================================================================
# REPORTS - Guardar Link en BD (llamado desde n8n)  — sin cambios
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
    job = db.query(Job).filter(Job.job_id == data.job_id_string).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job no encontrado: {data.job_id_string}"
        )
    
    client = db.query(Client).filter(Client.email == data.client_email).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente no encontrado: {data.client_email}"
        )
    
    existing_report = db.query(Report).filter(
        Report.job_id == job.id
    ).first()
    
    if existing_report:
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
# ALERTS  (sin cambios)
# ============================================================================

@router.get("/alerts", response_model=List[DashboardAlert])
async def get_alerts(
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """Obtiene alertas activas (parcelas con estrés)"""
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
# v2.0 NEW: RECOMMENDATIONS — Recomendaciones del último informe
# ============================================================================

@router.get("/recommendations", response_model=RecommendationsResponse)
async def get_recommendations(
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Devuelve las recomendaciones del último informe (baseline o biweekly).
    Estos datos vienen de Report.recommendations_json (guardado por n8n vía job-completed).
    """
    latest_report = db.query(Report).filter(
        Report.client_id == current_client.id,
        Report.report_type.in_(["baseline", "biweekly"]),
        Report.recommendations_json.isnot(None)
    ).order_by(desc(Report.generated_at)).first()

    if not latest_report or not latest_report.recommendations_json:
        return RecommendationsResponse(
            recommendations=[],
            report_type=None,
            report_date=None,
            report_id=None,
        )

    recs = latest_report.recommendations_json
    items = []
    for r in recs:
        if isinstance(r, dict):
            items.append(RecommendationItem(
                title=r.get("title", "Sin título"),
                priority=r.get("priority", "Media"),
                deadline_days=r.get("deadline_days", 14),
                trigger=r.get("trigger"),
                zone=r.get("zone"),
                justification=r.get("justification"),
            ))

    return RecommendationsResponse(
        recommendations=items,
        report_type=latest_report.report_type,
        report_date=latest_report.generated_at.strftime("%Y-%m-%d") if latest_report.generated_at else None,
        report_id=str(latest_report.id),
    )


# ============================================================================
# v2.0 NEW: WEATHER FORECAST — Proxy a Open-Meteo desde centroide de parcela
# ============================================================================

@router.get("/weather-forecast")
async def get_weather_forecast(
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Proxy a Open-Meteo: previsión 7 días usando el centroide de la primera parcela.
    Devuelve datos agregados + arrays diarios para mini-gráficas en dashboard.
    """
    # Obtener primera parcela activa con centroide
    parcel = db.query(Parcel).filter(
        Parcel.client_id == current_client.id,
        Parcel.is_active == True,
        Parcel.centroid_lat.isnot(None)
    ).first()

    if not parcel or not parcel.centroid_lat or not parcel.centroid_lon:
        return {
            "available": False,
            "error": "No hay parcela con coordenadas disponibles"
        }

    lat = float(parcel.centroid_lat)
    lon = float(parcel.centroid_lon)

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
        f"et0_fao_evapotranspiration,wind_speed_10m_max,soil_moisture_0_to_7cm_mean"
        f"&forecast_days=7&timezone=Europe/Madrid"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"⚠️ Open-Meteo error: {e}")
        return {"available": False, "error": str(e)}

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    tmax = daily.get("temperature_2m_max", [])
    tmin = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])
    et0 = daily.get("et0_fao_evapotranspiration", [])
    wind = daily.get("wind_speed_10m_max", [])
    soil = daily.get("soil_moisture_0_to_7cm_mean", [])

    n = len(dates)
    total_precip = sum(p for p in precip if p is not None)
    total_et0 = sum(e for e in et0 if e is not None)
    valid_tmax = [t for t in tmax if t is not None]
    valid_tmin = [t for t in tmin if t is not None]

    avg_tmax = sum(valid_tmax) / len(valid_tmax) if valid_tmax else None
    avg_tmin = sum(valid_tmin) / len(valid_tmin) if valid_tmin else None
    max_tmax = max(valid_tmax) if valid_tmax else None
    min_tmin = min(valid_tmin) if valid_tmin else None

    # Alertas
    heat_days = sum(1 for t in valid_tmax if t >= 35)
    frost_days = sum(1 for t in valid_tmin if t <= 0)
    heavy_rain_days = sum(1 for p in precip if p is not None and p > 20)

    # Ola de calor: 3+ días consecutivos ≥35°C
    consec = 0
    heat_wave = False
    for t in tmax:
        if t is not None and t >= 35:
            consec += 1
            if consec >= 3:
                heat_wave = True
        else:
            consec = 0

    return {
        "available": True,
        "days_ahead": n,
        "location": {"lat": lat, "lon": lon, "parcel_name": parcel.parcel_name},

        # Arrays diarios (para gráficas)
        "daily": {
            "dates": dates,
            "tmax": tmax,
            "tmin": tmin,
            "precip": precip,
            "et0": et0,
            "wind_max": wind,
            "soil_moisture": soil,
        },

        # Agregados
        "summary": {
            "avg_tmax": round(avg_tmax, 1) if avg_tmax is not None else None,
            "avg_tmin": round(avg_tmin, 1) if avg_tmin is not None else None,
            "max_tmax": round(max_tmax, 1) if max_tmax is not None else None,
            "min_tmin": round(min_tmin, 1) if min_tmin is not None else None,
            "total_precip_mm": round(total_precip, 1),
            "total_et0_mm": round(total_et0, 1),
            "water_balance_mm": round(total_precip - total_et0, 1),
        },

        # Alertas
        "alerts": {
            "heat_wave_risk": heat_wave,
            "heat_days": heat_days,
            "frost_risk": frost_days > 0,
            "frost_days": frost_days,
            "drought_risk": (total_precip - total_et0) < -30,
            "heavy_rain_risk": heavy_rain_days > 0,
            "heavy_rain_days": heavy_rain_days,
        },
    }


# ============================================================================
# v2.0 NEW: CLIMATE SUMMARY — Resumen climático últimas 2 semanas
# ============================================================================

@router.get("/climate-summary")
async def get_climate_summary(
    days: int = Query(14, ge=7, le=90),
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Resumen climático de los últimos N días extraído de los KPIs almacenados.
    Usa tmax_mean, precip_mm, lst_mean de la tabla kpis.
    """
    parcel_ids = db.query(Parcel.id).filter(
        Parcel.client_id == current_client.id,
        Parcel.is_active == True
    ).all()
    parcel_ids = [p[0] for p in parcel_ids]

    if not parcel_ids:
        return {
            "period_days": days,
            "observations_count": 0,
            "tmax_mean": None,
            "precip_total_mm": None,
            "lst_mean": None,
        }

    since = date.today() - timedelta(days=days)
    kpis = db.query(Kpi).filter(
        Kpi.parcel_id.in_(parcel_ids),
        Kpi.observation_date >= since
    ).order_by(Kpi.observation_date).all()

    if not kpis:
        return {
            "period_days": days,
            "observations_count": 0,
            "tmax_mean": None,
            "precip_total_mm": None,
            "lst_mean": None,
        }

    # Agregar datos climáticos (solo los que tienen valores)
    tmax_vals = [float(k.tmax_mean) for k in kpis if k.tmax_mean is not None]
    precip_vals = [float(k.precip_mm) for k in kpis if k.precip_mm is not None]
    lst_vals = [float(k.lst_mean) for k in kpis if k.lst_mean is not None]

    return {
        "period_days": days,
        "observations_count": len(kpis),
        "tmax_mean": round(sum(tmax_vals) / len(tmax_vals), 1) if tmax_vals else None,
        "precip_total_mm": round(sum(precip_vals), 1) if precip_vals else None,
        "lst_mean": round(sum(lst_vals) / len(lst_vals), 1) if lst_vals else None,
        # Detalle para mini-gráficas
        "daily": [
            {
                "date": k.observation_date.isoformat(),
                "tmax": float(k.tmax_mean) if k.tmax_mean else None,
                "precip": float(k.precip_mm) if k.precip_mm else None,
                "lst": float(k.lst_mean) if k.lst_mean else None,
            }
            for k in kpis
        ],
    }


# ============================================================================
# MAP DATA - Datos para capas satelitales  (sin cambios)
# ============================================================================

@router.get("/parcels/{parcel_id}/map-data")
async def get_parcel_map_data(
    parcel_id: str,
    current_client: Client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """
    Obtiene datos completos para renderizar el mapa con capas satelitales.
    """
    parcel = db.query(Parcel).filter(
        Parcel.id == parcel_id,
        Parcel.client_id == current_client.id
    ).first()
    
    if not parcel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parcela no encontrada")
    
    last_job = db.query(Job).filter(
        Job.client_id == current_client.id,
        Job.status == "completed"
    ).order_by(desc(Job.completed_at)).first()
    
    parsed_roi = parse_geojson(parcel.roi_geojson)
    geometry = extract_geometry(parsed_roi)
    bounds = calculate_bounds(geometry)
    
    latest_kpi = db.query(Kpi).filter(
        Kpi.parcel_id == parcel.id
    ).order_by(desc(Kpi.observation_date)).first()
    
    images = {}
    job_id = None
    if last_job:
        job_id = last_job.job_id
        try:
            gee_images = db.query(GEEImage).filter(
                GEEImage.job_id == job_id,
                GEEImage.png_base64.isnot(None)
            ).all()
            for img in gee_images:
                images[img.index_type] = f"/api/images/{job_id}/{img.filename}"
        except Exception as e:
            print(f"Warning: Could not fetch GEE images: {e}")
    
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
    """Obtiene datos del mapa para la primera parcela activa del cliente."""
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
    
    return await get_parcel_map_data(
        parcel_id=str(parcel.id),
        current_client=current_client,
        db=db
    )


# ============================================================================
# PAC REPORTS — Generación bajo demanda e informe anual  (sin cambios)
# ============================================================================

class PacReportRequest(BaseModel):
    parcel_id: str
    report_type: str = "pac_inspeccion"
    request_signature: bool = False
    year: Optional[int] = None


class PacSignatureRequest(BaseModel):
    report_id: str


@router.post("/reports/generate-pac")
async def generate_pac_report_endpoint(
    req: PacReportRequest,
    current_client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """Genera un informe PAC on-demand para la parcela indicada."""
    import base64 as _b64
    from app.services.generate_pac_report import generate_pac_report

    parcel = db.query(Parcel).filter(
        Parcel.id == req.parcel_id,
        Parcel.client_id == current_client.id,
        Parcel.is_active == True
    ).first()

    if not parcel:
        raise HTTPException(status_code=404, detail="Parcela no encontrada")

    year = req.year or datetime.now().year
    period_start = date(year - 1, 3, 1)
    period_end = date(year, 2, 28)

    if req.report_type == 'pac_inspeccion':
        period_end = datetime.now().date()
        period_start = date(period_end.year - 1, period_end.month, period_end.day)

    kpi_records_raw = (
        db.query(Kpi)
        .filter(
            Kpi.parcel_id == req.parcel_id,
            Kpi.observation_date >= period_start,
            Kpi.observation_date <= period_end,
            Kpi.ndvi_mean.isnot(None)
        )
        .order_by(Kpi.observation_date)
        .all()
    )

    kpi_records = [
        {
            'observation_date': str(k.observation_date),
            'ndvi_mean': float(k.ndvi_mean) if k.ndvi_mean else None,
            'ndwi_mean': float(k.ndwi_mean) if k.ndwi_mean else None,
            'stress_area_pct': float(k.stress_area_pct) if k.stress_area_pct else None,
            'satellite_source': k.satellite_source or 'Sentinel-2',
        }
        for k in kpi_records_raw
    ]

    ts = datetime.now().strftime('%Y%m%d%H%M')
    ref = f"PAC-{str(current_client.id)[:8].upper()}-{ts}"
    sig_status = 'pending' if req.request_signature else 'not_requested'

    pdf_data = {
        'client_name': current_client.client_name,
        'parcel_name': parcel.parcel_name,
        'crop_type': parcel.crop_type,
        'area_hectares': float(parcel.hectares) if parcel.hectares else 0,
        'municipality': parcel.municipality or parcel.province or 'Andalucía, España',
        'province': parcel.province or 'Andalucía',
        'period_start': period_start,
        'period_end': period_end,
        'year': year,
        'report_type': req.report_type,
        'report_ref': ref,
        'signature_status': sig_status,
        'kpi_records': kpi_records,
    }

    result = generate_pac_report(pdf_data)

    if not result['success']:
        raise HTTPException(
            status_code=500,
            detail=f"Error generando informe PAC: {result.get('error', 'Unknown')}"
        )

    last_job = (
        db.query(Job)
        .filter(Job.parcel_id == req.parcel_id)
        .order_by(desc(Job.created_at))
        .first()
    )

    new_report = Report(
        job_id=last_job.id if last_job else None,
        client_id=current_client.id,
        report_type=req.report_type,
        period_start=period_start,
        period_end=period_end,
        report_metadata={
            'pac_ref': ref,
            'pac_status': result['pac_status'],
            'signature_status': sig_status,
            'agronomist_name': None,
            'conditions_count': result['conditions_count'],
            'no_conforme_count': result['no_conforme_count'],
            'year': year,
            'kpi_count': len(kpi_records),
        }
    )

    db.add(new_report)
    db.commit()
    db.refresh(new_report)

    # ── Notificar solicitud de firma PAC vía n8n ──
    if req.request_signature:
        print(f"📝 PAC firma solicitada: report_id={new_report.id} | cliente={current_client.email} | ref={ref}")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as http:
                await http.post(
                    "https://primary-production-c678.up.railway.app/webhook/pac-signature-request",
                    json={
                        "client_name": current_client.client_name,
                        "client_email": current_client.email,
                        "parcel_name": parcel.parcel_name,
                        "report_ref": ref,
                        "report_id": str(new_report.id),
                        "pac_status": result['pac_status'],
                        "report_type": req.report_type,
                        "requested_at": datetime.now().isoformat(),
                    }
                )
        except Exception as e:
            print(f"⚠️ No se pudo notificar firma PAC: {e}")

    return {
        'success': True,
        'report_id': str(new_report.id),
        'report_ref': ref,
        'pac_status': result['pac_status'],
        'pdf_base64': result['pdf_base64'],
        'filename': result['filename'],
        'pdf_size': result['pdf_size'],
        'signature_status': sig_status,
        'kpi_count': len(kpi_records),
        'conditions': result['conditions_count'],
        'generated_at': result['generated_at'],
    }


@router.get("/reports/pac-status/{report_id}")
async def get_pac_report_status(
    report_id: str,
    current_client = Depends(get_current_active_client),
    db: Session = Depends(get_db)
):
    """Devuelve el estado de un informe PAC."""
    try:
        rid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID inválido")

    report = db.query(Report).filter(
        Report.id == rid,
        Report.client_id == current_client.id
    ).first()

    if not report:
        raise HTTPException(status_code=404, detail="Informe no encontrado")

    meta = report.report_metadata or {}
    return {
        'report_id': str(report.id),
        'report_type': report.report_type,
        'pac_ref': meta.get('pac_ref', ''),
        'pac_status': meta.get('pac_status', 'unknown'),
        'signature_status': meta.get('signature_status', 'not_requested'),
        'agronomist_name': meta.get('agronomist_name'),
        'generated_at': report.generated_at.isoformat() if report.generated_at else None,
        'pdf_url': report.pdf_url,
    }


@router.post("/reports/pac-sign")
async def update_pac_signature(
    report_id: str,
    agronomist_name: str,
    agronomist_college: str = '',
    x_internal_key: str = '',
    db: Session = Depends(get_db)
):
    """Marca un informe PAC como firmado (uso interno Mu.Orbita)."""
    import os
    internal_key = os.getenv('INTERNAL_API_KEY', 'muorbita-internal-2026')
    if x_internal_key != internal_key:
        raise HTTPException(status_code=403, detail="No autorizado")

    try:
        rid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID inválido")

    report = db.query(Report).filter(Report.id == rid).first()
    if not report:
        raise HTTPException(status_code=404, detail="Informe no encontrado")

    meta = dict(report.report_metadata or {})
    meta['signature_status'] = 'signed'
    meta['agronomist_name'] = agronomist_name
    meta['agronomist_college'] = agronomist_college
    meta['signature_date'] = datetime.now().isoformat()
    report.report_metadata = meta

    db.commit()
    return {'success': True, 'report_id': str(report.id), 'agronomist_name': agronomist_name}
