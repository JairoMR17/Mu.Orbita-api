"""
Mu.Orbita API - Webhooks Router
Endpoints para recibir datos de n8n
"""

from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import Optional, Union
from datetime import datetime
from pydantic import BaseModel
from passlib.context import CryptContext
import json

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


@router.post("/job-completed", response_model=MessageResponse)
async def webhook_job_completed(
    payload: WebhookJobCompleted,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_webhook)
):
    """
    n8n notifica que un job ha terminado.
    Actualiza el job con los resultados, o lo crea si no existe.
    """
    job = db.query(Job).filter(Job.job_id == payload.job_id).first()
    
    # Si no existe el job, crearlo
    if not job:
        job = Job(
            job_id=payload.job_id,
            status=payload.status,
            completed_at=datetime.utcnow() if payload.status == "completed" else None
        )
        db.add(job)
        db.commit()
        db.refresh(job)
    
    # Actualizar job
    job.status = payload.status
    job.completed_at = datetime.utcnow() if payload.status == "completed" else None
    
    if payload.pdf_url:
        job.report_url = payload.pdf_url
    if payload.google_drive_folder_id:
        job.google_drive_folder_id = payload.google_drive_folder_id
    if payload.error_message:
        job.error_message = payload.error_message
    
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
    
    db.commit()
    
    return MessageResponse(message=f"Job {payload.job_id} actualizado a {payload.status}")


@router.post("/kpis", response_model=MessageResponse)
async def webhook_kpis(
    payload: WebhookKpiBatch,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_webhook)
):
    """
    n8n envía batch de KPIs calculados.
    Inserta o actualiza KPIs en la BD.
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
    # Parsear roi_geojson
    roi_geojson = parse_roi_geojson(payload.roi_geojson)
    
    existing = db.query(Client).filter(Client.email == payload.email).first()
    if existing:
        if payload.stripe_customer_id:
            existing.stripe_customer_id = payload.stripe_customer_id
        if payload.hectares:
            existing.hectares = payload.hectares
        if payload.password:
            existing.password_hash = pwd_context.hash(payload.password)
        if roi_geojson:
            existing.roi_geojson = roi_geojson
        db.commit()
        return MessageResponse(message=f"Cliente {payload.email} actualizado")
    
    password_hash = None
    if payload.password:
        password_hash = pwd_context.hash(payload.password)
    
    tier_map = {"essential": "essential", "professional": "professional", "enterprise": "enterprise"}
    subscription_tier = tier_map.get(payload.plan, "essential") if payload.plan else "essential"
    
    client = Client(
        email=payload.email,
        password_hash=password_hash,
        client_name=payload.client_name,
        company=payload.company,
        phone=payload.phone,
        hectares=payload.hectares,
        crop_type=payload.crop_type,
        roi_geojson=roi_geojson,
        stripe_customer_id=payload.stripe_customer_id,
        status="active",
        source="landing_page",
        subscription_tier=subscription_tier,
        subscription_status="active"
    )
    
    db.add(client)
    db.commit()
    db.refresh(client)
    
    if roi_geojson:
        parcel = Parcel(
            client_id=client.id,
            parcel_name="Parcela principal",
            hectares=payload.hectares or 0,
            crop_type=payload.crop_type or "olivo",
            roi_geojson=roi_geojson
        )
        db.add(parcel)
        db.commit()
    
    return MessageResponse(message=f"Cliente {payload.email} creado")


@router.get("/health")
async def webhook_health(_: bool = Depends(verify_webhook)):
    """
    Health check para verificar que el webhook está funcionando
    """
    return {"status": "ok", "service": "muorbita-webhooks"}