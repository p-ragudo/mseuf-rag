import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.org_member import OrgMember
from app.routes.orgs import (
    remove_organization_member,
    transfer_organization_admin,
)


class FakeDatabase:
    def __init__(self, org, actor_membership, memberships):
        self.scalar_results = [org, actor_membership]
        self.memberships = memberships
        self.deleted = []
        self.committed = False

    async def scalar(self, _statement):
        return self.scalar_results.pop(0)

    async def get(self, model, key):
        assert model is OrgMember
        return self.memberships.get(key)

    async def delete(self, membership):
        self.deleted.append(membership)

    async def commit(self):
        self.committed = True


def _org(creator_id=7):
    return SimpleNamespace(id=1, creator_id=creator_id)


def _membership(user_id, role):
    return SimpleNamespace(user_id=user_id, org_id=1, roles=role)


def test_admin_handoff_promotes_target_and_demotes_current_admin():
    actor = _membership(8, "admin")
    target = _membership(9, "member")
    db = FakeDatabase(_org(), actor, {(8, 1): actor, (9, 1): target})

    result = asyncio.run(
        transfer_organization_admin(
            org_id=1,
            user_id=9,
            current_user=SimpleNamespace(id=8),
            db=db,
        )
    )

    assert target.roles == "admin"
    assert actor.roles == "member"
    assert result["admin_user_id"] == 9
    assert result["previous_admin_user_id"] == 8
    assert db.committed


def test_owner_can_grant_admin_without_losing_owner_admin_access():
    owner_membership = _membership(7, "admin")
    target = _membership(9, "member")
    db = FakeDatabase(
        _org(),
        owner_membership,
        {(7, 1): owner_membership, (9, 1): target},
    )

    result = asyncio.run(
        transfer_organization_admin(
            org_id=1,
            user_id=9,
            current_user=SimpleNamespace(id=7),
            db=db,
        )
    )

    assert target.roles == "admin"
    assert owner_membership.roles == "admin"
    assert result["previous_admin_user_id"] is None


def test_member_cannot_transfer_adminship():
    actor = _membership(8, "member")
    target = _membership(9, "member")
    db = FakeDatabase(_org(), actor, {(8, 1): actor, (9, 1): target})

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            transfer_organization_admin(
                org_id=1,
                user_id=9,
                current_user=SimpleNamespace(id=8),
                db=db,
            )
        )

    assert error.value.status_code == 403
    assert target.roles == "member"
    assert not db.committed


def test_admin_cannot_transfer_adminship_to_owner():
    actor = _membership(8, "admin")
    owner_membership = _membership(7, "admin")
    db = FakeDatabase(
        _org(),
        actor,
        {(8, 1): actor, (7, 1): owner_membership},
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            transfer_organization_admin(
                org_id=1,
                user_id=7,
                current_user=SimpleNamespace(id=8),
                db=db,
            )
        )

    assert error.value.status_code == 409
    assert actor.roles == "admin"
    assert not db.committed


def test_admin_can_remove_member():
    actor = _membership(8, "admin")
    target = _membership(9, "member")
    db = FakeDatabase(_org(), actor, {(8, 1): actor, (9, 1): target})

    result = asyncio.run(
        remove_organization_member(
            org_id=1,
            user_id=9,
            current_user=SimpleNamespace(id=8),
            db=db,
        )
    )

    assert result["user_id"] == 9
    assert db.deleted == [target]
    assert db.committed


def test_admin_cannot_remove_organization_owner():
    actor = _membership(8, "admin")
    owner_membership = _membership(7, "admin")
    db = FakeDatabase(
        _org(),
        actor,
        {(8, 1): actor, (7, 1): owner_membership},
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            remove_organization_member(
                org_id=1,
                user_id=7,
                current_user=SimpleNamespace(id=8),
                db=db,
            )
        )

    assert error.value.status_code == 409
    assert db.deleted == []
    assert not db.committed


def test_admin_cannot_remove_themselves():
    actor = _membership(8, "admin")
    db = FakeDatabase(_org(), actor, {(8, 1): actor})

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            remove_organization_member(
                org_id=1,
                user_id=8,
                current_user=SimpleNamespace(id=8),
                db=db,
            )
        )

    assert error.value.status_code == 400
    assert db.deleted == []
    assert not db.committed
