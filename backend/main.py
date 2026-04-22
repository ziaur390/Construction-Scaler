"""
Construction Scaler — FastAPI Backend
Handles PDF upload, page rendering, and scale detection.
Deploy on Render (free tier).
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import engine, get_db
import models
from pdf_service import PDFService

# Create database tables
models.Base.metadata.create_all(bind=engine)

# ── Session Store ────────────────────────────────────────────────

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
SESSION_TTL = 30 * 60  # 30 minutes

sessions: dict[str, dict] = {}


def _cleanup_sessions():
    """Remove sessions older than SESSION_TTL."""
    now = time.time()
    expired = [sid for sid, s in sessions.items() if now - s["created"] > SESSION_TTL]
    for sid in expired:
        try:
            sessions[sid]["service"].close()
        except Exception:
            pass
        del sessions[sid]


# ── App Lifecycle ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # Cleanup on shutdown
    for s in sessions.values():
        try:
            s["service"].close()
        except Exception:
            pass
    sessions.clear()


# ── FastAPI App ──────────────────────────────────────────────────

app = FastAPI(
    title="Construction Scaler API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Open for prototype; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoints ────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "construction-scaler-api",
        "active_sessions": len(sessions),
    }


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """Upload a PDF and create a session for page rendering."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large (max {MAX_FILE_SIZE // (1024*1024)} MB).")

    # Cleanup old sessions before creating new ones
    _cleanup_sessions()

    try:
        service = PDFService(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to open PDF: {exc}")

    session_id = uuid.uuid4().hex[:12]
    sessions[session_id] = {
        "service": service,
        "filename": file.filename,
        "created": time.time(),
    }

    return {
        "session_id": session_id,
        "page_count": service.page_count,
        "filename": file.filename,
    }


@app.get("/api/page/{session_id}/{page_num}")
async def get_page(session_id: str, page_num: int):
    """Render a specific page as JPEG + detected scales."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found or expired. Please re-upload.")

    service: PDFService = sessions[session_id]["service"]

    if page_num < 1 or page_num > service.page_count:
        raise HTTPException(status_code=400, detail="Invalid page number.")

    try:
        return service.render_page(page_num - 1)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Render error: {exc}")


@app.post("/api/measurements")
async def save_measurement(data: dict, db: Session = Depends(get_db)):
    """Save a measurement to the database."""
    new_m = models.Measurement(
        session_id=data.get("session_id"),
        filename=data.get("filename"),
        page_num=data.get("page_num"),
        type=data.get("type"),
        points=data.get("points"),
        result_text=data.get("result_text"),
        scale_label=data.get("scale_label")
    )
    db.add(new_m)
    db.commit()
    db.refresh(new_m)
    return {"status": "saved", "id": new_m.id}


@app.get("/api/measurements/{filename}")
async def get_measurements(filename: str, db: Session = Depends(get_db)):
    """Retrieve all measurements for a specific file."""
    results = db.query(models.Measurement).filter(models.Measurement.filename == filename).all()
    return results


@app.delete("/api/session/{session_id}")
async def close_session(session_id: str):
    """Close a session and free resources."""
    if session_id in sessions:
        try:
            sessions[session_id]["service"].close()
        except Exception:
            pass
        del sessions[session_id]
    return {"status": "closed"}
