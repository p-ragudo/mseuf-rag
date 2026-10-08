import asyncio
from app.core.config import settings
from app.services.embeddings.factory import get_embedder


def _mask_secret(key: str | None) -> str:
    if not key:
        return "<NOT SET>"
    if len(key) <= 8:
        return "********"
    return f"{key[:4]}...{key[-4:]}"


print("=" * 50)
print("ACTIVE ENVIRONMENT CONFIGURATION")
print("=" * 50)
print(f"EMBEDDING_PROVIDER        = {settings.embedding_provider}")
print(f"EMBEDDING_MODEL           = {settings.embedding_model}")
print(f"EMBEDDING_API_KEY         = {_mask_secret(settings.embedding_api_key)}")
print(f"EMBEDDING_DIMENSION       = {settings.embedding_dimension}")
print(f"VECTOR_DIM                = {settings.vector_dim}")

COLLECTION_NAME = (
    settings.collection_name
    if settings.collection_name_use_prod
    else settings.collection_name_not_prod
)
print(f"COLLECTION_NAME           = {COLLECTION_NAME}")

SEMANTIC_CACHE_INDEX_NAME = (
    settings.semantic_cache_index_name
    if settings.semantic_cache_use_prod
    else settings.semantic_cache_not_prod
)
print(f"SEMANTIC_CACHE_INDEX_NAME = {SEMANTIC_CACHE_INDEX_NAME}")
print("=" * 50)

embedder = get_embedder()
print("Provider loaded:", type(embedder).__name__)
print("Dimension:", embedder.dimension)

res = asyncio.run(embedder.embed(["MSEUF BSCS curriculum"]))
print("Vector size:", len(res[0].values))

target_dim = settings.embedding_dimension or settings.vector_dim
assert len(res[0].values) == target_dim, f"Expected {target_dim}-dim output, got {len(res[0].values)}"
print(f"OK: {settings.embedding_model} embedding generated successfully!")