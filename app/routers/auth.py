"""
Mu.Orbita API - Auth Router
Endpoints de autenticación: login, register, Google OAuth
"""

from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models.client import Client
from app.schemas import (
    LoginRequest, RegisterRequest, TokenResponse, 
    ClientResponse, GoogleAuthRequest, MessageResponse,
    PasswordChangeRequest
)
from app.services.auth import (
    verify_password, get_password_hash, create_tokens,
    verify_refresh_token, exchange_google_code, 
    get_google_user_info, get_google_auth_url
)
from app.dependencies import get_current_client
from app.config import settings

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=TokenResponse)
async def register(
    request: RegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Registro de nuevo cliente con email/password
    """
    # Verificar que email no exista
    existing = db.query(Client).filter(Client.email == request.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este email ya está registrado"
        )
    
    # Crear cliente
    client = Client(
        email=request.email,
        password_hash=get_password_hash(request.password),
        client_name=request.client_name,
        company=request.company,
        phone=request.phone,
        status="trial",
        source="web_register",
    )
    
    db.add(client)
    db.commit()
    db.refresh(client)
    
    # Generar tokens
    access_token, refresh_token = create_tokens(str(client.id), client.email)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Login con email/password
    """
    client = db.query(Client).filter(Client.email == request.email).first()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos"
        )
    
    if not client.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Esta cuenta usa Google para iniciar sesión"
        )
    
    if not verify_password(request.password, client.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos"
        )
    
    # Actualizar last_login
    client.last_login_at = datetime.utcnow()
    db.commit()
    
    # Generar tokens
    access_token, refresh_token = create_tokens(str(client.id), client.email)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60
    )


@router.get("/google")
async def google_login():
    """
    Inicia flujo OAuth con Google.
    Redirige al usuario a la página de login de Google.
    """
    auth_url = get_google_auth_url()
    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
async def google_callback(
    code: str,
    db: Session = Depends(get_db)
):
    """
    Callback de Google OAuth.
    Recibe el authorization code y lo intercambia por tokens.
    """
    # Intercambiar code por tokens de Google
    token_data = await exchange_google_code(code)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error al autenticar con Google"
        )
    
    # Obtener info del usuario
    google_access_token = token_data.get("access_token")
    user_info = await get_google_user_info(google_access_token)
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error al obtener información de Google"
        )
    
    google_id = user_info.get("id")
    email = user_info.get("email")
    name = user_info.get("name", email.split("@")[0])
    avatar = user_info.get("picture")
    
    # Buscar cliente existente por google_id o email
    client = db.query(Client).filter(
        (Client.google_id == google_id) | (Client.email == email)
    ).first()
    
    if client:
        # Actualizar datos de Google si es necesario
        if not client.google_id:
            client.google_id = google_id
        if avatar:
            client.avatar_url = avatar
        client.last_login_at = datetime.utcnow()
        db.commit()
    else:
        # Crear nuevo cliente
        client = Client(
            email=email,
            google_id=google_id,
            client_name=name,
            avatar_url=avatar,
            status="trial",
            source="google_oauth",
        )
        db.add(client)
        db.commit()
        db.refresh(client)
    
    # Generar tokens
    access_token, refresh_token = create_tokens(str(client.id), client.email)
    
    # Redirigir al frontend con tokens
    redirect_url = (
        f"{settings.frontend_url}/auth/callback"
        f"?access_token={access_token}"
        f"&refresh_token={refresh_token}"
    )
    
    return RedirectResponse(url=redirect_url)


@router.post("/google/token", response_model=TokenResponse)
async def google_token(
    request: GoogleAuthRequest,
    db: Session = Depends(get_db)
):
    """
    Alternativa al callback: el frontend envía el code directamente.
    Útil para SPAs que manejan el redirect ellos mismos.
    """
    # Intercambiar code por tokens de Google
    token_data = await exchange_google_code(request.code)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error al autenticar con Google"
        )
    
    # Obtener info del usuario
    google_access_token = token_data.get("access_token")
    user_info = await get_google_user_info(google_access_token)
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error al obtener información de Google"
        )
    
    google_id = user_info.get("id")
    email = user_info.get("email")
    name = user_info.get("name", email.split("@")[0])
    avatar = user_info.get("picture")
    
    # Buscar o crear cliente
    client = db.query(Client).filter(
        (Client.google_id == google_id) | (Client.email == email)
    ).first()
    
    if client:
        if not client.google_id:
            client.google_id = google_id
        if avatar:
            client.avatar_url = avatar
        client.last_login_at = datetime.utcnow()
        db.commit()
    else:
        client = Client(
            email=email,
            google_id=google_id,
            client_name=name,
            avatar_url=avatar,
            status="trial",
            source="google_oauth",
        )
        db.add(client)
        db.commit()
        db.refresh(client)
    
    # Generar tokens
    access_token, refresh_token = create_tokens(str(client.id), client.email)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    refresh_token: str,
    db: Session = Depends(get_db)
):
    """
    Renueva tokens usando refresh token
    """
    payload = verify_refresh_token(refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o expirado"
        )
    
    client_id = payload.get("sub")
    client = db.query(Client).filter(Client.id == client_id).first()
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cliente no encontrado"
        )
    
    # Generar nuevos tokens
    new_access_token, new_refresh_token = create_tokens(str(client.id), client.email)
    
    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.access_token_expire_minutes * 60
    )


@router.get("/me", response_model=ClientResponse)
async def get_me(
    current_client: Client = Depends(get_current_client)
):
    """
    Obtiene datos del cliente autenticado
    """
    return current_client


@router.put("/me", response_model=ClientResponse)
async def update_profile(
    request: dict,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Actualiza datos del perfil del cliente autenticado.
    Campos permitidos: client_name, company, phone
    """
    # Campos permitidos para actualizar
    allowed_fields = ['client_name', 'company', 'phone']
    
    for field in allowed_fields:
        if field in request and request[field] is not None:
            setattr(current_client, field, request[field])
    
    current_client.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_client)
    
    return current_client


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    request: PasswordChangeRequest,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """
    Cambia la contraseña del cliente autenticado
    """
    if not current_client.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta cuenta usa Google para iniciar sesión. No se puede cambiar la contraseña."
        )
    
    if not verify_password(request.current_password, current_client.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña actual incorrecta"
        )
    
    current_client.password_hash = get_password_hash(request.new_password)
    db.commit()
    
    return MessageResponse(message="Contraseña actualizada correctamente")


@router.post("/logout", response_model=MessageResponse)
async def logout(
    current_client: Client = Depends(get_current_client)
):
    """
    Logout - En JWT stateless no hay mucho que hacer server-side.
    El frontend debe eliminar los tokens.
    """
    # Podrías implementar una blacklist de tokens aquí si quieres
    return MessageResponse(message="Sesión cerrada correctamente")
