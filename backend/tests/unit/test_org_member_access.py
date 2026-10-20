import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routes.orgs import get_org_admin_status
from app.utils.org_roles import (
    BRANDING_MANAGER_ROLES,
    CONTENT_MANAGER_ROLES,
    get_org_role,
    require_org_role,
)


class FakeSession:
    def __init__(self, membership):
        self.membership = membership

    async def scalar(self, _statement):
        return self.membership


class FakeRoleSession:
    def __init__(self, org, membership):
        self.org = org
        self.membership = membership

    async def get(self, _model, _org_id):
        return self.org

    async def scalar(self, _statement):
        return self.membership


def test_organization_creator_can_manage_members_without_membership_row():
    org = SimpleNamespace(id=1, creator_id=7)
    user = SimpleNamespace(id=7)

    assert asyncio.run(get_org_admin_status(FakeSession(None), org, user)) == (
        True,
        True,
    )


def test_admin_member_can_manage_members():
    org = SimpleNamespace(id=1, creator_id=7)
    user = SimpleNamespace(id=8)
    membership = SimpleNamespace(roles="admin")

    assert asyncio.run(
        get_org_admin_status(FakeSession(membership), org, user)
    ) == (True, True)


def test_regular_member_cannot_manage_members():
    org = SimpleNamespace(id=1, creator_id=7)
    user = SimpleNamespace(id=8)
    membership = SimpleNamespace(roles="member")

    assert asyncio.run(
        get_org_admin_status(FakeSession(membership), org, user)
    ) == (True, False)


@pytest.mark.parametrize("role", ["designer", "ingester"])
def test_specialty_roles_cannot_manage_members(role):
    org = SimpleNamespace(id=1, creator_id=7)
    user = SimpleNamespace(id=8)
    membership = SimpleNamespace(roles=role)

    assert asyncio.run(
        get_org_admin_status(FakeSession(membership), org, user)
    ) == (True, False)


def test_nonmember_cannot_manage_members():
    org = SimpleNamespace(id=1, creator_id=7)
    user = SimpleNamespace(id=8)

    assert asyncio.run(get_org_admin_status(FakeSession(None), org, user)) == (
        False,
        False,
    )


@pytest.mark.parametrize(
    ("role", "allowed_roles"),
    [
        ("admin", BRANDING_MANAGER_ROLES),
        ("designer", BRANDING_MANAGER_ROLES),
        ("admin", CONTENT_MANAGER_ROLES),
        ("ingester", CONTENT_MANAGER_ROLES),
    ],
)
def test_role_requirements_accept_roles_with_the_matching_permission(
    role, allowed_roles
):
    db = FakeRoleSession(
        SimpleNamespace(id=1, creator_id=7),
        SimpleNamespace(roles=role),
    )

    assert asyncio.run(
        require_org_role(
            db,
            1,
            SimpleNamespace(id=8),
            allowed_roles,
            "forbidden",
        )
    ) == role


@pytest.mark.parametrize(
    ("role", "allowed_roles"),
    [
        ("designer", CONTENT_MANAGER_ROLES),
        ("ingester", BRANDING_MANAGER_ROLES),
        ("member", BRANDING_MANAGER_ROLES),
        ("member", CONTENT_MANAGER_ROLES),
    ],
)
def test_role_requirements_reject_roles_without_the_permission(role, allowed_roles):
    db = FakeRoleSession(
        SimpleNamespace(id=1, creator_id=7),
        SimpleNamespace(roles=role),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            require_org_role(
                db,
                1,
                SimpleNamespace(id=8),
                allowed_roles,
                "forbidden",
            )
        )

    assert error.value.status_code == 403


def test_organization_owner_always_has_admin_role():
    db = FakeRoleSession(SimpleNamespace(id=1, creator_id=7), None)

    assert asyncio.run(get_org_role(db, 1, SimpleNamespace(id=7))) == "admin"
