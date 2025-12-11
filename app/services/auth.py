"""
Mu.Orbita API - Auth Service
Maneja JWT, password hashing, y Google OAuth
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple
from jose import JWTError, jwt
from passlib.context import CryptContext
import httpx

from app.config import settings

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Google OAuth endpoints
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica password contra hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Genera hash bcrypt de password"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crea JWT access token
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    
    to_encode.update({"exp": expire, "type": "access"})
    
    return jwt.encode(
        to_encode, 
        settings.jwt_secret_key, 
        algorithm=settings.jwt_algorithm
    )


def create_refresh_token(data: dict) -> str:
    """
    Crea JWT refresh token (más duración)
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh"})
    
    return jwt.encode(
        to_encode, 
        settings.jwt_secret_key, 
        algorithm=settings.jwt_algorithm
    )


def create_tokens(client_id: str, email: str) -> Tuple[str, str]:
    """
    Crea par de tokens (access + refresh)
    """
    token_data = {"sub": str(client_id), "email": email}
    
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)
    
    return access_token, refresh_token


def decode_token(token: str) -> Optional[dict]:
    """
    Decodifica y valida JWT token
    Retorna payload o None si inválido
    """
    try:
        payload = jwt.decode(
            token, 
            settings.jwt_secret_key, 
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None


def verify_access_token(token: str) -> Optional[dict]:
    """
    Verifica que sea access token válido
    """
    payload = decode_token(token)
    if payload and payload.get("type") == "access":
        return payload
    return None


def verify_refresh_token(token: str) -> Optional[dict]:
    """
    Verifica que sea refresh token válido
    """
    payload = decode_token(token)
    if payload and payload.get("type") == "refresh":
        return payload
    return None


async def exchange_google_code(code: str) -> Optional[dict]:
    """
    Intercambia authorization code de Google por tokens
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                }
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Google token exchange failed: {response.text}")
                return None
                
        except Exception as e:
            print(f"Google token exchange error: {e}")
            return None


async def get_google_user_info(access_token: str) -> Optional[dict]:
    """
    Obtiene info del usuario de Google usando access token
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Google userinfo failed: {response.text}")
                return None
                
        except Exception as e:
            print(f"Google userinfo error: {e}")
            return None


def get_google_auth_url() -> str:
    """
    Genera URL para iniciar flujo OAuth con Google
    """
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query_string}"
