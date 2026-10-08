from functools import lru_cache
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession # type: ignore

from app.core.database import get_db
from app.models.org import Org
from app.services.query_pipeline.schema import (
    QueryBodyRequest,
    PipelineQueryRequest,
    PipelineQueryResponse,
)
from app.services.query_pipeline.query_pipeline import QueryPipeline

router = APIRouter(prefix="/query", tags=["Query Pipeline"])


@lru_cache(maxsize=1)
def get_query_pipeline() -> QueryPipeline:
    return QueryPipeline()


@router.post("/{org_id}/", response_model=PipelineQueryResponse)
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

    return await pipeline.execute(pipeline_req)