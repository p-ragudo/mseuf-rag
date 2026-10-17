# app/models/session_message.py
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SessionMessage(Base):
    """One turn (user question or assistant answer) of a chat session.

    Rows expire: they are ignored once older than SESSION_TTL and deleted
    shortly after (see session_context.py).
    """

    __tablename__ = "session_messages"
    __table_args__ = (
        # "latest messages of this session in this org"
        Index("ix_session_messages_lookup", "org_id", "session_id", "id"),
        # lets the expiry cleanup find old rows without scanning the table
        Index("ix_session_messages_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )