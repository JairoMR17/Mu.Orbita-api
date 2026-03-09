"""
Mu.Orbita API - Webhooks Router
Endpoints para recibir datos de n8n
VERSIÓN 4.1 - Auto-creación de Report + Kpi en job-completed
             - Resolución automática de client_id/parcel_id por email
             - Poblado automático de tablas para dashboard

CAMBIOS vs v4.0:
  1. WebhookJobCompletedV2 ahora acepta client_email y client_name
  2. Si el job no tiene client_id, lo resuelve automáticamente por client_email
  3. Si el job no tiene parcel_id, busca la primera parcela activa del cliente
  4. ndvi_current se guarda como número (no string) — compatible con columna numeric
  5. Esto garantiza que jobs creados sin job-started tengan datos completos
"""

from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import Optional, Union, List
from datetime import datetime, date as date_type
from pydantic import BaseModel
from passlib.context import CryptContext
import json
import traceback

from app.database import get_db
from app.models import Client, Parcel, Job, Kpi, Report
from app.schemas import (
    WebhookJobCompleted, WebhookKpiBatch, KpiCreate,
    MessageResponse, JobCreate
)
from app.config import settings

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_webhook(x_webhook_secret: Optional[str] = Header(None)):
    """
    Verifica el secret del webhook.
    n8n debe enviar el header X-Webhook-Secret con el valor correcto.
    """
    if not settings.n8n_webhook_secret:
        return True
    
    if x_webhook_secret != settings.n8n_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook secret inválido"
        )
    return True


def parse_roi_geojson(roi_data):
    """
    Parsea roi_geojson que puede venir como string o dict.
    """
    if roi_data is None:
        return None
    if isinstance(roi_data, dict):
        return roi_data
    if isinstance(roi_data, str):
        try:
            return json.loads(roi_data)
        except:
            return None
    return None


def resolve_client_and_parcel(db: Session, email: str):
    """
    Dado un email, resuelve client_id y parcel_id.
    Retorna (client_id, parcel_id) o (None, None).
    """
    if not email:
        return None, None
    
    client = db.query(Client).filter(Client.email == email).first()
    if not client:
        return None, None
    
    parcel = db.query(Parcel).filter(
        Parcel.client_id == client.id,
        Parcel.is_active == True
    ).first()
    
    return client.id, (parcel.id if parcel else None)


# ============================================================
# JOB-STARTED
# ============================================================

@router.post("/job-started", response_model=MessageResponse)
async def webhook_job_started(
    payload: JobCreate,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_webhook)
):
    """
    n8n notifica que un job ha comenzado.
    Crea el job en la BD si no existe.
    """
    client = db.query(Client).filter(Client.email == payload.client_email).first()
    
    if not client:
        client = Client(
            email=payload.client_email,
            client_name=payload.client_name or payload.client_email.split("@")[0],
            status="active",
            source="n8n_webhook"
        )
        db.add(client)
        db.commit()
        db.refresh(client)
    
    parcel = None
    if payload.parcel_id:
        parcel = db.query(Parcel).filter(Parcel.id == payload.parcel_id).first()
    
    roi_geojson = parse_roi_geojson(payload.roi_geojson)
    
    if not parcel and roi_geojson:
        parcel = Parcel(
            client_id=client.id,
            parcel_name=f"Parcela {payload.crop_type}",
            hectares=0,
            crop_type=payload.crop_type,
            roi_geojson=roi_geojson
        )
        db.add(parcel)
        db.commit()
        db.refresh(parcel)
    
    import time
    job_id = f"JOB_{int(time.time() * 1000)}"
    
    job = Job(
        job_id=job_id,
        client_id=client.id,
        parcel_id=parcel.id if parcel else None,
        client_email=payload.client_email,
        client_name=payload.client_name,
        crop_type=payload.crop_type,
        analysis_type=payload.analysis_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        roi_geojson=roi_geojson,
        buffer_meters=payload.buffer_meters,
        status="processing",
        started_at=datetime.utcnow()
    )
    
    db.add(job)
    db.commit()
    
    return MessageResponse(message=f"Job {job_id} registrado")


# ============================================================
# JOB-COMPLETED v4.1
# Con auto-creación de Report + Kpi + resolución por email
# ============================================================

class WebhookJobCompletedV2(BaseModel):
    """
    Payload para webhook job-completed v4.1.
    Incluye client_email para resolución automática de client_id/parcel_id,
    campos fenológicos, y datos para auto-crear Report y Kpi.
    """
    job_id: str
    status: str
    pdf_url: Optional[str] = None
    google_drive_folder_id: Optional[str] = None
    error_message: Optional[str] = None
    
    # Identificación del cliente (v4.1 — para resolver client_id/parcel_id)
    client_email: Optional[str] = None
    client_name: Optional[str] = None
    
    # KPIs básicos
    ndvi_mean: Optional[float] = None
    ndvi_p10: Optional[float] = None
    ndvi_p90: Optional[float] = None
    ndwi_mean: Optional[float] = None
    evi_mean: Optional[float] = None
    stress_area_ha: Optional[float] = None
    stress_area_pct: Optional[float] = None
    
    # Campos fenológicos (v3.2)
    doy: Optional[int] = None
    pheno_phase: Optional[str] = None
    pheno_status: Optional[str] = None
    ndvi_expected: Optional[float] = None
    ndvi_deviation_pct: Optional[float] = None
    ndvi_zscore_seasonal: Optional[float] = None
    
    # Campos opcionales para Report (v4.0)
    main_findings: Optional[list] = None
    priority_actions: Optional[list] = None


@router.post("/job-completed", response_model=MessageResponse)
async def webhook_job_completed(
    payload: WebhookJobCompletedV2,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_webhook)
):
    """
    n8n notifica que un job ha terminado.
    
    VERSIÓN 4.1 — Además de actualizar el job, ahora:
    1. Resuelve client_id y parcel_id desde client_email si faltan
    2. Crea automáticamente un registro Report (para /dashboard/reports)
    3. Crea/actualiza un registro Kpi (para /dashboard/summary y /dashboard/alerts)
    
    Esto garantiza que el dashboard SIEMPRE tenga datos tras un análisis exitoso,
    incluso si el job no pasó por /webhooks/job-started.
    """
    job = db.query(Job).filter(Job.job_id == payload.job_id).first()
    
    # ── 0. Si no existe el job, crearlo resolviendo client/parcel por email ──
    if not job:
        resolved_client_id, resolved_parcel_id = resolve_client_and_parcel(
            db, payload.client_email
        )
        
        job = Job(
            job_id=payload.job_id,
            client_id=resolved_client_id,
            parcel_id=resolved_parcel_id,
            client_email=payload.client_email,
            client_name=payload.client_name,
            status=payload.status,
            completed_at=datetime.utcnow() if payload.status == "completed" else None
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        
        if resolved_client_id:
            print(f"✅ Job {payload.job_id} creado con client={resolved_client_id}, parcel={resolved_parcel_id}")
        else:
            print(f"⚠️ Job {payload.job_id} creado sin client_id (email: {payload.client_email})")
    
    # ── 0b. Si el job existe pero no tiene client_id, resolverlo ahora ──
    if not job.client_id and payload.client_email:
        resolved_client_id, resolved_parcel_id = resolve_client_and_parcel(
            db, payload.client_email
        )
        if resolved_client_id:
            job.client_id = resolved_client_id
            if not job.parcel_id and resolved_parcel_id:
                job.parcel_id = resolved_parcel_id
            db.commit()
            db.refresh(job)
            print(f"🔗 Job {payload.job_id} vinculado a client={resolved_client_id}, parcel={resolved_parcel_id}")
    
    # ── 1. Actualizar campos del Job ──────────────────────────
    job.status = payload.status
    job.completed_at = datetime.utcnow() if payload.status == "completed" else None
    
    if payload.pdf_url:
        job.report_url = payload.pdf_url
    if payload.google_drive_folder_id:
        job.google_drive_folder_id = payload.google_drive_folder_id
    if payload.error_message:
        job.error_message = payload.error_message
    if payload.client_email and not job.client_email:
        job.client_email = payload.client_email
    if payload.client_name and not job.client_name:
        job.client_name = payload.client_name
    
    # KPIs básicos en la tabla jobs
    if payload.ndvi_mean is not None:
        job.ndvi_mean = payload.ndvi_mean
    if payload.ndvi_p10 is not None:
        job.ndvi_p10 = payload.ndvi_p10
    if payload.ndvi_p90 is not None:
        job.ndvi_p90 = payload.ndvi_p90
    if payload.ndwi_mean is not None:
        job.ndwi_mean = payload.ndwi_mean
    if payload.stress_area_ha is not None:
        job.stress_area_ha = payload.stress_area_ha
    if payload.stress_area_pct is not None:
        job.stress_area_pct = payload.stress_area_pct
    
    # Campos fenológicos
    if payload.doy is not None:
        job.doy = payload.doy
    if payload.pheno_phase is not None:
        job.pheno_phase = payload.pheno_phase
    if payload.pheno_status is not None:
        job.pheno_status = payload.pheno_status
    if payload.ndvi_expected is not None:
        job.ndvi_expected = payload.ndvi_expected
    if payload.ndvi_deviation_pct is not None:
        job.ndvi_deviation_pct = payload.ndvi_deviation_pct
    if payload.ndvi_zscore_seasonal is not None:
        job.ndvi_zscore_seasonal = payload.ndvi_zscore_seasonal
    
    db.commit()
    db.refresh(job)
    
    # ── 2. Auto-crear Report (v4.0) ──────────────────────────
    report_created = False
    if payload.status == "completed" and job.client_id:
        try:
            existing_report = db.query(Report).filter(
                Report.job_id == job.id
            ).first()
            
            if not existing_report:
                new_report = Report(
                    job_id=job.id,
                    client_id=job.client_id,
                    report_type=getattr(job, 'analysis_type', 'baseline') or 'baseline',
                    pdf_url=payload.pdf_url,
                    period_start=getattr(job, 'start_date', None),
                    period_end=getattr(job, 'end_date', None),
                    generated_at=datetime.utcnow(),
                    ndvi_current=round(payload.ndvi_mean, 2) if payload.ndvi_mean is not None else None,
                    main_findings=payload.main_findings,
                    priority_actions=payload.priority_actions,
                )
                db.add(new_report)
                db.commit()
                report_created = True
                print(f"✅ Report auto-creado para job {payload.job_id}")
            else:
                if payload.pdf_url:
                    existing_report.pdf_url = payload.pdf_url
                if payload.ndvi_mean is not None:
                    existing_report.ndvi_current = round(payload.ndvi_mean, 2)
                db.commit()
                print(f"📝 Report existente actualizado para job {payload.job_id}")
                
        except Exception as e:
            print(f"⚠️ Error creando Report para job {payload.job_id}: {e}")
            print(traceback.format_exc())
            db.rollback()
    
    # ── 3. Auto-crear/actualizar Kpi (v4.0) ──────────────────
    kpi_created = False
    if payload.status == "completed" and job.parcel_id:
        try:
            obs_date = getattr(job, 'end_date', None) or date_type.today()
            
            existing_kpi = db.query(Kpi).filter(
                Kpi.parcel_id == job.parcel_id,
                Kpi.observation_date == obs_date
            ).first()
            
            if existing_kpi:
                if payload.ndvi_mean is not None:
                    existing_kpi.ndvi_mean = payload.ndvi_mean
                if payload.ndvi_p10 is not None:
                    existing_kpi.ndvi_p10 = payload.ndvi_p10
                if payload.ndvi_p90 is not None:
                    existing_kpi.ndvi_p90 = payload.ndvi_p90
                if payload.ndwi_mean is not None:
                    existing_kpi.ndwi_mean = payload.ndwi_mean
                if payload.evi_mean is not None:
                    existing_kpi.evi_mean = payload.evi_mean
                if payload.stress_area_ha is not None:
                    existing_kpi.stress_area_ha = payload.stress_area_ha
                if payload.stress_area_pct is not None:
                    existing_kpi.stress_area_pct = payload.stress_area_pct
                db.commit()
                print(f"📝 KPI actualizado para parcela {job.parcel_id} fecha {obs_date}")
            else:
                new_kpi = Kpi(
                    parcel_id=job.parcel_id,
                    job_id=job.id,
                    observation_date=obs_date,
                    ndvi_mean=payload.ndvi_mean,
                    ndvi_p10=payload.ndvi_p10,
                    ndvi_p90=payload.ndvi_p90,
                    ndwi_mean=payload.ndwi_mean,
                    evi_mean=payload.evi_mean,
                    stress_area_ha=payload.stress_area_ha,
                    stress_area_pct=payload.stress_area_pct,
                    satellite_source="sentinel2",
                )
                db.add(new_kpi)
                db.commit()
                kpi_created = True
                print(f"✅ KPI auto-creado para parcela {job.parcel_id} fecha {obs_date}")
                
        except Exception as e:
            print(f"⚠️ Error creando KPI para job {payload.job_id}: {e}")
            print(traceback.format_exc())
            db.rollback()
    
    # ── 4. Construir mensaje de respuesta ─────────────────────
    pheno_info = ""
    if payload.pheno_status:
        pheno_info = f" | Fenología: {payload.pheno_status}"
        if payload.pheno_phase:
            pheno_info += f" ({payload.pheno_phase})"
    
    extras = []
    if report_created:
        extras.append("Report creado")
    if kpi_created:
        extras.append("KPI creado")
    if job.client_id:
        extras.append(f"client={str(job.client_id)[:8]}")
    if job.parcel_id:
        extras.append(f"parcel={str(job.parcel_id)[:8]}")
    extras_str = f" | {', '.join(extras)}" if extras else ""
    
    return MessageResponse(
        message=f"Job {payload.job_id} actualizado a {payload.status}{pheno_info}{extras_str}"
    )


# ============================================================
# KPIS BATCH (para time_series completa desde n8n)
# ============================================================

@router.post("/kpis", response_model=MessageResponse)
async def webhook_kpis(
    payload: WebhookKpiBatch,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_webhook)
):
    """
    n8n envía batch de KPIs calculados (serie temporal completa).
    Inserta o actualiza KPIs en la BD.
    
    Este endpoint es COMPLEMENTARIO a job-completed:
    - job-completed crea 1 KPI (última observación) para que el dashboard funcione siempre
    - Este endpoint crea N KPIs (toda la time_series) para el gráfico de evolución
    """
    parcel = db.query(Parcel).filter(Parcel.id == payload.parcel_id).first()
    if not parcel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Parcela {payload.parcel_id} no encontrada"
        )
    
    inserted = 0
    updated = 0
    
    for kpi_data in payload.kpis:
        existing = db.query(Kpi).filter(
            Kpi.parcel_id == payload.parcel_id,
            Kpi.observation_date == kpi_data.observation_date
        ).first()
        
        if existing:
            for field, value in kpi_data.model_dump(exclude={"parcel_id"}).items():
                if value is not None:
                    setattr(existing, field, value)
            updated += 1
        else:
            kpi = Kpi(
                parcel_id=payload.parcel_id,
                job_id=payload.job_id,
                **kpi_data.model_dump(exclude={"parcel_id", "job_id"})
            )
            db.add(kpi)
            inserted += 1
    
    db.commit()
    
    return MessageResponse(
        message=f"KPIs procesados: {inserted} insertados, {updated} actualizados"
    )


# ============================================================
# REPORT-SENT
# ============================================================

class ReportSentPayload(BaseModel):
    job_id: str
    sent_to: str


@router.post("/report-sent", response_model=MessageResponse)
async def webhook_report_sent(
    payload: ReportSentPayload,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_webhook)
):
    """
    n8n notifica que el reporte fue enviado por email.
    Marca el Report como enviado (si existe).
    """
    job = db.query(Job).filter(Job.job_id == payload.job_id).first()
    if job:
        job.report_sent = True
        db.commit()
    
        report = db.query(Report).filter(Report.job_id == job.id).first()
        if report:
            report.sent_at = datetime.utcnow()
            report.sent_to = payload.sent_to
            db.commit()
    
    return MessageResponse(message=f"Report {payload.job_id} marcado como enviado")


# ============================================================
# CLIENT-CREATED
# ============================================================

class ClientCreatedPayload(BaseModel):
    email: str
    client_name: str
    password: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    hectares: Optional[float] = None
    crop_type: Optional[str] = None
    plan: Optional[str] = None
    roi_geojson: Optional[Union[dict, str]] = None
    stripe_customer_id: Optional[str] = None


@router.post("/client-created", response_model=MessageResponse)
async def webhook_client_created(
    payload: ClientCreatedPayload,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_webhook)
):
    """
    n8n notifica que un nuevo cliente se registró (desde el formulario web).
    Hashea la contraseña y crea cliente + parcela.
    """
    # Verificar si ya existe
    existing = db.query(Client).filter(Client.email == payload.email).first()
    if existing:
        return MessageResponse(message=f"Cliente {payload.email} ya existe")
    
    # Hashear contraseña
    password_hash = None
    if payload.password:
        password_hash = pwd_context.hash(payload.password)
    
    # Crear cliente
    client = Client(
        email=payload.email,
        client_name=payload.client_name,
        password_hash=password_hash,
        company=payload.company,
        phone=payload.phone,
        hectares=payload.hectares,
        crop_type=payload.crop_type,
        subscription_tier=payload.plan,
        stripe_customer_id=payload.stripe_customer_id,
        status="active",
        source="n8n_webhook"
    )
    
    roi_geojson = parse_roi_geojson(payload.roi_geojson)
    if roi_geojson:
        client.roi_geojson = roi_geojson
    
    db.add(client)
    db.commit()
    db.refresh(client)
    
    # Crear parcela si hay ROI
    if roi_geojson:
        parcel = Parcel(
            client_id=client.id,
            parcel_name=f"Parcela {payload.crop_type or 'Principal'}",
            hectares=payload.hectares or 0,
            crop_type=payload.crop_type or "olive",
            roi_geojson=roi_geojson
        )
        db.add(parcel)
        db.commit()
    
    return MessageResponse(
        message=f"Cliente {payload.email} creado con éxito"
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/health")
async def webhooks_health():
    return {"status": "ok", "service": "webhooks", "version": "4.1"}
