# app/services/query_pipeline/session_context.py
"""Conversation memory for the query pipeline, with automatic expiry.

- load_history / save_turns: read and write the turns of a session
- purge_expired: deletes messages older than SESSION_TTL
- build_retrieval_query: makes a short follow-up searchable on its own
- build_llm_query: gives the answer model the conversation so far
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session_message import SessionMessage
from app.services.query_pipeline.schema import ChatTurn

logger = logging.getLogger(__name__)

SESSION_TTL = timedelta(hours=24)  # messages expire this long after they were sent
PURGE_EVERY = timedelta(minutes=10)  # how often the cleanup may run (per process)

MAX_HISTORY_MESSAGES = 6  # last 3 question/answer pairs
SELF_CONTAINED_WORDS = 8  # questions at least this long are searched as written
MAX_ANSWER_CHARS = 600  # old answers are trimmed before going into the prompt
MAX_STORED_CHARS = 8000  # hard cap on what is stored per message

_last_purge = datetime.min  # naive UTC, like the created_at column


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _key(session_id: str) -> str:
    return session_id[:64]  # matches the column length


async def load_history(
    db: AsyncSession, org_id: int, session_id: str | None
) -> list[ChatTurn]:
    """Latest unexpired turns of this session, oldest first."""
    if not session_id:
        return []

    result = await db.execute(
        select(SessionMessage.role, SessionMessage.content)
        .where(
            SessionMessage.org_id == org_id,
            SessionMessage.session_id == _key(session_id),
            SessionMessage.created_at >= _now() - SESSION_TTL,  # expired = ignored
        )
        .order_by(SessionMessage.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
    )
    rows = result.all()
    return [ChatTurn(role=role, content=content) for role, content in reversed(rows)]


def save_turns(
    db: AsyncSession,
    org_id: int,
    session_id: str | None,
    question: str,
    answer: str,
) -> None:
    """Queues the question and answer; the caller's commit saves them."""
    if not session_id:
        return
    for role, text in (("user", question), ("assistant", answer)):
        db.add(
            SessionMessage(
                org_id=org_id,
                session_id=_key(session_id),
                role=role,
                content=text[:MAX_STORED_CHARS],
            )
        )


async def purge_expired(db: AsyncSession) -> None:
    """Deletes expired messages. Runs at most once per PURGE_EVERY in each
    process, and never raises, so a cleanup problem can't break a request."""
    global _last_purge

    now = _now()
    if now - _last_purge < PURGE_EVERY:
        return
    _last_purge = now

    try:
        await db.execute(
            delete(SessionMessage).where(SessionMessage.created_at < now - SESSION_TTL)
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Failed to purge expired session messages")


def build_retrieval_query(query: str, history: list[ChatTurn]) -> str:
    """Short follow-ups ("what about the fees?") say nothing on their own, so
    they are searched together with the previous question."""
    if not history or len(query.split()) >= SELF_CONTAINED_WORDS:
        return query

    previous_questions = [t.content for t in history if t.role == "user"]
    if not previous_questions:
        return query
    return f"{previous_questions[-1]} {query}"


def build_llm_query(query: str, history: list[ChatTurn]) -> str:
    """The question as the answer model sees it, with the conversation so far."""
    if not history:
        return query

    lines = []
    for turn in history:
        text = turn.content.strip()
        if turn.role == "assistant" and len(text) > MAX_ANSWER_CHARS:
            text = text[:MAX_ANSWER_CHARS].rstrip() + "..."
        speaker = "User" if turn.role == "user" else "Assistant"
        lines.append(f"{speaker}: {text}")

    conversation = "\n".join(lines)
    return (
        "Earlier in this conversation:\n"
        f"{conversation}\n\n"
        "Answer the current question using the provided documents. Use the earlier "
        "conversation only to understand what the question refers to.\n\n"
        f"Current question: {query}"
    )