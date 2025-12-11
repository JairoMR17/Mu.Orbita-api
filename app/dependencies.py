"""
Mu.Orbita API - Dependencies
Middleware y dependencias comunes para inyección
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.services.auth import verify_access_token
from app.models.client import Client

# Bearer token security
security = HTTPBearer()


async def get_current_client(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Client:
    """
    Dependency que obtiene el cliente actual desde el JWT token.
    Uso: current_client: Client = Depends(get_current_client)
    """
    token = credentials.credentials
    
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    client_id = payload.get("sub")
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        )
    
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cliente no encontrado",
        )
    
    return client


async def get_current_active_client(
    current_client: Client = Depends(get_current_client)
) -> Client:
    """
    Verifica que el cliente esté activo (no cancelado/inactivo)
    """
    if current_client.status in ["cancelled", "inactive"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta inactiva o cancelada",
        )
    return current_client


async def get_optional_client(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db)
) -> Optional[Client]:
    """
    Dependency opcional - no falla si no hay token.
    Útil para endpoints que funcionan con o sin auth.
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    payload = verify_access_token(token)
    
    if not payload:
        return None
    
    client_id = payload.get("sub")
    if not client_id:
        return None
    
    return db.query(Client).filter(Client.id == client_id).first()


def verify_webhook_secret(secret: str) -> bool:
    """
    Verifica secret de webhooks de n8n
    """
    from app.config import settings
    return secret == settings.n8n_webhook_secret
