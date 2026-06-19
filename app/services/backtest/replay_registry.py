"""
Backtest Replay — Job Registry (in-memory)
============================================
Quản lý trạng thái các job backtest replay.
Phase 1: in-memory, không lưu DB.
"""

import threading
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from app.services.backtest.replay_models import (
    ReplayJobStatus,
    ReplaySummary,
    TradeRow,
)


_lock = threading.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}


def create_job(request_params: dict) -> str:
    job_id = f"bt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    with _lock:
        _jobs[job_id] = {
            "status": "QUEUED",
            "progress_pct": 0,
            "message": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "finished_at": None,
            "error": None,
            "request_params": request_params,
            "summary": None,
            "rows": [],
        }

    return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        return _jobs.get(job_id)


def get_job_status(job_id: str) -> Optional[ReplayJobStatus]:
    job = get_job(job_id)
    if not job:
        return None

    return ReplayJobStatus(
        job_id=job_id,
        status=job["status"],
        progress_pct=job["progress_pct"],
        message=job["message"],
        created_at=job["created_at"],
        started_at=job["started_at"],
        finished_at=job["finished_at"],
        error=job["error"],
    )


def update_job(job_id: str, **kwargs):
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.update(kwargs)


def set_job_running(job_id: str, message: str = ""):
    update_job(
        job_id,
        status="RUNNING",
        started_at=datetime.now(timezone.utc).isoformat(),
        message=message,
    )


def set_job_progress(job_id: str, pct: int, message: str = ""):
    update_job(job_id, progress_pct=pct, message=message)


def set_job_done(job_id: str, summary: ReplaySummary, rows: list):
    update_job(
        job_id,
        status="DONE",
        progress_pct=100,
        message="Complete",
        finished_at=datetime.now(timezone.utc).isoformat(),
        summary=summary,
        rows=rows,
    )


def set_job_failed(job_id: str, error: str):
    update_job(
        job_id,
        status="FAILED",
        finished_at=datetime.now(timezone.utc).isoformat(),
        error=error,
    )


def get_job_summary(job_id: str) -> Optional[ReplaySummary]:
    job = get_job(job_id)
    if not job:
        return None
    return job.get("summary")


def get_job_rows(job_id: str) -> list:
    job = get_job(job_id)
    if not job:
        return []
    return job.get("rows", [])