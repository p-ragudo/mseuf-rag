from fastapi import APIRouter, Depends
from app.services.query_pipeline.schema import PipelineQueryRequest, PipelineQueryResponse
from app.services.query_pipeline.query_pipeline import QueryPipelineService, get_query_pipeline

router = APIRouter(prefix="/api", tags=["query"])

@router.post("/query", response_model=PipelineQueryResponse)
async def handle_query(
    request: PipelineQueryRequest,
    pipeline: QueryPipelineService = Depends(get_query_pipeline)
):
    return await pipeline.execute(request)