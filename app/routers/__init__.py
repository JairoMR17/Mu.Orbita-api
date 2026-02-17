"""
Mu.Orbita API - Routers
"""
from app.routers.auth import router as auth_router
from app.routers.dashboard import router as dashboard_router
from app.routers.webhooks import router as webhooks_router
from app.routers.gee import router as gee_router
from app.routers.reports import router as reports_router
from .images import router as images_router

__all__ = ["auth_router", "dashboard_router", "webhooks_router", "gee_router", "reports_router"]
