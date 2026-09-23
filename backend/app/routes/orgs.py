from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.org import Org
from app.models.org_member import OrgMember
from app.models.user import User
from app.schemas.tenant import OrgCreate, OrgResponse
from app.routes.auth import get_current_user  # Adjust import to match your auth user dependency

router = APIRouter(prefix="/orgs", tags=["Organizations"])


@router.post("/", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrgCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Creates a new organization and assigns the creator as an admin."""
    # Check if org name already exists
    existing = await db.execute(select(Org).where(Org.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization with this name already exists",
        )

    new_org = Org(
        name=payload.name,
        creator_id=current_user.id,
    )
    db.add(new_org)
    await db.flush()  # Populates new_org.id

    # Create membership record for the creator
    membership = OrgMember(
        user_id=current_user.id,
        org_id=new_org.id,
        roles="admin",
    )
    db.add(membership)
    await db.commit()
    await db.refresh(new_org)

    return new_org


@router.get("/", response_model=list[OrgResponse])
async def list_user_organizations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lists all organizations the current user belongs to."""
    stmt = (
        select(Org)
        .join(OrgMember, Org.id == OrgMember.org_id)
        .where(OrgMember.user_id == current_user.id)
    )
    res = await db.execute(stmt)
    return res.scalars().all()