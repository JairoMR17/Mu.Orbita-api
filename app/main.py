"""
Mu.Orbita API - Main Application
FastAPI backend para dashboard de agricultura de precisión
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time

from app.config import settings
from app.database import check_db_connection
from app.routers import auth_router, dashboard_router, webhooks_router, gee_router, reports_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle events: startup y shutdown
    """
    # Startup
    print(f"🚀 Starting {settings.app_name}...")
    
    # Verificar conexión a BD
    if check_db_connection():
        print("✅ Database connection OK")
    else:
        print("❌ Database connection FAILED")
    
    yield
    
    # Shutdown
    print(f"👋 Shutting down {settings.app_name}...")


# Crear app
app = FastAPI(
    title=settings.app_name,
    description="API backend para Mu.Orbita - Plataforma de agricultura de precisión satelital",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Handler global para excepciones no controladas
    """
    if settings.debug:
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc),
                "type": type(exc).__name__
            }
        )
    else:
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno del servidor"}
        )


# Root endpoint
@app.get("/")
async def root():
    return {
        "service": settings.app_name,
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs" if settings.debug else "disabled"
    }


# Health check
@app.get("/health")
async def health_check():
    db_ok = check_db_connection()
    return {
        "status": "healthy" if db_ok else "unhealthy",
        "database": "connected" if db_ok else "disconnected",
        "environment": settings.app_env
    }


# Incluir routers
app.include_router(auth_router, prefix=f"/api/{settings.api_version}")
app.include_router(dashboard_router, prefix=f"/api/{settings.api_version}")
app.include_router(webhooks_router, prefix=f"/api/{settings.api_version}")


# Para desarrollo local
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
app.include_router(gee_router)
app.include_router(reports_router)
