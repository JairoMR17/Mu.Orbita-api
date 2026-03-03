"""
Mu.Orbita Image Provider v1.0
==============================

ARCHIVO NUEVO: app/services/image_provider.py

Abstracción de almacenamiento de imágenes satelitales.
MVP: PostgreSQL. Futuro: S3/CloudFlare R2 para GeoTIFF.

USO:
    from app.services.image_provider import get_image_provider
    
    provider = get_image_provider()
    provider.store_base64(job_id, 'NDVI', b64_data, metadata=bounds)
    b64 = provider.retrieve_base64(job_id, 'NDVI')
    png_map = provider.load_all_as_map(job_id)

CAMBIAR A S3:
    Setear IMAGE_STORAGE_PROVIDER=s3 + S3_BUCKET + S3_ENDPOINT_URL en env
    → Zero cambios en código consumidor
"""

import os
import base64
import logging
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class ImageProvider(ABC):
    """Interfaz abstracta para almacenamiento de imágenes satelitales."""

    @abstractmethod
    def store(self, job_id: str, index_type: str, data: bytes,
              format: str = 'png', metadata: dict = None) -> str:
        """Almacena imagen desde bytes. Devuelve identificador único."""
        pass

    @abstractmethod
    def store_base64(self, job_id: str, index_type: str, b64_data: str,
                     format: str = 'png', metadata: dict = None) -> str:
        """Almacena imagen desde base64 string."""
        pass

    @abstractmethod
    def retrieve_base64(self, job_id: str, index_type: str) -> Optional[str]:
        """Recupera imagen como base64 string (para PDF inline)."""
        pass

    @abstractmethod
    def retrieve_bytes(self, job_id: str, index_type: str) -> Optional[bytes]:
        """Recupera imagen como bytes (para HTTP response)."""
        pass

    @abstractmethod
    def list_images(self, job_id: str) -> List[Dict[str, Any]]:
        """Lista imágenes disponibles para un job."""
        pass

    @abstractmethod
    def delete_job_images(self, job_id: str) -> int:
        """Elimina todas las imágenes de un job. Devuelve count."""
        pass

    @abstractmethod
    def load_all_as_map(self, job_id: str) -> Dict[str, str]:
        """Carga TODAS las imágenes como dict {index_type: base64}."""
        pass


class PostgresImageProvider(ImageProvider):
    """
    MVP: Almacena PNGs como base64 en PostgreSQL.
    
    Ventajas: Simple, sin dependencias externas, backup con DB.
    Límite práctico: ~5-10 MB por imagen (OK para PNG 1024px).
    Para GeoTIFF (50-200 MB): usar S3ImageProvider.
    """

    def _get_db(self):
        from app.database import SessionLocal
        return SessionLocal()

    def _get_model(self):
        from app.models.gee_image import GEEImage
        return GEEImage

    def store(self, job_id, index_type, data, format='png', metadata=None):
        b64 = base64.b64encode(data).decode('utf-8')
        return self.store_base64(job_id, index_type, b64, format, metadata)

    def store_base64(self, job_id, index_type, b64_data, format='png', metadata=None):
        GEEImage = self._get_model()
        db = self._get_db()
        try:
            existing = db.query(GEEImage).filter(
                GEEImage.job_id == job_id,
                GEEImage.index_type == index_type
            ).first()

            bounds = metadata or {}
            size_kb = len(b64_data) * 3 // 4 // 1024  # approx decoded size

            if existing:
                existing.png_base64 = b64_data
                existing.filename = f"PNG_{index_type}.png"
                if bounds:
                    existing.bounds_north = bounds.get('north')
                    existing.bounds_south = bounds.get('south')
                    existing.bounds_east = bounds.get('east')
                    existing.bounds_west = bounds.get('west')
                action = 'updated'
            else:
                db.add(GEEImage(
                    job_id=job_id,
                    index_type=index_type,
                    filename=f"PNG_{index_type}.png",
                    png_base64=b64_data,
                    bounds_north=bounds.get('north'),
                    bounds_south=bounds.get('south'),
                    bounds_east=bounds.get('east'),
                    bounds_west=bounds.get('west'),
                ))
                action = 'created'

            db.commit()
            logger.info(f"📷 {action} {index_type} for {job_id} (~{size_kb} KB)")
            return f"db://{job_id}/{index_type}"

        except Exception as e:
            db.rollback()
            logger.error(f"❌ Store failed {index_type}/{job_id}: {e}")
            raise
        finally:
            db.close()

    def retrieve_base64(self, job_id, index_type):
        GEEImage = self._get_model()
        db = self._get_db()
        try:
            img = db.query(GEEImage).filter(
                GEEImage.job_id == job_id,
                GEEImage.index_type == index_type
            ).first()
            if img and img.png_base64 and isinstance(img.png_base64, str):
                return img.png_base64
            return None
        finally:
            db.close()

    def retrieve_bytes(self, job_id, index_type):
        b64 = self.retrieve_base64(job_id, index_type)
        if b64:
            return base64.b64decode(b64)
        return None

    def list_images(self, job_id):
        GEEImage = self._get_model()
        db = self._get_db()
        try:
            images = db.query(GEEImage).filter(
                GEEImage.job_id == job_id
            ).all()
            return [{
                'index_type': img.index_type,
                'filename': img.filename,
                'has_data': bool(img.png_base64),
                'size_kb': len(img.png_base64) * 3 // 4 // 1024 if img.png_base64 else 0,
                'bounds': {
                    'north': img.bounds_north,
                    'south': img.bounds_south,
                    'east': img.bounds_east,
                    'west': img.bounds_west,
                } if img.bounds_north is not None else None
            } for img in images]
        finally:
            db.close()

    def delete_job_images(self, job_id):
        GEEImage = self._get_model()
        db = self._get_db()
        try:
            count = db.query(GEEImage).filter(
                GEEImage.job_id == job_id
            ).delete()
            db.commit()
            return count
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def load_all_as_map(self, job_id) -> Dict[str, str]:
        """
        Carga TODAS las imágenes de un job como dict {index_type: base64}.
        Optimizado para el PDF generator (una sola query).
        """
        GEEImage = self._get_model()
        db = self._get_db()
        try:
            images = db.query(
                GEEImage.index_type, GEEImage.png_base64
            ).filter(
                GEEImage.job_id == job_id,
                GEEImage.png_base64.isnot(None)
            ).all()

            result = {}
            for index_type, b64 in images:
                if b64 and isinstance(b64, str) and not b64.startswith('['):
                    result[index_type] = b64

            logger.info(f"📦 Loaded {len(result)} images for {job_id}: "
                        f"{list(result.keys())}")
            return result
        finally:
            db.close()


# ============================================================================
# FUTURO: S3/CloudFlare R2 Provider (no implementar hasta que sea necesario)
# ============================================================================

class S3ImageProvider(ImageProvider):
    """
    FUTURO: Para GeoTIFF y archivos grandes.
    Requiere: pip install boto3
    Config: S3_BUCKET, S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
    """

    def __init__(self, bucket: str, endpoint_url: str = None):
        try:
            import boto3
            self.s3 = boto3.client('s3', endpoint_url=endpoint_url)
            self.bucket = bucket
        except ImportError:
            raise ImportError("boto3 required for S3 storage. pip install boto3")

    def _key(self, job_id, index_type, format='png'):
        return f"satellite/{job_id}/{index_type}.{format}"

    def store(self, job_id, index_type, data, format='png', metadata=None):
        key = self._key(job_id, index_type, format)
        content_type = {
            'png': 'image/png',
            'tiff': 'image/tiff',
            'cog': 'image/tiff',
        }.get(format, 'application/octet-stream')

        self.s3.put_object(
            Bucket=self.bucket, Key=key, Body=data,
            ContentType=content_type,
            Metadata={k: str(v) for k, v in (metadata or {}).items()}
        )
        logger.info(f"📷 Stored {key} ({len(data) // 1024} KB)")
        return f"s3://{self.bucket}/{key}"

    def store_base64(self, job_id, index_type, b64_data, format='png', metadata=None):
        data = base64.b64decode(b64_data)
        return self.store(job_id, index_type, data, format, metadata)

    def retrieve_base64(self, job_id, index_type):
        data = self.retrieve_bytes(job_id, index_type)
        if data:
            return base64.b64encode(data).decode('utf-8')
        return None

    def retrieve_bytes(self, job_id, index_type):
        for fmt in ('png', 'tiff', 'cog'):
            key = self._key(job_id, index_type, fmt)
            try:
                obj = self.s3.get_object(Bucket=self.bucket, Key=key)
                return obj['Body'].read()
            except Exception:
                continue
        return None

    def list_images(self, job_id):
        prefix = f"satellite/{job_id}/"
        resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        return [{
            'key': obj['Key'],
            'size_kb': obj['Size'] // 1024,
            'index_type': obj['Key'].split('/')[-1].split('.')[0],
        } for obj in resp.get('Contents', [])]

    def delete_job_images(self, job_id):
        images = self.list_images(job_id)
        if images:
            self.s3.delete_objects(
                Bucket=self.bucket,
                Delete={'Objects': [{'Key': img['key']} for img in images]}
            )
        return len(images)

    def load_all_as_map(self, job_id):
        images = self.list_images(job_id)
        result = {}
        for img in images:
            b64 = self.retrieve_base64(job_id, img['index_type'])
            if b64:
                result[img['index_type']] = b64
        return result


# ============================================================================
# FACTORY
# ============================================================================

_provider_instance = None


def get_image_provider() -> ImageProvider:
    """
    Retorna el provider configurado.
    Cachea la instancia para reutilizar conexiones.
    
    Config via env var IMAGE_STORAGE_PROVIDER:
        'postgres' (default) → PostgresImageProvider
        's3' → S3ImageProvider (requiere boto3 + S3_BUCKET)
    """
    global _provider_instance

    if _provider_instance is not None:
        return _provider_instance

    provider_type = os.environ.get('IMAGE_STORAGE_PROVIDER', 'postgres')

    if provider_type == 's3':
        _provider_instance = S3ImageProvider(
            bucket=os.environ['S3_BUCKET'],
            endpoint_url=os.environ.get('S3_ENDPOINT_URL')
        )
    else:
        _provider_instance = PostgresImageProvider()

    logger.info(f"🗄️ Image provider: {provider_type}")
    return _provider_instance
