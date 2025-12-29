"""FastAPI application for visual-cataloguer web interface."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from cataloguer import __version__
from cataloguer.api.deps import DbDep, configure_database
from cataloguer.api.routes import images, items, locations, search

# Create app
app = FastAPI(
    title="Visual Cataloguer",
    description="Browse and manage your catalogued collection",
    version=__version__,
)

# CORS for development (React dev server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(items.router, prefix="/api/items", tags=["items"])
app.include_router(locations.router, prefix="/api/locations", tags=["locations"])
app.include_router(images.router, prefix="/api", tags=["images"])
app.include_router(search.router, prefix="/api", tags=["search"])


@app.get("/api/stats")
def get_stats(db: DbDep) -> dict[str, int]:
    """Get collection statistics."""
    return db.get_stats()


@app.get("/api/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "version": __version__}


# Serve static files (frontend) if available
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse)
async def serve_index() -> FileResponse:
    """Serve the frontend index page."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    # Return a simple message if no frontend is built
    return HTMLResponse(  # type: ignore[return-value]
        content="""
        <html>
        <head><title>Visual Cataloguer API</title></head>
        <body>
            <h1>Visual Cataloguer API</h1>
            <p>API is running. Frontend not available.</p>
            <p>API docs: <a href="/docs">/docs</a></p>
        </body>
        </html>
        """
    )


# Mount assets directory if it exists
if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


# Re-export configure_database for CLI use
__all__ = ["app", "configure_database"]
