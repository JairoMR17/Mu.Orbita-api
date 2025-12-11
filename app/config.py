"""
Mu.Orbita API - Configuration
Carga variables de entorno y define settings globales
"""

from pydantic_settings import BaseSettings
from typing import List
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "Mu.Orbita API"
    app_env: str = "development"
    debug: bool = True
    api_version: str = "v1"
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Database
    database_url: str
    
    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    
    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    
    # Frontend
    frontend_url: str = "http://localhost:3000"
    
    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    
    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    
    # n8n
    n8n_webhook_secret: str = ""
    
    # Google Drive
    google_drive_folder_id: str = ""
    
    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Singleton para settings - se cachea en memoria"""
    return Settings()


# Instancia global
settings = get_settings()
