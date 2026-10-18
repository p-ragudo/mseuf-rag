from app.schemas.tenant import ChatTurn
from app.services.query_pipeline.intent_classifier import QueryIntent
from app.services.query_pipeline.query_pipeline import QueryPipeline
from app.services.query_pipeline.schema import PipelineQueryRequest
from app.services.query_pipeline.session_context import SESSION_TTL


def test_rewritten_follow_up_keeps_history_in_qa_prompt_and_skips_cache():
    history = [
        ChatTurn(role="user", content="What are the requirements for nursing?"),
        ChatTurn(role="assistant", content="Here are the nursing requirements."),
    ]
    request = PipelineQueryRequest(
        org_id=1,
        query="What about the fees?",
        history=history,
    )
    intent = QueryIntent(
        is_ambiguous=False,
        is_follow_up=True,
        standalone_query="What are the fees for the nursing program?",
    )

    search_query, llm_query, use_cache = QueryPipeline._resolve_follow_up(
        request, intent
    )

    assert search_query == "What are the fees for the nursing program?"
    assert "Here are the nursing requirements." in llm_query
    assert "Current question: What are the fees for the nursing program?" in llm_query
    assert use_cache is False


def test_session_history_expiration_remains_24_hours():
    assert SESSION_TTL.total_seconds() == 24 * 60 * 60
