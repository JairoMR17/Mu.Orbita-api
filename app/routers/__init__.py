"""
Mu.Orbita API - Routers
"""

from app.routers.auth import router as auth_router
from app.routers.dashboard import router as dashboard_router
from app.routers.webhooks import router as webhooks_router

__all__ = ["auth_router", "dashboard_router", "webhooks_router"]
