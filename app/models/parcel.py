"""
Mu.Orbita API - Parcel Model
"""

from sqlalchemy import Column, String, Numeric, Boolean, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.database import Base


class Parcel(Base):
    __tablename__ = "parcels"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign key
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    
    # Identificación
    parcel_name = Column(String(255), nullable=False)
    parcel_code = Column(String(50), nullable=True)  # Código catastral
    
    # Datos agronómicos
    hectares = Column(Numeric(10, 2), nullable=False)
    crop_type = Column(String(50), nullable=False)
    crop_variety = Column(String(100), nullable=True)
    planting_year = Column(Integer, nullable=True)
    irrigation_type = Column(String(50), nullable=True)
    
    # Ubicación
    location_name = Column(String(255), nullable=True)
    municipality = Column(String(100), nullable=True)
    province = Column(String(100), nullable=True)
    
    # ROI
    roi_geojson = Column(JSONB, nullable=False)
    centroid_lat = Column(Numeric(9, 6), nullable=True)
    centroid_lon = Column(Numeric(9, 6), nullable=True)
    
    # Estado
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Metadata
    parcel_metadata = Column(JSONB, default={})
    
    # Relationships
    client = relationship("Client", back_populates="parcels")
    kpis = relationship("Kpi", back_populates="parcel", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="parcel")
    
    def __repr__(self):
        return f"<Parcel {self.parcel_name} ({self.hectares} ha)>"
