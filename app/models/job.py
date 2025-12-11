"""
Mu.Orbita API - Job Model
"""

from sqlalchemy import Column, String, Numeric, Boolean, DateTime, Integer, Date, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Identificador legible
    job_id = Column(String(100), unique=True, nullable=False, index=True)
    
    # Foreign keys
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    parcel_id = Column(UUID(as_uuid=True), ForeignKey("parcels.id", ondelete="SET NULL"), nullable=True)
    
    # Datos desnormalizados (para queries rápidas)
    client_email = Column(String(255), nullable=False)
    client_name = Column(String(255), nullable=True)
    
    # Parámetros del análisis
    crop_type = Column(String(50), nullable=False)
    analysis_type = Column(String(50), nullable=False)  # completo, weekly_update, on_demand
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    
    # ROI
    roi_geojson = Column(JSONB, nullable=False)
    buffer_meters = Column(Integer, default=2000)
    
    # Estado
    status = Column(String(50), default="pending", index=True)
    progress = Column(Integer, default=0)
    
    # GEE
    gee_task_ids = Column(JSONB, nullable=True)
    
    # Resultados
    google_drive_folder_id = Column(String(255), nullable=True)
    report_url = Column(String(500), nullable=True)
    report_sent = Column(Boolean, default=False)
    
    # Métricas resumen
    ndvi_mean = Column(Numeric(5, 3), nullable=True)
    ndvi_p10 = Column(Numeric(5, 3), nullable=True)
    ndvi_p90 = Column(Numeric(5, 3), nullable=True)
    ndwi_mean = Column(Numeric(5, 3), nullable=True)
    stress_area_ha = Column(Numeric(10, 2), nullable=True)
    stress_area_pct = Column(Numeric(5, 2), nullable=True)
    
    # Errores
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    job_metadata = Column(JSONB, default={})
    
    # Relationships
    client = relationship("Client", back_populates="jobs")
    parcel = relationship("Parcel", back_populates="jobs")
    reports = relationship("Report", back_populates="job", cascade="all, delete-orphan")
    kpis = relationship("Kpi", back_populates="job")
    
    def __repr__(self):
        return f"<Job {self.job_id} ({self.status})>"
