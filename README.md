# Construction Scaler

A precision web tool for measuring distances and areas on construction blueprint PDFs with automatic scale detection.

## Architecture

| Layer | Tech | Hosting |
|-------|------|---------|
| **Frontend** | HTML/CSS/JS (Canvas API) | Vercel (free) |
| **Backend API** | FastAPI + PyMuPDF | Render (free) |
| **Database** | PostgreSQL (Render) / SQLite (local) | Render (free) |

## Local Development

### 1. Start the backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --port 8000 --reload
```

### 2. Start the frontend server
```bash
python server.py
# Open http://127.0.0.1:8001
```

### 3. Or use the batch script (Windows)
```bash
run_project.bat
```

## Features
- **PDF Upload & Rendering** — Upload construction blueprints, rendered server-side with PyMuPDF
- **Automatic Scale Detection** — Parses scale text from PDF layers (1/8" = 1'-0", 1:100, etc.)
- **Distance Measurement** — Click two points → real-world distance using detected scale
- **Area Measurement** — Click polygon points → real-world area calculation
- **Zoom/Pan** — Mouse wheel zoom, Ctrl+click pan
- **Measurement Persistence** — All measurements saved to database

## Deployment
See the deployment guide for Vercel (frontend) + Render (backend + PostgreSQL).
