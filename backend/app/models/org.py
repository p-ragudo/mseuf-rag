from typing import TYPE_CHECKING

from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.org_member import OrgMember
    from app.models.website import Website


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[int] = mapped_column(primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    # Bumped whenever indexed content changes. Part of the semantic-cache scope,
    # so old cached answers become unreachable instantly (and expire via TTL).
    content_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    members: Mapped[list["OrgMember"]] = relationship(back_populates="org")
    websites: Mapped[list["Website"]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )