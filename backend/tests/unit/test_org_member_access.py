import asyncio
from types import SimpleNamespace

from app.routes.orgs import get_org_admin_status


class FakeSession:
    def __init__(self, membership):
        self.membership = membership

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


def test_nonmember_cannot_manage_members():
    org = SimpleNamespace(id=1, creator_id=7)
    user = SimpleNamespace(id=8)

    assert asyncio.run(get_org_admin_status(FakeSession(None), org, user)) == (
        False,
        False,
    )
