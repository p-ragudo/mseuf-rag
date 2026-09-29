from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.org import Org
from app.models.org_member import OrgMember
from app.models.user import User
from app.schemas.tenant import OrgCreate, OrgResponse, AddMemberResponse
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

# Adding members in an organization and other endpoints can be implemented similarly, ensuring proper role checks and validations are in place.

@router.post("/{org_id}/add-member", response_model=AddMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_member_to_organization(
    org_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Adds a member to the organization if the current user is an admin."""
    # Check if the organization exists
    org = await db.get(Org, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    # Check if the current user is an admin of the organization
    membership = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id, OrgMember.user_id == current_user.id
        )
    )
    membership_record = membership.scalar_one_or_none()
    if not membership_record or "admin" not in membership_record.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to add members to this organization",
        )

    # Check if the user to be added exists
    user_to_add = await db.get(User, user_id)
    if not user_to_add:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User to add not found",
        )

    # Check if the user is already a member of the organization
    existing_member = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id, OrgMember.user_id == user_id
        )
    )
    if existing_member.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this organization",
        )

    # Add the new member with default role (e.g., "member")
    new_membership = OrgMember(
        user_id=user_id,
        org_id=org_id,
        roles="member",  # Default role for new members
    )
    db.add(new_membership)
    await db.commit()
    await db.refresh(new_membership)

    return AddMemberResponse(
        message=f"User {user_to_add.email} added to organization {org.name}."
    )