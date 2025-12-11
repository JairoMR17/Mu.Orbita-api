"""
Mu.Orbita API - Client Model
"""

from sqlalchemy import Column, String, Numeric, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.database import Base


class Client(Base):
    __tablename__ = "clients"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Auth
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)  # NULL para OAuth-only
    
    # Google OAuth
    google_id = Column(String(255), unique=True, nullable=True)
    avatar_url = Column(Text, nullable=True)
    
    # Info básica
    client_name = Column(String(255), nullable=False)
    company = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    
    # Explotación
    hectares = Column(Numeric(10, 2), nullable=True)
    crop_type = Column(String(50), nullable=True)
    location = Column(String(255), nullable=True)
    
    # ROI legacy (para clientes con 1 sola parcela)
    roi_geojson = Column(JSONB, nullable=True)
    
    # Estado
    status = Column(String(50), default="lead", index=True)
    source = Column(String(100), nullable=True)
    
    # Suscripción
    subscription_tier = Column(String(50), nullable=True)
    subscription_status = Column(String(50), nullable=True)
    subscription_start_date = Column(DateTime(timezone=True), nullable=True)
    subscription_end_date = Column(DateTime(timezone=True), nullable=True)
    
    # Stripe
    stripe_customer_id = Column(String(255), unique=True, nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    client_metadata = Column(JSONB, default={})
    
    # Relationships
    parcels = relationship("Parcel", back_populates="client", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="client", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="client", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Client {self.email}>"
