from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.org import Org
from app.models.user import User

class OrgMember(Base):
    __tablename__ = "org_members"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), primary_key=True)
    roles: Mapped[str] = mapped_column(String(50))  # e.g. "admin", "member"

    user: Mapped["User"] = relationship(back_populates="memberships")
    org: Mapped["Org"] = relationship(back_populates="members")