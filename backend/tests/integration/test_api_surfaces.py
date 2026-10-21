import io
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock

from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.services.llm_qa.schema import QAResponse
from app.services.vector_db.schema import VectorPoint, SparseVectorData
from app.routes.query import get_query_pipeline
from app.core.config import settings
from tests.conftest import TEST_COLLECTION_NAME, Deterministic768Embedder


@pytest.mark.asyncio
async def test_full_api_surface_branding_query_and_analytics(
    api_client: AsyncClient,
    db_session,
    live_or_mock_qdrant,
    monkeypatch,
):
    # 1. Register & Authenticate User
    email = "faculty@university.edu"
    pwd = "FacultyPassword2026!"
    await api_client.post(
        "/auth/register",
        json={"email": email, "password": pwd, "first_name": "Faculty", "last_name": "Lead"},
    )
    login = await api_client.post("/auth/login", json={"email": email, "password": pwd})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Check /auth/me
    me_res = await api_client.get("/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == email

    # 3. Create Org
    org_res = await api_client.post("/orgs/", headers=headers, json={"name": "Engineering College"})
    org_id = org_res.json()["id"]

    # 4. Test Branding: Upload PNG mascot and hex color
    valid_png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    files = {"mascot": ("mascot.png", io.BytesIO(valid_png_bytes), "image/png")}
    data = {"color": "#800000", "remove_mascot": "false"}

    put_branding = await api_client.put(f"/branding/{org_id}", headers=headers, data=data, files=files)
    assert put_branding.status_code == 200
    assert put_branding.json()["color"] == "#800000"
    assert put_branding.json()["mascot_url"] is not None

    # Public Branding GET
    pub_branding = await api_client.get(f"/branding/{org_id}")
    assert pub_branding.status_code == 200
    assert pub_branding.json()["color"] == "#800000"

    # 5. Insert backing database records (ScrapedPage & Chunk) for Small-to-Big Context Expansion
    page = ScrapedPage(
        org_id=org_id,
        web_id=1,
        url="https://university.edu/bscs",
        status=PageProcessStatus.COMPLETED,
    )
    db_session.add(page)
    await db_session.flush()

    chunk = Chunk(
        page_id=page.id,
        chunk_index=0,
        section_id="sec_bscs",
        heading_path="Academics > BSCS",
        content="The curriculum includes Systems Programming, AI, and Software Architecture.",
        token_count=12,
        has_qgen=True,
    )
    db_session.add(chunk)
    await db_session.commit()

    # 6. Seed Qdrant with matching question vector and valid chunk_id
    embedder = Deterministic768Embedder()
    vec = (await embedder.embed(["What is the curriculum for Computer Science?"]))[0].values

    test_point = VectorPoint(
        id="e1111111-1111-1111-1111-111111111111",
        vector={"question_dense": vec, "chunk_sparse": SparseVectorData(indices=[5, 9], values=[0.8, 0.4])},
        payload={
            "group_id": str(org_id),
            "web_id": 1,
            "page_id": page.id,
            "chunk_id": chunk.id,
            "parent_chunk_id": f"chunk_parent_{chunk.id}",
            "question_text": "What is the curriculum for Computer Science?",
            "chunk_text": chunk.content,
            "source_url": page.url,
            "heading_path": chunk.heading_path,
            "campus": "main",
            "doc_period": 2026,
            "academic_level": "undergraduate",
        },
    )
    await live_or_mock_qdrant.upsert_points(TEST_COLLECTION_NAME, [test_point])

    # 7. Sync the route's cached pipeline instance and flush previous test cache entries
    pipeline = get_query_pipeline()
    pipeline.embedder = embedder
    
    # Flush semantic cache so we test the full retrieval-to-LLM cold path
    await pipeline.semantic_cache.clear()

    mock_qa = AsyncMock()
    mock_qa.generate_answer.return_value = QAResponse(
        answer="The BSCS curriculum covers Systems Programming and AI.",
        sources=[page.url],
    )
    pipeline.qa_synthesizer = mock_qa

    # Disable reranker score gating for this test
    monkeypatch.setattr(settings, "reranker_score_threshold", None)

    # 8. Execute FIRST POST /query/{org_id} (Cold Query: Must hit LLM synthesis)
    query_res = await api_client.post(
        f"/query/{org_id}",
        json={"query": "What is the curriculum for Computer Science?", "session_id": "session_test_42"},
    )
    assert query_res.status_code == 200
    query_data = query_res.json()
    assert query_data["source"] == "llm"
    assert "Systems Programming" in query_data["answer"]
    response_id = query_data["response_id"]
    assert response_id is not None

    # 8b. Execute SECOND POST /query/{org_id} (Warm Query: Must hit semantic cache)
    cached_query_res = await api_client.post(
        f"/query/{org_id}",
        json={"query": "What is the curriculum for Computer Science?", "session_id": "session_test_42"},
    )
    assert cached_query_res.status_code == 200
    cached_data = cached_query_res.json()
    assert cached_data["source"] == "cache"
    assert cached_data["is_cached"] is True

    # 9. Record User Feedback: POST /query/{response_id}/feedback
    feedback_res = await api_client.post(
        f"/query/{response_id}/feedback",
        json={"satisfied": True},
    )
    assert feedback_res.status_code == 204

    # 10. Test Stats Endpoint Access Control & Validation
    missing_org_stats = await api_client.post(
        "/stats",
        headers=headers,
        json={"org_id": 999999, "range": "last_7_days"},
    )
    assert missing_org_stats.status_code == 404

    unauth_stats = await api_client.post(
        "/stats",
        json={"org_id": org_id, "range": "last_7_days"},
    )
    assert unauth_stats.status_code == 401