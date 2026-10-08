import asyncio
import inspect
from urllib.parse import urlparse
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine, DATABSE_URL
from app.services.embeddings.factory import get_embedder
from app.services.vector_db.factory import get_vector_db


def _mask_secret(key: str | None) -> str:
    if not key:
        return "<NOT SET>"
    if len(key) <= 8:
        return "********"
    return f"{key[:4]}...{key[-4:]}"


def _is_truthy(val) -> bool:
    """Safely evaluates booleans, strings ('true'/'false'), or integers."""
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return bool(val)


def _safe_db_summary(raw_url: str | None) -> str:
    if not raw_url:
        return "<NOT SET>"
    try:
        parsed = urlparse(raw_url)
        db_name = parsed.path.lstrip("/") or "<no db>"
        host_port = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
        return f"database='{db_name}' on host='{host_port}'"
    except Exception:
        return "<unparseable url>"


# 1. Print Configured Settings
use_prod_collection = _is_truthy(getattr(settings, "collection_name_use_prod", False))
use_prod_cache = _is_truthy(getattr(settings, "semantic_cache_index_name_use_prod", False))
use_prod_db = _is_truthy(getattr(settings, "database_url_use_prod", False))

active_collection = (
    settings.collection_name
    if use_prod_collection
    else getattr(settings, "collection_name_not_prod", "<NOT SET>")
)

active_semantic_cache = (
    settings.semantic_cache_index_name
    if use_prod_cache
    else getattr(settings, "semantic_cache_index_name_not_prod", "<NOT SET>")
)

print("=" * 60)
print("ACTIVE ENVIRONMENT CONFIGURATION")
print("=" * 60)
print(f"EMBEDDING_PROVIDER        = {getattr(settings, 'embedding_provider', '<NOT SET>')}")
print(f"EMBEDDING_MODEL           = {getattr(settings, 'embedding_model', '<NOT SET>')}")
print(f"EMBEDDING_API_KEY         = {_mask_secret(getattr(settings, 'embedding_api_key', None))}")
print(f"EMBEDDING_DIMENSION       = {getattr(settings, 'embedding_dimension', '<NOT SET>')}")
print(f"VECTOR_DIM                = {getattr(settings, 'vector_dim', '<NOT SET>')}")
print("-" * 60)
print(f"ACTIVE COLLECTION_NAME    = {active_collection} (PROD: {use_prod_collection})")
print(f"ACTIVE SEMANTIC_CACHE     = {active_semantic_cache} (PROD: {use_prod_cache})")
print(f"RESOLVED APP ENGINE URL   = {_safe_db_summary(DATABSE_URL)} (PROD: {use_prod_db})")
print("=" * 60)


# 2. Async Verifications (Live Database + Embedder + Vector DB)
async def run_verifications():
    # Database
    print("\n[VERIFICATION: DATABASE CONNECTION]")
    try:
        async with engine.connect() as conn:
            live_db = await conn.scalar(text("SELECT current_database()"))
            live_user = await conn.scalar(text("SELECT current_user"))
            print(f"  Status:            CONNECTED")
            print(f"  Live Target DB:    {live_db}")
            print(f"  Authenticated As:  {live_user}")
            print(f"  Bound Engine Host: {engine.url.host}:{engine.url.port or 'default'}")
    except Exception as e:
        print(f"  Status:            FAILED ({e})")

    # Embedder
    print("\n[VERIFICATION: EMBEDDER]")
    try:
        embedder = get_embedder()
        print(f"  Provider Loaded:   {type(embedder).__name__}")
        print(f"  Reported Dim:      {embedder.dimension}")

        res = await embedder.embed(["MSEUF BSCS curriculum"])
        vector_size = len(res[0].values)
        print(f"  Vector Size:       {vector_size}")

        target_dim = getattr(settings, "embedding_dimension", None) or getattr(settings, "vector_dim", None)
        if target_dim:
            assert vector_size == target_dim, f"Expected {target_dim}-dim output, got {vector_size}"
            print(f"  Status:            SUCCESS ({getattr(settings, 'embedding_model', 'model')} matched target {target_dim}d)")
        else:
            print("  Status:            SUCCESS (Vector returned, no target_dim configured to assert)")
    except Exception as e:
        print(f"  Status:            FAILED ({e})")

    # Vector DB (Live Client & Collection Verification)
    print("\n[VERIFICATION: VECTOR DATABASE]")
    try:
        vdb = get_vector_db()
        print(f"  Provider Loaded:   {type(vdb).__name__}")

        # Extract underlying client (e.g. self.client or self.async_client inside QdrantVectorDB)
        client = getattr(vdb, "client", getattr(vdb, "async_client", None))

        if client is not None:
            # Query actual collection info over the wire
            get_coll_method = getattr(client, "get_collection")
            if inspect.iscoroutinefunction(get_coll_method):
                coll_info = await get_coll_method(collection_name=active_collection)
            else:
                coll_info = get_coll_method(collection_name=active_collection)

            status = getattr(coll_info, "status", "UNKNOWN")
            points_count = getattr(coll_info, "points_count", getattr(coll_info, "vectors_count", "N/A"))

            print(f"  Live Target Coll:  {active_collection}")
            print(f"  Collection Status: {status}")
            print(f"  Live Point Count:  {points_count}")
            print(f"  Status:            SUCCESS (Connected to live vector index)")
        else:
            # Fallback if QdrantVectorDB wraps collection check on itself
            check_method = getattr(vdb, "collection_exists", None) or getattr(vdb, "get_collection", None)
            if check_method:
                exists = await check_method(active_collection) if inspect.iscoroutinefunction(check_method) else check_method(active_collection)
                print(f"  Live Target Coll:  {active_collection}")
                print(f"  Collection Exists: {exists}")
                print(f"  Status:            SUCCESS")
            else:
                print(f"  Status:            WARNING (Client initialized, but no direct collection check method found)")
    except Exception as e:
        print(f"  Status:            FAILED ({e})")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_verifications())