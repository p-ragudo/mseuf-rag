# app/routes/branding.py
import re
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.org import Org
from app.models.org_branding import OrgBranding
from app.models.org_member import OrgMember
from app.models.user import User
from app.routes.auth import get_current_user

router = APIRouter(prefix="/branding", tags=["branding"])

DEFAULT_COLOR = "#7A1F2B"
MAX_MASCOT_BYTES = 512 * 1024  # 512 KB
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class BrandingOut(BaseModel):
    color: str
    mascot_url: str | None  # relative path, e.g. "/branding/1/mascot?v=1760400000"


def to_out(org_id: int, color: str, mascot_updated_at: datetime | None) -> BrandingOut:
    url = None
    if mascot_updated_at is not None:
        # the version changes on every upload, so browsers can cache the image forever
        url = f"/branding/{org_id}/mascot?v={int(mascot_updated_at.timestamp())}"
    return BrandingOut(color=color, mascot_url=url)


async def require_org_access(db: AsyncSession, org_id: int, user: User) -> None:
    org = await db.scalar(select(Org).where(Org.id == org_id))
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
        )

    member = await db.scalar(
        select(OrgMember).where(
            OrgMember.org_id == org_id, OrgMember.user_id == user.id
        )
    )
    if org.creator_id != user.id and not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization",
        )


# ---- public: the chat page has no logged-in user ----


@router.get("/{org_id}", response_model=BrandingOut)
async def get_branding(org_id: int, db: AsyncSession = Depends(get_db)):
    # Select only the small columns so the image bytes are never loaded here
    row = (
        await db.execute(
            select(OrgBranding.color, OrgBranding.mascot_updated_at).where(
                OrgBranding.org_id == org_id
            )
        )
    ).first()

    if row is None:
        # Nothing saved yet: serve the defaults so the chat just works
        exists = await db.scalar(select(Org.id).where(Org.id == org_id))
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
            )
        return BrandingOut(color=DEFAULT_COLOR, mascot_url=None)

    return to_out(org_id, row.color, row.mascot_updated_at)


@router.get("/{org_id}/mascot")
async def get_mascot(org_id: int, db: AsyncSession = Depends(get_db)):
    data = await db.scalar(
        select(OrgBranding.mascot_png).where(OrgBranding.org_id == org_id)
    )
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No mascot")

    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# ---- authenticated: used by the Mascot page ----


@router.put("/{org_id}", response_model=BrandingOut)
async def update_branding(
    org_id: int,
    color: str = Form(...),
    mascot: UploadFile | None = File(None),
    remove_mascot: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_access(db, org_id, current_user)

    if not HEX_COLOR.match(color):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Color must look like #7A1F2B.",
        )

    branding = await db.get(OrgBranding, org_id)
    if branding is None:
        branding = OrgBranding(org_id=org_id, color=color.upper())
        db.add(branding)
    branding.color = color.upper()

    if mascot is not None and mascot.filename:
        data = await mascot.read(MAX_MASCOT_BYTES + 1)
        if len(data) > MAX_MASCOT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="The mascot image must be 512 KB or smaller.",
            )
        # Check the file's real signature, not just the name or content type
        if not data.startswith(PNG_MAGIC):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="The mascot must be a PNG image.",
            )
        branding.mascot_png = data
        branding.mascot_updated_at = datetime.utcnow()
    elif remove_mascot:
        branding.mascot_png = None
        branding.mascot_updated_at = None

    # Build the response before commit(): commit expires the object's attributes
    result = to_out(org_id, branding.color, branding.mascot_updated_at)
    await db.commit()
    return result