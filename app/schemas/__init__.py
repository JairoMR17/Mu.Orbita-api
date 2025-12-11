"""
Mu.Orbita API - Pydantic Schemas
Validación de datos de entrada/salida
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Any
from datetime import datetime, date
from uuid import UUID


# ============================================================================
# AUTH SCHEMAS
# ============================================================================

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    sub: str  # client_id
    email: str
    exp: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    client_name: str = Field(..., min_length=2)
    company: Optional[str] = None
    phone: Optional[str] = None


class GoogleAuthRequest(BaseModel):
    code: str  # Authorization code from Google


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


# ============================================================================
# CLIENT SCHEMAS
# ============================================================================

class ClientBase(BaseModel):
    email: EmailStr
    client_name: str
    company: Optional[str] = None
    phone: Optional[str] = None
    hectares: Optional[float] = None
    crop_type: Optional[str] = None
    location: Optional[str] = None


class ClientCreate(ClientBase):
    password: Optional[str] = Field(None, min_length=8)
    google_id: Optional[str] = None


class ClientUpdate(BaseModel):
    client_name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    hectares: Optional[float] = None
    crop_type: Optional[str] = None
    location: Optional[str] = None


class ClientResponse(ClientBase):
    id: UUID
    status: str
    subscription_tier: Optional[str] = None
    subscription_status: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ClientSummary(BaseModel):
    """Para dashboard - resumen del cliente"""
    id: UUID
    client_name: str
    email: str
    total_parcels: int
    total_hectares: float
    total_reports: int
    last_analysis_date: Optional[datetime] = None
    avg_ndvi: Optional[float] = None


# ============================================================================
# PARCEL SCHEMAS
# ============================================================================

class ParcelBase(BaseModel):
    parcel_name: str
    parcel_code: Optional[str] = None
    hectares: float
    crop_type: str
    crop_variety: Optional[str] = None
    planting_year: Optional[int] = None
    irrigation_type: Optional[str] = None
    location_name: Optional[str] = None
    municipality: Optional[str] = None
    province: Optional[str] = None
    roi_geojson: dict  # GeoJSON Polygon


class ParcelCreate(ParcelBase):
    pass


class ParcelUpdate(BaseModel):
    parcel_name: Optional[str] = None
    parcel_code: Optional[str] = None
    hectares: Optional[float] = None
    crop_type: Optional[str] = None
    crop_variety: Optional[str] = None
    irrigation_type: Optional[str] = None
    location_name: Optional[str] = None
    is_active: Optional[bool] = None


class ParcelResponse(ParcelBase):
    id: UUID
    client_id: UUID
    is_active: bool
    centroid_lat: Optional[float] = None
    centroid_lon: Optional[float] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class ParcelWithLatestKpi(ParcelResponse):
    """Parcela con su último KPI (para dashboard)"""
    latest_ndvi: Optional[float] = None
    latest_ndwi: Optional[float] = None
    latest_observation_date: Optional[date] = None
    stress_area_pct: Optional[float] = None


# ============================================================================
# KPI SCHEMAS
# ============================================================================

class KpiBase(BaseModel):
    observation_date: date
    ndvi_mean: Optional[float] = None
    ndvi_p10: Optional[float] = None
    ndvi_p90: Optional[float] = None
    ndwi_mean: Optional[float] = None
    evi_mean: Optional[float] = None
    lst_mean: Optional[float] = None
    stress_area_ha: Optional[float] = None
    stress_area_pct: Optional[float] = None
    satellite_source: Optional[str] = None


class KpiCreate(KpiBase):
    parcel_id: UUID
    job_id: Optional[UUID] = None
    ndvi_min: Optional[float] = None
    ndvi_max: Optional[float] = None
    ndvi_std: Optional[float] = None
    ndvi_p50: Optional[float] = None
    ndwi_min: Optional[float] = None
    ndwi_max: Optional[float] = None
    ndci_mean: Optional[float] = None
    lst_max: Optional[float] = None
    tmax_mean: Optional[float] = None
    precip_mm: Optional[float] = None
    gdd_accumulated: Optional[float] = None
    low_vigor_area_ha: Optional[float] = None
    ndvi_zscore: Optional[float] = None
    ndwi_zscore: Optional[float] = None
    cloud_cover_pct: Optional[float] = None


class KpiResponse(KpiBase):
    id: UUID
    parcel_id: UUID
    job_id: Optional[UUID] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class KpiTimeSeries(BaseModel):
    """Para gráficas de evolución"""
    observation_date: date
    ndvi_mean: Optional[float] = None
    ndvi_p10: Optional[float] = None
    ndvi_p90: Optional[float] = None
    ndwi_mean: Optional[float] = None
    stress_area_pct: Optional[float] = None


# ============================================================================
# JOB SCHEMAS
# ============================================================================

class JobBase(BaseModel):
    crop_type: str
    analysis_type: str
    start_date: date
    end_date: date
    roi_geojson: dict


class JobCreate(JobBase):
    client_email: str
    client_name: Optional[str] = None
    parcel_id: Optional[UUID] = None
    buffer_meters: int = 2000


class JobUpdate(BaseModel):
    status: Optional[str] = None
    progress: Optional[int] = None
    report_url: Optional[str] = None
    report_sent: Optional[bool] = None
    error_message: Optional[str] = None
    ndvi_mean: Optional[float] = None
    ndwi_mean: Optional[float] = None
    stress_area_ha: Optional[float] = None
    stress_area_pct: Optional[float] = None


class JobResponse(JobBase):
    id: UUID
    job_id: str
    client_id: UUID
    parcel_id: Optional[UUID] = None
    status: str
    progress: int
    report_url: Optional[str] = None
    report_sent: bool
    ndvi_mean: Optional[float] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# ============================================================================
# REPORT SCHEMAS
# ============================================================================

class ReportResponse(BaseModel):
    id: UUID
    job_id: UUID
    report_type: str
    pdf_url: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    generated_at: datetime
    sent_at: Optional[datetime] = None
    ndvi_current: Optional[str] = None
    ndvi_change: Optional[str] = None
    main_findings: Optional[List[str]] = None
    priority_actions: Optional[List[str]] = None
    
    class Config:
        from_attributes = True


# ============================================================================
# DASHBOARD SCHEMAS
# ============================================================================

class DashboardSummary(BaseModel):
    """Resumen general para dashboard principal"""
    client_name: str
    total_parcels: int
    total_hectares: float
    total_reports: int
    avg_ndvi: Optional[float] = None
    ndvi_trend: Optional[str] = None  # "up", "down", "stable"
    last_analysis_date: Optional[datetime] = None
    days_until_next_report: Optional[int] = None
    alerts_count: int = 0


class DashboardAlert(BaseModel):
    """Alerta para el dashboard"""
    parcel_id: UUID
    parcel_name: str
    alert_type: str  # "stress", "low_vigor", "anomaly"
    severity: str  # "warning", "critical"
    message: str
    detected_at: datetime


# ============================================================================
# WEBHOOK SCHEMAS (para n8n)
# ============================================================================

class WebhookJobCompleted(BaseModel):
    """Payload que envía n8n cuando termina un job"""
    job_id: str
    status: str
    pdf_url: Optional[str] = None
    google_drive_folder_id: Optional[str] = None
    ndvi_mean: Optional[float] = None
    ndvi_p10: Optional[float] = None
    ndvi_p90: Optional[float] = None
    ndwi_mean: Optional[float] = None
    stress_area_ha: Optional[float] = None
    stress_area_pct: Optional[float] = None
    error_message: Optional[str] = None


class WebhookKpiBatch(BaseModel):
    """Batch de KPIs que envía n8n"""
    parcel_id: UUID
    job_id: Optional[UUID] = None
    kpis: List[KpiCreate]


# ============================================================================
# GENERIC RESPONSES
# ============================================================================

class MessageResponse(BaseModel):
    message: str
    success: bool = True


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    pages: int
