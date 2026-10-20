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
from app.models.org_branding import (
    OrgBranding,
    OrgChatFont,
    OrgChatHeader,
    OrgChatSettings,
)
from app.models.user import User
from app.routes.auth import get_current_user
from app.utils.org_roles import BRANDING_MANAGER_ROLES, require_org_role

router = APIRouter(prefix="/branding", tags=["branding"])

DEFAULT_COLOR = "#7A1F2B"
DEFAULT_ASSISTANT_NAME = "Chat Assistant"
DEFAULT_HEADER_TAGLINE = "Admissions Intelligence Hub"
DEFAULT_FONT_FAMILY = "system"
SUPPORTED_FONT_FAMILIES = {
    DEFAULT_FONT_FAMILY,
    "arial",
    "georgia",
    "verdana",
    "trebuchet",
    "courier",
}
MAX_ASSISTANT_NAME_LENGTH = 50
MAX_HEADER_TAGLINE_LENGTH = 80
MAX_MASCOT_BYTES = 512 * 1024  # 512 KB
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class BrandingOut(BaseModel):
    color: str
    mascot_url: str | None  # relative path, e.g. "/branding/1/mascot?v=1760400000"
    assistant_name: str
    header_tagline: str
    font_family: str


def to_out(
    org_id: int,
    color: str,
    mascot_updated_at: datetime | None,
    assistant_name: str = DEFAULT_ASSISTANT_NAME,
    header_tagline: str = DEFAULT_HEADER_TAGLINE,
    font_family: str = DEFAULT_FONT_FAMILY,
) -> BrandingOut:
    url = None
    if mascot_updated_at is not None:
        # the version changes on every upload, so browsers can cache the image forever
        url = f"/branding/{org_id}/mascot?v={int(mascot_updated_at.timestamp())}"
    return BrandingOut(
        color=color,
        mascot_url=url,
        assistant_name=assistant_name,
        header_tagline=header_tagline,
        font_family=font_family,
    )


async def require_branding_editor(db: AsyncSession, org_id: int, user: User) -> None:
    await require_org_role(
        db,
        org_id,
        user,
        BRANDING_MANAGER_ROLES,
        "Only organization administrators and designers can update chat branding.",
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

    exists = await db.scalar(select(Org.id).where(Org.id == org_id))
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
        )

    assistant_name = await db.scalar(
        select(OrgChatSettings.assistant_name).where(
            OrgChatSettings.org_id == org_id
        )
    )
    header_tagline = await db.scalar(
        select(OrgChatHeader.header_tagline).where(OrgChatHeader.org_id == org_id)
    )
    font_family = await db.scalar(
        select(OrgChatFont.font_family).where(OrgChatFont.org_id == org_id)
    )
    if row is None:
        return BrandingOut(
            color=DEFAULT_COLOR,
            mascot_url=None,
            assistant_name=assistant_name or DEFAULT_ASSISTANT_NAME,
            header_tagline=header_tagline or DEFAULT_HEADER_TAGLINE,
            font_family=font_family or DEFAULT_FONT_FAMILY,
        )

    return to_out(
        org_id,
        row.color,
        row.mascot_updated_at,
        assistant_name or DEFAULT_ASSISTANT_NAME,
        header_tagline or DEFAULT_HEADER_TAGLINE,
        font_family or DEFAULT_FONT_FAMILY,
    )


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
    assistant_name: str | None = Form(None),
    header_tagline: str | None = Form(None),
    font_family: str | None = Form(None),
    mascot: UploadFile | None = File(None),
    remove_mascot: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_branding_editor(db, org_id, current_user)

    if not HEX_COLOR.match(color):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Color must look like #7A1F2B.",
        )

    normalized_name = assistant_name.strip() if assistant_name is not None else None
    if normalized_name is not None and not normalized_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Assistant name cannot be empty.",
        )
    if normalized_name is not None and len(normalized_name) > MAX_ASSISTANT_NAME_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Assistant name must be {MAX_ASSISTANT_NAME_LENGTH} characters or fewer.",
        )

    normalized_tagline = (
        header_tagline.strip() if header_tagline is not None else None
    )
    if normalized_tagline is not None and not normalized_tagline:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Header tagline cannot be empty.",
        )
    if (
        normalized_tagline is not None
        and len(normalized_tagline) > MAX_HEADER_TAGLINE_LENGTH
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Header tagline must be {MAX_HEADER_TAGLINE_LENGTH} characters or fewer.",
        )

    normalized_font_family = (
        font_family.strip().lower() if font_family is not None else None
    )
    if (
        normalized_font_family is not None
        and normalized_font_family not in SUPPORTED_FONT_FAMILIES
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Choose a supported chat font.",
        )

    branding = await db.get(OrgBranding, org_id)
    if branding is None:
        branding = OrgBranding(org_id=org_id, color=color.upper())
        db.add(branding)
    branding.color = color.upper()

    chat_settings = await db.get(OrgChatSettings, org_id)
    if normalized_name is not None:
        if chat_settings is None:
            chat_settings = OrgChatSettings(
                org_id=org_id, assistant_name=normalized_name
            )
            db.add(chat_settings)
        else:
            chat_settings.assistant_name = normalized_name

    chat_header = await db.get(OrgChatHeader, org_id)
    if normalized_tagline is not None:
        if chat_header is None:
            chat_header = OrgChatHeader(
                org_id=org_id, header_tagline=normalized_tagline
            )
            db.add(chat_header)
        else:
            chat_header.header_tagline = normalized_tagline

    chat_font = await db.get(OrgChatFont, org_id)
    if normalized_font_family is not None:
        if chat_font is None:
            chat_font = OrgChatFont(
                org_id=org_id, font_family=normalized_font_family
            )
            db.add(chat_font)
        else:
            chat_font.font_family = normalized_font_family

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
    result = to_out(
        org_id,
        branding.color,
        branding.mascot_updated_at,
        normalized_name
        or (chat_settings.assistant_name if chat_settings else DEFAULT_ASSISTANT_NAME),
        normalized_tagline
        or (chat_header.header_tagline if chat_header else DEFAULT_HEADER_TAGLINE),
        normalized_font_family
        or (chat_font.font_family if chat_font else DEFAULT_FONT_FAMILY),
    )
    await db.commit()
    return result