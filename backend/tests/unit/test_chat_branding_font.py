import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.org_branding import OrgChatFont
from app.routes import branding as branding_route


class FakeDatabase:
    def __init__(self):
        self.records = []

    async def get(self, _model, _org_id):
        return None

    def add(self, record):
        self.records.append(record)

    async def commit(self):
        pass


def test_update_branding_saves_supported_font(monkeypatch):
    async def allow_org_access(_db, _org_id, _user):
        return None

    monkeypatch.setattr(branding_route, "require_org_access", allow_org_access)
    db = FakeDatabase()

    result = asyncio.run(
        branding_route.update_branding(
            org_id=7,
            color="#123456",
            assistant_name=None,
            header_tagline=None,
            font_family="Georgia",
            mascot=None,
            remove_mascot=False,
            db=db,
            current_user=SimpleNamespace(id=3),
        )
    )

    saved_font = next(record for record in db.records if isinstance(record, OrgChatFont))
    assert result.font_family == "georgia"
    assert saved_font.font_family == "georgia"


def test_update_branding_rejects_unsupported_font(monkeypatch):
    async def allow_org_access(_db, _org_id, _user):
        return None

    monkeypatch.setattr(branding_route, "require_org_access", allow_org_access)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            branding_route.update_branding(
                org_id=7,
                color="#123456",
                assistant_name=None,
                header_tagline=None,
                font_family="Comic Sans",
                mascot=None,
                remove_mascot=False,
                db=FakeDatabase(),
                current_user=SimpleNamespace(id=3),
            )
        )

    assert error.value.status_code == 422
