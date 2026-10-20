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
    OrgMemberUpdate,
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
    current_role = (
        "admin"
        if org.creator_id == current_user.id
        else await db.scalar(
            select(OrgMember.roles).where(
                OrgMember.org_id == org_id,
                OrgMember.user_id == current_user.id,
            )
        )
    )
    if current_role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization.",
        )

    return OrgMembersResponse(
        members=members,
        can_manage=can_manage,
        owner_id=org.creator_id,
        current_user_id=current_user.id,
        current_role=current_role,
    )


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


@router.patch(
    "/{org_id}/members/{user_id}",
    response_model=OrgMemberSummary,
)
async def update_organization_member_role(
    org_id: int,
    user_id: int,
    payload: OrgMemberUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await db.scalar(
        select(Org).where(Org.id == org_id).with_for_update()
    )
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found."
        )

    _, can_manage = await get_org_admin_status(db, org, current_user)
    if not can_manage:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization administrators can change member roles.",
        )
    if user_id == org.creator_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The organization owner must remain an administrator.",
        )
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role.",
        )

    membership = await db.get(OrgMember, (user_id, org_id))
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The selected user is not a member of this organization.",
        )

    membership.roles = payload.role
    await db.commit()
    user = await db.get(User, user_id)
    return OrgMemberSummary(
        user_id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=membership.roles,
    )


@router.post("/{org_id}/members/{user_id}/transfer-admin")
async def transfer_organization_admin(
    org_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await db.scalar(
        select(Org).where(Org.id == org_id).with_for_update()
    )
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found."
        )

    _, can_manage = await get_org_admin_status(db, org, current_user)
    if not can_manage:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization administrators can transfer adminship.",
        )
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose another member to receive adminship.",
        )
    if user_id == org.creator_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The organization owner already has permanent admin access.",
        )

    target_membership = await db.get(OrgMember, (user_id, org_id))
    if target_membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The selected user is not a member of this organization.",
        )

    target_membership.roles = "admin"
    current_membership = await db.get(OrgMember, (current_user.id, org_id))
    if current_user.id != org.creator_id and current_membership is not None:
        current_membership.roles = "member"

    await db.commit()
    return {
        "message": "Adminship transferred.",
        "admin_user_id": user_id,
        "previous_admin_user_id": (
            current_user.id if current_user.id != org.creator_id else None
        ),
    }


@router.delete("/{org_id}/members/{user_id}")
async def remove_organization_member(
    org_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await db.scalar(
        select(Org).where(Org.id == org_id).with_for_update()
    )
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found."
        )

    _, can_manage = await get_org_admin_status(db, org, current_user)
    if not can_manage:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization administrators can remove members.",
        )
    if user_id == org.creator_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The organization owner cannot be removed from the organization.",
        )
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove yourself. Ask another administrator to remove you.",
        )

    membership = await db.get(OrgMember, (user_id, org_id))
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The selected user is not a member of this organization.",
        )

    await db.delete(membership)
    await db.commit()
    return {"message": "Member removed from the organization.", "user_id": user_id}