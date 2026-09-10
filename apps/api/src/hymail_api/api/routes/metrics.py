from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from hymail_api.api.deps import SessionDep
from hymail_api.schemas.metrics import (
    FolderMetricsRead,
    MetricsRead,
    OutboxMetricsRead,
)
from hymail_api.services import accounts
from hymail_api.services.metrics import collect_metrics

router = APIRouter()


@router.get("", response_model=MetricsRead)
async def read_metrics(
    session: SessionDep,
    window_hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> MetricsRead:
    """Sync and outbox health over a rolling window."""
    account = await accounts.get_current_account(session)
    if account is None:
        raise HTTPException(status_code=404, detail="account not configured")

    snapshot = await collect_metrics(
        session,
        account.id,
        window_hours=window_hours,
    )

    return MetricsRead(
        window_hours=snapshot.window_hours,
        generated_at=snapshot.generated_at,
        runs=snapshot.runs,
        failures=snapshot.failures,
        failure_rate=snapshot.failure_rate,
        retries=snapshot.retries,
        fetched=snapshot.fetched,
        avg_duration_ms=snapshot.avg_duration_ms,
        p95_duration_ms=snapshot.p95_duration_ms,
        folders=[
            FolderMetricsRead(
                folder_id=item.folder_id,
                folder_name=item.folder_name,
                runs=item.runs,
                failures=item.failures,
                retries=item.retries,
                fetched=item.fetched,
                avg_duration_ms=item.avg_duration_ms,
                p95_duration_ms=item.p95_duration_ms,
                last_sync_at=item.last_sync_at,
                last_error=item.last_error,
            )
            for item in snapshot.folders
        ],
        outbox=OutboxMetricsRead(
            pending=snapshot.outbox.pending,
            inflight=snapshot.outbox.inflight,
            success=snapshot.outbox.success,
            failed=snapshot.outbox.failed,
            abandoned=snapshot.outbox.abandoned,
            outstanding=snapshot.outbox.outstanding,
        ),
    )
