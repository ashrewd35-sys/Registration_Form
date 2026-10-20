"""FastAPI application for the Channel Partner UPI application flow."""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# --- Dynamic Path Resolution for Render / Linux Environment ---
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Ensure Current Working Directory is set to project root
os.chdir(BASE_DIR)

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

# Load environment variables
load_dotenv(BASE_DIR / ".env")

# --- Robust Imports with Fallback Handling ---
try:
    from lib.db import close_db, get_session, init_db
except ModuleNotFoundError:
    try:
        from .lib.db import close_db, get_session, init_db
    except ImportError:
        import importlib
        lib_db = importlib.import_module("lib.db")
        close_db, get_session, init_db = lib_db.close_db, lib_db.get_session, lib_db.init_db

try:
    from routers.admin import router as admin_router
    from routers.applications import router as applications_router
    from routers.payments import router as payments_router
except ModuleNotFoundError:
    from .routers.admin import router as admin_router
    from .routers.applications import router as applications_router
    from .routers.payments import router as payments_router


# --- Lifespan Context Manager (Modern FastAPI Startup/Shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks: Initialize PostgreSQL tables & pool
    try:
        await init_db()
    except Exception as err:
        print(f"[Warning] Database initialization error during startup: {err}")
    yield
    # Shutdown tasks: Clean up connections
    try:
        await close_db()
    except Exception as err:
        print(f"[Warning] Error closing database connections: {err}")


app = FastAPI(
    title="Channel Partner Application",
    version="1.0.0",
    lifespan=lifespan,
)

# --- CORS Configuration ---
origins_env = os.getenv("CORS_ORIGINS", "")
origins = [origin.strip().rstrip("/") for origin in origins_env.split(",") if origin.strip()]

if not origins:
    origins = [
        "https://ashrewd35-sys.github.io",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Router Registration ---
api_router = APIRouter(prefix="/api")
api_router.include_router(payments_router)
api_router.include_router(applications_router)
api_router.include_router(admin_router)
app.include_router(api_router)


# --- Health Check Endpoint ---
@app.get("/api/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable.") from exc
    return {"status": "ok"}


# --- Static Frontend Serving (Optional) ---
frontend_dir = BASE_DIR.parent / "frontend"

if frontend_dir.exists():
    @app.get("/admin", include_in_schema=False)
    async def admin_page() -> FileResponse:
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="Admin page index.html not found.")

    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
