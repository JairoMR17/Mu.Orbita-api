"""
MU.ORBITA - Modelo GEEImage v5.0
==================================

CAMBIOS V5.0:
✅ Nuevo campo: png_base64 (TEXT) — almacena PNG completo como base64
✅ Nuevos campos: bounds_north/south/east/west — para Leaflet overlay
✅ Campo gdrive_file_id mantenido para backward compatibility (legacy data)
✅ Eliminado: gdrive_folder (ya no se usa Drive)

MIGRACIÓN SQL (ejecutar en Neon):
    ALTER TABLE gee_images ADD COLUMN IF NOT EXISTS png_base64 TEXT;
    ALTER TABLE gee_images ADD COLUMN IF NOT EXISTS bounds_north FLOAT;
    ALTER TABLE gee_images ADD COLUMN IF NOT EXISTS bounds_south FLOAT;
    ALTER TABLE gee_images ADD COLUMN IF NOT EXISTS bounds_east FLOAT;
    ALTER TABLE gee_images ADD COLUMN IF NOT EXISTS bounds_west FLOAT;
"""

from sqlalchemy import Column, String, Text, Float, DateTime, Integer, func
from app.database import Base


class GEEImage(Base):
    __tablename__ = "gee_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Identificación
    job_id = Column(String(100), nullable=False, index=True)
    index_type = Column(String(20), nullable=False)  # NDVI, NDWI, EVI, etc.
    filename = Column(String(100), nullable=False)    # PNG_NDVI.png
    
    # V5.0: PNG almacenado como base64
    png_base64 = Column(Text, nullable=True)
    
    # V5.0: Bounds para Leaflet image overlay
    bounds_north = Column(Float, nullable=True)
    bounds_south = Column(Float, nullable=True)
    bounds_east = Column(Float, nullable=True)
    bounds_west = Column(Float, nullable=True)
    
    # Legacy V4: referencia a Drive (mantener para datos existentes)
    gdrive_file_id = Column(String(200), nullable=True)
    gdrive_folder = Column(String(20), nullable=True)  # WEB, REPORT, TIFF
    
    # Metadata
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        source = "db" if self.png_base64 else "drive" if self.gdrive_file_id else "empty"
        return f"<GEEImage {self.job_id}/{self.index_type} [{source}]>"

    # Legacy helper (mantener por si algún código viejo lo usa)
    @classmethod
    def create_for_job(cls, job_id, index_type, gdrive_file_id=None, 
                       folder="WEB", png_base64=None, bounds=None):
        filename = f"PNG_{index_type}.png"
        return cls(
            job_id=job_id,
            index_type=index_type,
            filename=filename,
            gdrive_file_id=gdrive_file_id,
            gdrive_folder=folder,
            png_base64=png_base64,
            bounds_north=bounds.get('north') if bounds else None,
            bounds_south=bounds.get('south') if bounds else None,
            bounds_east=bounds.get('east') if bounds else None,
            bounds_west=bounds.get('west') if bounds else None,
        )
