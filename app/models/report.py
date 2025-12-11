"""
Mu.Orbita API - Report Model
"""

from sqlalchemy import Column, String, DateTime, Date, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.database import Base


class Report(Base):
    __tablename__ = "reports"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign keys
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    
    # Tipo
    report_type = Column(String(50), nullable=False)  # baseline, bisemanal, on_demand
    
    # Archivos
    pdf_url = Column(String(500), nullable=True)
    pdf_drive_id = Column(String(255), nullable=True)
    html_content = Column(Text, nullable=True)
    
    # Período
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # KPIs resumen
    ndvi_current = Column(String(10), nullable=True)
    ndvi_change = Column(String(10), nullable=True)
    main_findings = Column(ARRAY(Text), nullable=True)
    priority_actions = Column(ARRAY(Text), nullable=True)
    
    # Entrega
    sent_at = Column(DateTime(timezone=True), nullable=True)
    sent_to = Column(String(255), nullable=True)
    opened_at = Column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    report_metadata = Column(JSONB, default={})
    
    # Relationships
    job = relationship("Job", back_populates="reports")
    client = relationship("Client", back_populates="reports")
    
    def __repr__(self):
        return f"<Report {self.report_type} @ {self.generated_at}>"
