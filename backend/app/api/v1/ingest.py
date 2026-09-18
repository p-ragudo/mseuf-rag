from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Header
from pydantic import BaseModel
from app.core.config import settings
from app.utils.telegram_bot import run_pipeline_with_notifications

router = APIRouter(prefix="/ingest", tags=["Ingestion"])

class IngestRequest(BaseModel):
    tenant_id: str
    start_url: str
    max_depth: int = 1
    notify_chat_id: Optional[int | str] = None


@router.post("/start")
async def trigger_ingestion(
    payload: IngestRequest,
    background_tasks: BackgroundTasks,
    x_admin_secret: str = Header(...),
):
    if x_admin_secret != settings.telegram_bot_fastapi_key:
        raise HTTPException(status_code=403, detail="Unauthorized")

    background_tasks.add_task(
        run_pipeline_with_notifications,
        tenant_id=payload.tenant_id,
        start_url=payload.start_url,
        max_depth=payload.max_depth,
        chat_id=payload.notify_chat_id,
    )

    return {
        "status": "QUEUED",
        "tenant_id": payload.tenant_id,
        "message": f"Pipeline task triggered for '{payload.tenant_id}'.",
    }