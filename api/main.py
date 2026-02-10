"""FastAPI application for Telegram Post Exchange."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from storage import get_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    db = get_database()
    yield
    # Shutdown
    await db.close()


def create_app() -> FastAPI:
    """Create a FastAPI app instance (useful for tests and multi-env setups)."""
    settings = get_settings()

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "ok"}

    # Import and include routers
    from api.routers import auth, feed, vote, summary, stats, admin, search

    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(feed.router, prefix="/feed", tags=["feed"])
    app.include_router(search.router, prefix="/search", tags=["search"])
    app.include_router(vote.router, prefix="/vote", tags=["vote"])
    app.include_router(summary.router, prefix="/summary", tags=["summary"])
    app.include_router(stats.router, prefix="/stats", tags=["stats"])
    app.include_router(admin.router, prefix="/admin", tags=["admin"])

    return app


app = create_app()
