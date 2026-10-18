import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.website import Website
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.services.vector_db.schema import VectorPoint, SparseVectorData
from tests.conftest import TEST_COLLECTION_NAME


@pytest.mark.asyncio
async def test_website_deletion_endpoint_purges_sql_and_qdrant(
    api_client: AsyncClient,
    db_session,
    live_or_mock_qdrant,
):
    # 1. Register and Login to get a valid JWT
    email = "admin_del_test@university.edu"
    pwd = "StrongPassword2026!"
    reg_res = await api_client.post(
        "/auth/register",
        json={"email": email, "password": pwd, "first_name": "Test", "last_name": "Admin"},
    )
    assert reg_res.status_code == 200

    login_res = await api_client.post("/auth/login", json={"email": email, "password": pwd})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create Org
    org_res = await api_client.post("/orgs/", headers=headers, json={"name": "Org Cascade Test"})
    assert org_res.status_code == 201
    org_id = org_res.json()["id"]

    # 3. Create Website
    site_url = "https://deletion-test.mseuf.edu.ph"
    site_res = await api_client.post(
        "/websites/",
        headers=headers,
        json={"org_id": org_id, "url": site_url, "interval_days": 1},
    )
    assert site_res.status_code == 201
    web_id = site_res.json()["id"]

    # 4. Insert child database records (Page and Chunk)
    page = ScrapedPage(
        org_id=org_id,
        web_id=web_id,
        url=f"{site_url}/info",
        status=PageProcessStatus.COMPLETED,
    )
    db_session.add(page)
    await db_session.flush()

    chunk = Chunk(page_id=page.id, content="Deletion test chunk", token_count=5, has_qgen=True)
    db_session.add(chunk)
    await db_session.commit()

    # 5. Insert points into Qdrant: one belonging to this website, one to an unrelated website
    pt_target = VectorPoint(
        id="d1111111-1111-1111-1111-111111111111",
        vector={
            "question_dense": [0.02] * 768,
            "chunk_sparse": SparseVectorData(indices=[1, 2], values=[0.1, 0.2]),
        },
        payload={"group_id": str(org_id), "web_id": web_id, "page_id": page.id},
    )
    pt_foreign = VectorPoint(
        id="d2222222-2222-2222-2222-222222222222",
        vector={
            "question_dense": [0.02] * 768,
            "chunk_sparse": SparseVectorData(indices=[1, 2], values=[0.1, 0.2]),
        },
        payload={"group_id": str(org_id), "web_id": 88888, "page_id": 9999},
    )
    await live_or_mock_qdrant.upsert_points(TEST_COLLECTION_NAME, [pt_target, pt_foreign])

    # 6. ACT: Execute actual DELETE endpoint over HTTP
    del_res = await api_client.delete(f"/websites/{web_id}", headers=headers)
    assert del_res.status_code == 200

    # 7. ASSERT: Database cascades deleted the website, page, and chunk
    assert await db_session.get(Website, web_id) is None
    page_query = await db_session.execute(select(ScrapedPage).where(ScrapedPage.web_id == web_id))
    assert page_query.scalar_one_or_none() is None
    chunk_query = await db_session.execute(select(Chunk).where(Chunk.page_id == page.id))
    assert chunk_query.scalar_one_or_none() is None

    # 8. ASSERT: Qdrant deleted the target point while leaving foreign points intact
    found_target = await live_or_mock_qdrant.search(
        collection_name=TEST_COLLECTION_NAME,
        query_vector=[0.02] * 768,
        filters={"group_id": str(org_id), "web_id": web_id},
    )
    assert len(found_target) == 0

    found_foreign = await live_or_mock_qdrant.search(
        collection_name=TEST_COLLECTION_NAME,
        query_vector=[0.02] * 768,
        filters={"group_id": str(org_id), "web_id": 88888},
    )
    assert len(found_foreign) == 1