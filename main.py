"""
main.py — FastAPI application serving the ingested job data.

The API has three responsibilities:
  1. Serve the most recently ingested job listings from the local data file.
  2. Expose a /ingest endpoint that triggers a fresh ingestion run on demand.
  3. Report its own health so a deployment platform can route traffic correctly.

Design note: in a production deployment the ingestion run would be triggered
by a scheduled cron job or a Celery worker, not by an HTTP request. For this
demo, the on-demand /ingest endpoint makes it easy for a reviewer to watch the
pipeline execute in real time without needing access to the server's cron.
"""

import json
import logging
import os
import threading
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ingester import run_ingestion, DATA_FILE

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Job Ingestion API",
    description=(
        "Demonstrates a resilient job-listing ingestion pipeline. "
        "Data is sourced from the public Hacker News Jobs API. "
        "See /docs for interactive API documentation."
    ),
    version="1.0.0",
)

# CORS origins are configurable via env var so this isn't wide-open by default
# in a real deployment; falls back to "*" for the demo's convenience.
_cors_origins = os.getenv("ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _cors_origins == "*" else [o.strip() for o in _cors_origins.split(",")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# A simple in-process lock to prevent concurrent ingestion runs from racing
# each other and corrupting the output file.
_ingestion_lock = threading.Lock()
_ingestion_running = False


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class JobListing(BaseModel):
    id: int
    title: str
    company: Optional[str] = None
    url: Optional[str] = None
    posted_by: str
    posted_at_unix: int
    posted_at_iso: str
    source: str


class JobsResponse(BaseModel):
    ingested_at: Optional[str] = None
    total: int
    skipped: int = 0
    jobs: list[JobListing]


class HealthResponse(BaseModel):
    status: str
    has_data: bool
    last_ingestion: Optional[str] = None
    job_count: int = 0


class IngestResponse(BaseModel):
    message: str
    already_running: bool = False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, summary="Health check")
def health_check():
    """Returns the operational status of the API and metadata about the last ingestion run."""
    if not os.path.exists(DATA_FILE):
        return HealthResponse(status="ok", has_data=False)

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return HealthResponse(
            status="ok",
            has_data=True,
            last_ingestion=data.get("ingested_at"),
            job_count=data.get("total", 0),
        )
    except Exception as exc:
        log.warning("Health check found a corrupt data file (%s): %s", DATA_FILE, exc)
        return HealthResponse(status="degraded", has_data=False)


@app.get("/jobs", response_model=JobsResponse, summary="Get ingested job listings")
def get_jobs():
    """Returns all job listings from the most recent ingestion run."""
    if not os.path.exists(DATA_FILE):
        return JobsResponse(total=0, jobs=[])

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return JobsResponse(**data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read data file: {exc}")


@app.post("/ingest", response_model=IngestResponse, summary="Trigger an ingestion run")
def trigger_ingest(background_tasks: BackgroundTasks):
    """
    Triggers a fresh ingestion run in the background.

    Returns immediately with a confirmation message. The ingestion run executes
    asynchronously so this endpoint does not block. Poll /health to check when
    new data is available.

    If an ingestion run is already in progress, this returns a 202 without
    starting a second run — the lock is intentional.
    """
    global _ingestion_running

    if _ingestion_running:
        return IngestResponse(
            message="An ingestion run is already in progress. Check /health for updates.",
            already_running=True,
        )

    def _run():
        global _ingestion_running
        with _ingestion_lock:
            _ingestion_running = True
            try:
                run_ingestion()
            except Exception:
                log.exception("Background ingestion run failed.")
            finally:
                _ingestion_running = False

    background_tasks.add_task(_run)
    return IngestResponse(message="Ingestion started. Poll /health or /jobs to see results.")


# ---------------------------------------------------------------------------
# Static frontend — mount AFTER all API routes so /health, /jobs, /ingest
# take precedence over the catch-all static file handler.
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory="static", html=True), name="static")

