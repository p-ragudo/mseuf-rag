# app/api/v1/ingest.py
from fastapi import APIRouter, BackgroundTasks, HTTPException, Header
from pydantic import BaseModel
from app.services.sql_db.postgres_provider import PostgresDatabaseRepository
from app.services.ingest_pipeline.scrape import scrape_site
from app.services.ingest_pipeline.chunk import process_and_chunk_pages
from app.core.config import settings

router = APIRouter(prefix="/ingest", tags=["Ingestion"])


class IngestTriggerRequest(BaseModel):
    tenant_id: str
    start_url: str
    max_depth: int = 2


async def run_pipeline_task(tenant_id: str, start_url: str, max_depth: int):
    # Direct internal container networking inside the VM uses local port 5432
    repo = PostgresDatabaseRepository(dsn=settings.database_url)
    await repo.connect()
    try:
        print(f"[{tenant_id}] Remote execution started for {start_url}...")
        await scrape_site(
            start_url=start_url,
            tenant_id=tenant_id,
            repo=repo,
            max_depth=max_depth,
        )
        chunks = await process_and_chunk_pages(tenant_id=tenant_id, repo=repo)
        print(f"[{tenant_id}] Ingestion complete. Chunks created: {len(chunks)}")
    finally:
        await repo.close()


@router.post("/start")
async def trigger_ingestion(
    payload: IngestTriggerRequest,
    background_tasks: BackgroundTasks,
    x_admin_secret: str = Header(...),  # Simple security check
):
    if x_admin_secret != settings.admin_secret_key:
        raise HTTPException(status_code=403, detail="Unauthorized")

    background_tasks.add_task(
        run_pipeline_task,
        tenant_id=payload.tenant_id,
        start_url=payload.start_url,
        max_depth=payload.max_depth,
    )

    return {
        "status": "QUEUED",
        "message": f"Ingestion triggered for tenant '{payload.tenant_id}'. Running in background.",
    }