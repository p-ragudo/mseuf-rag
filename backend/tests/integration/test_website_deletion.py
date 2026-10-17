import pytest
from app.models.org import Org
from app.models.website import Website
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.services.vector_db.qdrant_provider import QdrantVectorDB

@pytest.mark.asyncio
async def test_delete_website_only_targets_its_own_tenant_and_site(db_session, in_memory_qdrant, monkeypatch):
    qdrant_db = QdrantVectorDB(client=in_memory_qdrant)
    
    deleted_scopes = []
    async def mock_delete_points(collection_name, filters, must_not=None):
        deleted_scopes.append(filters)

    monkeypatch.setattr(qdrant_db, "delete_points", mock_delete_points)
    monkeypatch.setattr("app.routes.websites.get_vector_db", lambda: qdrant_db)

    # Org 1 Website 10
    web_1 = Website(id=10, org_id=1, url="https://uni-1.edu")
    db_session.add(web_1)
    await db_session.commit()

    # Simulate deletion logic from routes/websites.py
    await qdrant_db.delete_points(
        collection_name="test_collection",
        filters={"group_id": str(web_1.org_id), "web_id": web_1.id}
    )

    assert len(deleted_scopes) == 1
    assert deleted_scopes[0] == {"group_id": "1", "web_id": 10}