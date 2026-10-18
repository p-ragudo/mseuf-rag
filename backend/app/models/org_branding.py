# app/models/org_branding.py
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OrgBranding(Base):
    __tablename__ = "org_branding"

    # one row per organization
    org_id: Mapped[int] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True
    )
    color: Mapped[str] = mapped_column(String(7), default="#7A1F2B", nullable=False)

    # deferred: the image bytes are only loaded when explicitly asked for,
    # so reading the color never drags a PNG out of the database
    mascot_png: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, deferred=True
    )
    # NULL means "no mascot". Also used as the cache-busting version in the URL.
    mascot_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class OrgChatSettings(Base):
    __tablename__ = "org_chat_settings"

    org_id: Mapped[int] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True
    )
    assistant_name: Mapped[str] = mapped_column(
        String(50), default="Chat Assistant", nullable=False
    )


class OrgChatHeader(Base):
    __tablename__ = "org_chat_headers"

    org_id: Mapped[int] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True
    )
    header_tagline: Mapped[str] = mapped_column(
        String(80), default="Admissions Intelligence Hub", nullable=False
    )