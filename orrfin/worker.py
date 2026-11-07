"""Background worker. Claims jobs with SKIP LOCKED and runs each in its own tenant transaction.

A claim is a lease: if the worker dies mid-job, the lease expires and another run picks it up.
Handlers must therefore be idempotent. The worker uses the same RLS-bound role as the API.
"""
import signal
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from orrfin.db import assert_safe_role, platform_tx
from orrfin.models import Job, Tenant

HEARTBEAT = Path("/tmp/orrfin-worker-heartbeat")
LEASE = timedelta(minutes=5)
POLL_SECONDS = 1.0
SCAN_EVERY_SECONDS = 300
MAX_ATTEMPTS = 6
BACKOFF_SCALE = float(__import__("os").getenv("ORRFIN_JOB_BACKOFF_SCALE", "1"))

_handlers: dict = {}
_running = True


def handler(kind: str):
    def register(func):
        _handlers[kind] = func
        return func

    return register


def enqueue(db: Session, tenant_id: UUID | None, kind: str, delay_seconds: int = 0, **payload) -> None:
    """Adds a job in the caller's transaction, so it commits or rolls back with the state change."""
    db.add(
        Job(
            tenant_id=tenant_id,
            kind=kind,
            payload={key: str(value) for key, value in payload.items()},
            run_after=datetime.now(timezone.utc) + timedelta(seconds=delay_seconds),
        )
    )


def _claim_one() -> tuple[UUID, str, UUID | None, dict, int] | None:
    now = datetime.now(timezone.utc)
    with platform_tx() as db:
        job = db.scalar(
            select(Job)
            .where(
                (Job.status == "queued") & (Job.run_after <= now)
                | (Job.status == "running") & (Job.locked_until < now)
            )
            .order_by(Job.run_after)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.status = "running"
        job.attempts += 1
        job.locked_until = now + LEASE
        return job.id, job.kind, job.tenant_id, dict(job.payload), job.attempts


def _finish(job_id: UUID, error: str | None, attempts: int) -> None:
    now = datetime.now(timezone.utc)
    with platform_tx() as db:
        job = db.get(Job, job_id)
        job.locked_until = None
        if error is None:
            job.status, job.finished_at, job.last_error = "done", now, None
        elif attempts >= MAX_ATTEMPTS:
            job.status, job.finished_at, job.last_error = "failed", now, error[-2000:]
        else:
            job.status, job.last_error = "queued", error[-2000:]
            job.run_after = now + timedelta(seconds=min(300, 2**attempts) * BACKOFF_SCALE)


def run_once() -> bool:
    """Runs one job if available. Returns whether it found work."""
    claim = _claim_one()
    if claim is None:
        return False
    job_id, kind, tenant_id, payload, attempts = claim
    func = _handlers.get(kind)
    try:
        if func is None:
            raise RuntimeError(f"No handler registered for job kind {kind}.")
        func(tenant_id, payload)
    except Exception:  # A failed job is recorded and retried; it must not stop the worker.
        print(f"job {job_id} ({kind}) failed on attempt {attempts}", file=sys.stderr)
        traceback.print_exc()
        _finish(job_id, traceback.format_exc(), attempts)
    else:
        _finish(job_id, None, attempts)
    return True


def _enqueue_scans() -> None:
    with platform_tx() as db:
        tenant_ids = db.scalars(select(Tenant.id)).all()
        for tenant_id in tenant_ids:
            if "scan" in _handlers:
                pending = db.scalar(
                    select(Job.id)
                    .where(Job.tenant_id == tenant_id, Job.kind == "scan", Job.status.in_(("queued", "running")))
                    .limit(1)
                )
                if pending is None:
                    enqueue(db, tenant_id, "scan")


def _stop(*_args) -> None:
    global _running
    _running = False


def _load_handlers() -> None:
    import orrfin.jobs  # noqa: F401  Registers handlers through @handler.


def main() -> None:
    assert_safe_role()
    _load_handlers()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    last_scan = 0.0
    while _running:
        HEARTBEAT.write_text(str(time.time()))
        if time.time() - last_scan > SCAN_EVERY_SECONDS:
            _enqueue_scans()
            last_scan = time.time()
        if not run_once():
            time.sleep(POLL_SECONDS)


def healthcheck() -> int:
    try:
        fresh = time.time() - float(HEARTBEAT.read_text()) < 360
        with platform_tx() as db:
            db.execute(text("SELECT 1"))
        return 0 if fresh else 1
    except (OSError, ValueError):
        return 1


if __name__ == "__main__":
    # Run through the importable module, not __main__, so handlers registered by orrfin.jobs
    # land in the same registry this loop reads.
    import orrfin.worker as worker_module

    sys.exit(worker_module.healthcheck()) if "--healthcheck" in sys.argv else worker_module.main()
