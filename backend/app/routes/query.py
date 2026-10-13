import logging
import time
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.response import Response as ResponseLog
from app.models.org import Org
from app.services.query_pipeline.schema import (
    QueryBodyRequest,
    PipelineQueryRequest,
    PipelineQueryResponse,
)
from app.services.query_pipeline.query_pipeline import QueryPipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["Query Pipeline"])


@lru_cache(maxsize=1)
def get_query_pipeline() -> QueryPipeline:
    return QueryPipeline()


def _collect_titles(result: PipelineQueryResponse) -> tuple[list[str], list[str]]:
    chunk_titles: dict[str, None] = {}  # dict keeps order and removes duplicates
    questions: dict[str, None] = {}

    for ctx in result.contexts or []:
        if ctx.title:
            chunk_titles[ctx.title] = None
        for mq in ctx.matched_questions or []:
            if mq.question:
                questions[mq.question] = None

    return list(chunk_titles), list(questions)


@router.post("/{org_id}", response_model=PipelineQueryResponse)
async def execute_query(
    org_id: int,
    body: QueryBodyRequest,
    db: AsyncSession = Depends(get_db),
    pipeline: QueryPipeline = Depends(get_query_pipeline),
):
    org = await db.get(Org, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization {org_id} not found.",
        )

    pipeline_req = PipelineQueryRequest(
        org_id=org_id,
        query=body.query,
        session_id=body.session_id,
    )

    started = time.perf_counter()
    result = await pipeline.execute(pipeline_req)  # raises -> nothing below runs
    latency_ms = int((time.perf_counter() - started) * 1000)

    try:
        titles, questions = _collect_titles(result)
        db.add(
            ResponseLog(
                org_id=org_id,
                latency_ms=latency_ms,
                accessed_chunks=titles,
                accessed_generated_questions=questions,
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Failed to record response for org %s", org_id)

    return result