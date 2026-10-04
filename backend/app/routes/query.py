from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.user import User
from app.models.org_member import OrgMember
from app.routes.auth import get_current_user
from app.services.query_pipeline.schema import PipelineQueryRequest, PipelineQueryResponse
from app.services.query_pipeline.query_pipeline import QueryPipeline

router = APIRouter(prefix="/query", tags=["Query Pipeline"])


def get_query_pipeline() -> QueryPipeline:
    return QueryPipeline()


@router.post("/", response_model=PipelineQueryResponse)
async def execute_query(
    payload: PipelineQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    pipeline: QueryPipeline = Depends(get_query_pipeline),
):
    # Enforce organization access permission
    stmt = select(OrgMember).where(
        OrgMember.org_id == payload.org_id,
        OrgMember.user_id == current_user.id,
    )
    res = await db.execute(stmt)
    if not res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to run queries against this organization.",
        )

    return await pipeline.execute(payload)