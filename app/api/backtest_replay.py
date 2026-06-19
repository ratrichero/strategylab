"""
Backtest Replay API
====================
5 endpoints cho Signal Replay Backtest Phase 1.
"""

import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services.backtest.replay_models import (
    ReplayRunRequest,
    ReplayJobStatus,
    ReplaySummary,
    TradeRow,
    TradeRowsPage,
)
from app.services.backtest.replay_registry import (
    create_job,
    get_job_status,
    get_job_summary,
    get_job_rows,
    get_job,
)
from app.services.backtest.replay_service import run_replay_job


router = APIRouter(prefix="/api/backtest/replay", tags=["backtest"])


# ── POST /run ────────────────────────────────────────────────

@router.post("/run")
def start_replay_job(req: ReplayRunRequest):
    params = {
        "date_from": req.date_from.isoformat(),
        "date_to": req.date_to.isoformat(),
        "timeframes": req.timeframes,
        "symbols": req.symbols,
        "strategies": req.strategies,
        "limit": req.limit,
    }

    job_id = create_job(params)

    thread = threading.Thread(
        target=run_replay_job,
        args=(job_id, params),
        daemon=True,
        name=f"backtest::{job_id}",
    )
    thread.start()

    return {"job_id": job_id, "status": "QUEUED"}


# ── GET /jobs/{job_id} ───────────────────────────────────────

@router.get("/jobs/{job_id}")
def get_job_status_api(job_id: str):
    status = get_job_status(job_id)
    if not status:
        raise HTTPException(404, f"Job {job_id} not found")
    return status.dict()


# ── GET /jobs/{job_id}/summary ───────────────────────────────

@router.get("/jobs/{job_id}/summary")
def get_job_summary_api(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")

    if job["status"] != "DONE":
        raise HTTPException(400, f"Job {job_id} not done yet (status={job['status']})")

    summary = get_job_summary(job_id)
    if not summary:
        raise HTTPException(404, f"Summary not found for job {job_id}")

    return summary.dict()


# ── GET /jobs/{job_id}/rows ──────────────────────────────────

@router.get("/jobs/{job_id}/rows")
def get_job_rows_api(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")

    if job["status"] != "DONE":
        raise HTTPException(400, f"Job {job_id} not done yet (status={job['status']})")

    all_rows = get_job_rows(job_id)
    total = len(all_rows)

    start = (page - 1) * page_size
    end = start + page_size
    page_items = all_rows[start:end]

    items = []
    for r in page_items:
        if isinstance(r, dict):
            items.append(r)
        elif hasattr(r, "dict"):
            items.append(r.dict())
        else:
            items.append(r)

    return {
        "job_id": job_id,
        "page": page,
        "page_size": page_size,
        "total_rows": total,
        "items": items,
    }


# ── GET /jobs/{job_id}/rows/{signal_id} ──────────────────────

@router.get("/jobs/{job_id}/rows/{signal_id}")
def get_job_row_detail_api(job_id: str, signal_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")

    if job["status"] != "DONE":
        raise HTTPException(400, f"Job {job_id} not done yet (status={job['status']})")

    all_rows = get_job_rows(job_id)

    for r in all_rows:
        row_data = r if isinstance(r, dict) else (r.dict() if hasattr(r, "dict") else r)
        if row_data.get("signal_id") == signal_id:
            return row_data

    raise HTTPException(404, f"Signal {signal_id} not found in job {job_id}")