"""
Mu.Orbita API - Database Connection
Configuración de SQLAlchemy para PostgreSQL (Neon)
"""

from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings

# Neon requiere SSL y NullPool para serverless
# NullPool desactiva connection pooling (Neon lo maneja)
engine = create_engine(
    settings.database_url,
    poolclass=NullPool,  # Importante para Neon serverless
    echo=settings.debug,  # Log SQL queries en desarrollo
)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base para modelos
Base = declarative_base()


def get_db():
    """
    Dependency para obtener sesión de BD.
    Uso: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Inicializa la BD creando todas las tablas.
    Solo usar en desarrollo - en producción usar migraciones.
    """
    Base.metadata.create_all(bind=engine)


def check_db_connection() -> bool:
    """
    Verifica que la conexión a BD funcione.
    Útil para health checks.
    """
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception as e:
        print(f"Database connection error: {e}")
        return False