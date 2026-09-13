"""Visibility into the ingestion staging queue.

Queued work used to be invisible: nobody could see how deep the backlog was, and
a document that failed every retry left no trace at all. These endpoints expose
the queue depth, whether work is actually durable, and the dead-letter list, so a
stuck ingestion can be diagnosed and replayed instead of guessed at.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from module_1_document_processing.identity import bind_identity
from module_1_document_processing.pipeline.durable_queue import ingest_queue
from module_1_document_processing.workspace_access import (
    WorkspaceAccess,
    require_workspace_member,
    require_writer,
)

router = APIRouter(tags=["Ingestion Queue"], dependencies=[Depends(bind_identity)])


@router.get("/ingestion/queue/stats")
def queue_stats(access: WorkspaceAccess = Depends(require_workspace_member)):
    """Queue depth and backend. `durable` false means a restart would lose work."""
    stats = ingest_queue.stats()
    return {"status": "success", "durable": stats.get("backend") == "redis", "queue": stats}


@router.get("/ingestion/queue/metrics")
def queue_metrics(access: WorkspaceAccess = Depends(require_workspace_member)):
    """The same figures in Prometheus text format, for Grafana.

    Queue *age* matters as much as depth: a backlog that is not draining looks
    identical to a healthy one if you only measure depth. Counters are totals
    since the Redis keys were created, so they survive a restart of this service.

    Scraping this needs a public path on the gateway; today it is behind the same
    workspace check as the rest of the pipeline API. It carries counts only, never
    document content.
    """
    stats = ingest_queue.stats()
    totals = stats.get("totals") or {}
    lines = [
        "# HELP rolesync_ingest_queue_depth Jobs waiting to be processed.",
        "# TYPE rolesync_ingest_queue_depth gauge",
        f'rolesync_ingest_queue_depth{{state="pending"}} {stats.get("pending", 0)}',
        f'rolesync_ingest_queue_depth{{state="inflight"}} {stats.get("inflight", 0)}',
        f'rolesync_ingest_queue_depth{{state="retry"}} {stats.get("retry", 0)}',
        f'rolesync_ingest_queue_depth{{state="dead"}} {stats.get("dead", 0)}',
        "# HELP rolesync_ingest_queue_oldest_pending_seconds Age of the longest-waiting job.",
        "# TYPE rolesync_ingest_queue_oldest_pending_seconds gauge",
        f'rolesync_ingest_queue_oldest_pending_seconds {stats.get("oldest_pending_age_seconds", 0)}',
        "# HELP rolesync_ingest_queue_durable 1 when queued work survives a restart.",
        "# TYPE rolesync_ingest_queue_durable gauge",
        f'rolesync_ingest_queue_durable {1 if stats.get("backend") == "redis" else 0}',
        "# HELP rolesync_ingest_queue_accepting 1 while new ingestion is being accepted.",
        "# TYPE rolesync_ingest_queue_accepting gauge",
        f'rolesync_ingest_queue_accepting {1 if stats.get("accepting") else 0}',
        "# HELP rolesync_ingest_jobs_total Ingestion jobs by outcome.",
        "# TYPE rolesync_ingest_jobs_total counter",
    ]
    for outcome in ("enqueued", "processed", "retried", "dead"):
        lines.append(f'rolesync_ingest_jobs_total{{outcome="{outcome}"}} {totals.get(outcome, 0)}')

    return Response(content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.get("/ingestion/queue/dead-letters")
def dead_letters(
    limit: int = Query(default=50, ge=1, le=500),
    access: WorkspaceAccess = Depends(require_workspace_member),
):
    """Jobs that failed every attempt, with the error that stopped them."""
    # The queue is service-wide, so only this workspace's jobs are returned.
    mine = ingest_queue.dead_letters_for(access.workspace_id, limit=limit)
    return {
        "status": "success",
        "count": len(mine),
        "dead_letters": [
            {
                "job_id": e.get("job_id"),
                "kind": e.get("kind"),
                "attempts": e.get("attempts"),
                "last_error": e.get("last_error"),
                "enqueued_at": e.get("enqueued_at"),
                "doc_id": (e.get("payload") or {}).get("doc_id"),
                "filename": (e.get("payload") or {}).get("filename"),
                "source": (e.get("payload") or {}).get("source"),
            }
            for e in mine
        ],
    }


@router.post("/ingestion/queue/dead-letters/replay")
def replay_dead_letters(
    limit: int = Query(default=50, ge=1, le=500),
    access: WorkspaceAccess = Depends(require_workspace_member),
):
    """Put failed jobs back on the queue with a fresh attempt count."""
    require_writer(access)
    replayed = ingest_queue.replay_dead_letters(limit=limit, tenant_id=access.workspace_id)
    return {"status": "success", "replayed": replayed, "message": f"Requeued {replayed} failed job(s)."}
