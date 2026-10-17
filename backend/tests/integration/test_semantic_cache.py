import pytest
from unittest.mock import patch
from app.core.config import settings
from app.services.semantic_cache.factory import get_semantic_cache
from app.services.semantic_cache.schemas import CacheMetadata
from app.services.query_pipeline.query_pipeline import _cache_scope

@pytest.fixture
def test_cache():
    with patch.object(settings, "semantic_cache_provider", "memory"), \
         patch.object(settings, "semantic_cache_threshold", 0.20):
        return get_semantic_cache()

@pytest.mark.asyncio
async def test_semantic_cache_hit_and_distance_threshold(test_cache):
    query_vec = [1.0, 0.0, 0.0]
    org_scope = "tenant_1_v0"

    await test_cache.set(
        query="What is the admission deadline?",
        vector=query_vec,
        response="The deadline is July 31, 2026.",
        org_id=org_scope,
        metadata=CacheMetadata(extra={"sources": ["https://university.edu/dates"]}),
    )

    # 1. Exact query match -> HIT
    exact_hit = await test_cache.get(vector=[1.0, 0.0, 0.0], org_id=org_scope)
    assert exact_hit is not None
    assert exact_hit.response == "The deadline is July 31, 2026."

    # 2. Similar query within threshold -> HIT
    similar_hit = await test_cache.get(vector=[0.98, 0.05, 0.0], org_id=org_scope)
    assert similar_hit is not None
    assert similar_hit.response == "The deadline is July 31, 2026."

    # 3. Dissimilar query exceeding threshold -> MISS
    miss = await test_cache.get(vector=[0.0, 1.0, 0.0], org_id=org_scope)
    assert miss is None

@pytest.mark.asyncio
async def test_cache_multi_tenant_and_campus_scope_isolation(test_cache):
    vector = [0.5, 0.5, 0.5]

    scope_main = _cache_scope(org_id=1, campus=None, version=0)          # "1_v0"
    scope_satellite = _cache_scope(org_id=1, campus="candelaria", version=0) # "1_v0_candelaria"
    scope_tenant_2 = _cache_scope(org_id=2, campus=None, version=0)       # "2_v0"

    await test_cache.set("Tuition fee", vector, "Main Campus: 40k PHP", org_id=scope_main)
    await test_cache.set("Tuition fee", vector, "Candelaria Branch: 25k PHP", org_id=scope_satellite)

    # Check Main scope
    res_main = await test_cache.get(vector, org_id=scope_main)
    assert res_main.response == "Main Campus: 40k PHP"

    # Check Sub-campus scope
    res_satellite = await test_cache.get(vector, org_id=scope_satellite)
    assert res_satellite.response == "Candelaria Branch: 25k PHP"

    # Cross-tenant check: Tenant 2 query must MISS
    res_tenant_2 = await test_cache.get(vector, org_id=scope_tenant_2)
    assert res_tenant_2 is None

@pytest.mark.asyncio
async def test_cache_invalidation_via_content_version_bump(test_cache):
    vector = [0.2, 0.4, 0.8]

    v0_scope = _cache_scope(org_id=10, campus=None, version=0)
    await test_cache.set("Library hours", vector, "Open 8 AM - 5 PM", org_id=v0_scope)

    # Pre-invalidation hit
    assert (await test_cache.get(vector, org_id=v0_scope)) is not None

    # Simulating knowledgebase update (content_version incremented to 1)
    v1_scope = _cache_scope(org_id=10, campus=None, version=1)

    # Previous cache scope becomes unreachable
    res_post_invalidation = await test_cache.get(vector, org_id=v1_scope)
    assert res_post_invalidation is None