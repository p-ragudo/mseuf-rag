from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.core.database import get_db
from app.models.org import Org
from app.models.org_member import OrgMember
from app.models.user import User
from app.schemas.tenant import (
    OrgCreate,
    OrgMemberCreate,
    OrgMemberSummary,
    OrgMembersResponse,
    OrgResponse,
    PublicOrgResponse,
)
from app.routes.auth import get_current_user

router = APIRouter(prefix="/orgs", tags=["Organizations"])


async def get_org_admin_status(
    db: AsyncSession, org: Org, current_user: User
) -> tuple[bool, bool]:
    """Returns (is_member, can_manage_members) for an organization."""
    membership = await db.scalar(
        select(OrgMember).where(
            OrgMember.org_id == org.id,
            OrgMember.user_id == current_user.id,
        )
    )
    is_member = org.creator_id == current_user.id or membership is not None
    can_manage = org.creator_id == current_user.id or (
        membership is not None and membership.roles == "admin"
    )
    return is_member, can_manage


@router.get("/public/{org_id}", response_model=PublicOrgResponse)
async def get_public_org_info(
    org_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Public initialization endpoint for frontend chat widgets.
    Allows unauthenticated visitors to verify organization existence
    and load institutional branding (e.g. organization name).
    """
    org = await db.get(Org, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization with ID {org_id} does not exist.",
        )
    return org


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


@router.get("/{org_id}/members", response_model=OrgMembersResponse)
async def list_organization_members(
    org_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await db.get(Org, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found."
        )

    is_member, can_manage = await get_org_admin_status(db, org, current_user)
    if not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization.",
        )

    rows = await db.execute(
        select(User, OrgMember.roles)
        .join(OrgMember, OrgMember.user_id == User.id)
        .where(OrgMember.org_id == org_id)
        .order_by(User.first_name, User.last_name, User.email)
    )
    members = [
        OrgMemberSummary(
            user_id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            role=role,
        )
        for user, role in rows.all()
    ]
    return OrgMembersResponse(members=members, can_manage=can_manage)


@router.post(
    "/{org_id}/members",
    response_model=OrgMemberSummary,
    status_code=status.HTTP_201_CREATED,
)
async def add_organization_member(
    org_id: int,
    payload: OrgMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await db.get(Org, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found."
        )

    _, can_manage = await get_org_admin_status(db, org, current_user)
    if not can_manage:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization administrators can add members.",
        )

    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Email is required.",
        )

    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No registered account was found for that email.",
        )

    existing_membership = await db.get(OrgMember, (user.id, org_id))
    if existing_membership is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This user is already a member of the organization.",
        )

    membership = OrgMember(user_id=user.id, org_id=org_id, roles="member")
    db.add(membership)
    await db.commit()

    return OrgMemberSummary(
        user_id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=membership.roles,
    )