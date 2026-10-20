from collections.abc import Collection

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import Org
from app.models.org_member import OrgMember
from app.models.user import User

CONTENT_MANAGER_ROLES = ("admin", "ingester")
BRANDING_MANAGER_ROLES = ("admin", "designer")


async def get_org_role(db: AsyncSession, org_id: int, user: User) -> str:
    org = await db.get(Org, org_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )

    if org.creator_id == user.id:
        return "admin"

    membership = await db.scalar(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization.",
        )
    return membership.roles


async def require_org_role(
    db: AsyncSession,
    org_id: int,
    user: User,
    allowed_roles: Collection[str],
    detail: str,
) -> str:
    role = await get_org_role(db, org_id, user)
    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )
    return role
