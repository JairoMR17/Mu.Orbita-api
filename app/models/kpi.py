"""
Mu.Orbita API - KPI Model
Serie temporal de métricas satelitales por parcela
"""

from sqlalchemy import Column, String, Numeric, DateTime, Date, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.database import Base


class Kpi(Base):
    __tablename__ = "kpis"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign keys
    parcel_id = Column(UUID(as_uuid=True), ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    
    # Fecha de observación
    observation_date = Column(Date, nullable=False)
    
    # Índices de vegetación
    ndvi_mean = Column(Numeric(5, 3), nullable=True)
    ndvi_min = Column(Numeric(5, 3), nullable=True)
    ndvi_max = Column(Numeric(5, 3), nullable=True)
    ndvi_std = Column(Numeric(5, 3), nullable=True)
    ndvi_p10 = Column(Numeric(5, 3), nullable=True)
    ndvi_p50 = Column(Numeric(5, 3), nullable=True)
    ndvi_p90 = Column(Numeric(5, 3), nullable=True)
    
    # Índice de agua
    ndwi_mean = Column(Numeric(5, 3), nullable=True)
    ndwi_min = Column(Numeric(5, 3), nullable=True)
    ndwi_max = Column(Numeric(5, 3), nullable=True)
    
    # Productividad
    evi_mean = Column(Numeric(5, 3), nullable=True)
    
    # Clorofila
    ndci_mean = Column(Numeric(5, 3), nullable=True)
    
    # Temperatura superficial (MODIS)
    lst_mean = Column(Numeric(5, 2), nullable=True)
    lst_max = Column(Numeric(5, 2), nullable=True)
    
    # Clima (ERA5)
    tmax_mean = Column(Numeric(5, 2), nullable=True)
    precip_mm = Column(Numeric(7, 2), nullable=True)
    gdd_accumulated = Column(Numeric(7, 1), nullable=True)
    
    # Áreas de estrés
    stress_area_ha = Column(Numeric(10, 2), nullable=True)
    stress_area_pct = Column(Numeric(5, 2), nullable=True)
    low_vigor_area_ha = Column(Numeric(10, 2), nullable=True)
    
    # Z-scores
    ndvi_zscore = Column(Numeric(5, 2), nullable=True)
    ndwi_zscore = Column(Numeric(5, 2), nullable=True)
    
    # Fuente
    satellite_source = Column(String(50), nullable=True)
    cloud_cover_pct = Column(Numeric(5, 2), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('parcel_id', 'observation_date', name='unique_parcel_date'),
    )
    
    # Relationships
    parcel = relationship("Parcel", back_populates="kpis")
    job = relationship("Job", back_populates="kpis")
    
    def __repr__(self):
        return f"<Kpi {self.parcel_id} @ {self.observation_date}>"
