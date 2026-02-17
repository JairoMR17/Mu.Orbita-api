"""
MU.ORBITA - Modelo GEEImage
Almacena referencias a imágenes PNG en Google Drive
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime

# Ajusta este import según tu estructura
from app.database import Base


class GEEImage(Base):
    __tablename__ = "gee_images"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, index=True, nullable=False)  # JOB_123456789
    
    # Tipo de imagen
    index_type = Column(String, nullable=False)  # NDVI, NDWI, EVI, VRA, etc.
    filename = Column(String, nullable=False)    # PNG_NDVI.png
    
    # Google Drive
    gdrive_file_id = Column(String)              # El ID del archivo en Drive
    gdrive_folder = Column(String)               # Carpeta en Drive (WEB, TIFF, etc.)
    
    # Metadatos
    file_format = Column(String, default='PNG')  # PNG, TIFF, CSV
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Índice compuesto para búsquedas rápidas
    __table_args__ = (
        Index('ix_gee_images_job_filename', 'job_id', 'filename'),
        Index('ix_gee_images_job_index', 'job_id', 'index_type'),
    )
    
    def __repr__(self):
        return f"<GEEImage {self.job_id}/{self.filename}>"
    
    @property
    def gdrive_direct_url(self):
        """URL directa para visualizar/descargar desde Google Drive"""
        if self.gdrive_file_id:
            return f"https://drive.google.com/uc?export=view&id={self.gdrive_file_id}"
        return None
    
    @classmethod
    def create_for_job(cls, job_id: str, index_type: str, gdrive_file_id: str, folder: str = "WEB"):
        """Factory method para crear una imagen"""
        filename = f"PNG_{index_type}.png" if folder == "WEB" else f"TIFF_{index_type}.tif"
        file_format = "PNG" if folder == "WEB" else "TIFF"
        
        return cls(
            job_id=job_id,
            index_type=index_type,
            filename=filename,
            gdrive_file_id=gdrive_file_id,
            gdrive_folder=folder,
            file_format=file_format
        )
