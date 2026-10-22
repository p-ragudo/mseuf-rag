"""Read-only guards. The evaluation must never modify production data.

What can write in this codebase, and how each path is closed:
  * Postgres  -> install_postgres_write_guard(): a SQLAlchemy hook that raises before any INSERT/UPDATE/DELETE/DDL
                 statement is sent to the database.
  * Qdrant    -> ReadOnlyVectorDB: a proxy that only exposes search / search_sparse / close. upsert, delete,
                 create_collection, create_payload_index and the raw client are unreachable.
  * Redis     -> build_safe_pipeline() swaps the semantic-cache factory for a no-op BEFORE QueryPipeline() is
                 constructed. (RedisSemanticCache.__init__ uses overwrite=True, i.e. it would re-create the cache
                 index just by being instantiated, so we never instantiate it.)
  * App state -> we never call the HTTP routes, so no session_messages / stats / response rows are written.
The only things this suite writes are local files under backend/evaluation/data/.
Gemini API calls are the only non-read side effect (they cost quota).
"""
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import event, text

_WRITE_SQL = re.compile(
    r"^\s*(insert|update|delete|drop|alter|create|truncate|grant|revoke|merge|copy|vacuum|reindex|comment)\b",
    re.IGNORECASE,
)
_CTE_WRITE = re.compile(r"^\s*with\b.*?\b(insert\s+into|update\s+\w+\s+set|delete\s+from)\b", re.IGNORECASE | re.DOTALL)
_PG_GUARD_INSTALLED = False


class ProductionWriteBlocked(RuntimeError):
    """Raised when evaluation code tries to write to a production system."""


def install_postgres_write_guard() -> None:
    global _PG_GUARD_INSTALLED
    if _PG_GUARD_INSTALLED:
        return
    from app.core.database import engine

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _block_writes(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if _WRITE_SQL.match(statement) or _CTE_WRITE.match(statement):
            raise ProductionWriteBlocked(
                f"Evaluation tried to run a write statement and was blocked: {statement[:120]!r}"
            )

    _PG_GUARD_INSTALLED = True


async def selftest_postgres_guard() -> None:
    """Proves the guard works. The blocked statement never reaches the database."""
    from app.core.database import async_session

    async with async_session() as session:
        try:
            await session.execute(text("UPDATE chunks SET id = id WHERE 1 = 0"))
        except ProductionWriteBlocked:
            return
        except Exception as e:  # a DB error means the guard did NOT stop it before execution
            raise RuntimeError(f"Postgres write guard self-test failed (statement reached the DB): {e}") from e
    raise RuntimeError("Postgres write guard self-test failed: write statement was not blocked.")


class ReadOnlyVectorDB:
    """Proxy around the real vector DB that only allows reads."""

    _ALLOWED = frozenset({"search", "search_sparse", "close"})

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name: str) -> Any:
        if name in ReadOnlyVectorDB._ALLOWED:
            return getattr(object.__getattribute__(self, "_inner"), name)
        raise ProductionWriteBlocked(
            f"Evaluation tried to access vector_db.{name!r}; only {sorted(ReadOnlyVectorDB._ALLOWED)} are allowed."
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise ProductionWriteBlocked("ReadOnlyVectorDB is immutable.")


def selftest_vector_guard(vdb: "ReadOnlyVectorDB") -> None:
    for forbidden in ("upsert_points", "delete_points", "create_collection_if_not_exists", "client"):
        try:
            getattr(vdb, forbidden)
        except ProductionWriteBlocked:
            continue
        raise RuntimeError(f"Vector DB guard self-test failed: {forbidden!r} was reachable.")


def _make_noop_cache():
    from typing import List as _L, Optional as _O
    from app.services.semantic_cache.base import BaseSemanticCache
    from app.services.semantic_cache.schemas import CacheEntry, CacheMetadata

    class NoOpSemanticCache(BaseSemanticCache):
        """Never reads, never writes. Every query is a cache MISS, so live retrieval + generation are tested."""

        async def get(self, vector: _L[float], org_id: "int | str") -> _O[CacheEntry]:
            return None

        async def set(self, query: str, vector: _L[float], response: str, org_id: "int | str",
                      metadata: _O[CacheMetadata] = None) -> None:
            return None

        async def clear(self) -> None:
            return None

    return NoOpSemanticCache()


def build_safe_pipeline():
    """Constructs the production QueryPipeline with all write paths closed. Call after install_postgres_write_guard()."""
    import app.services.query_pipeline.query_pipeline as qp

    if not hasattr(qp, "get_semantic_cache"):
        raise RuntimeError(
            "query_pipeline.py no longer exposes get_semantic_cache; refusing to build QueryPipeline() because "
            "that could instantiate the real Redis cache. Update evaluation/safety.py."
        )
    original = qp.get_semantic_cache
    qp.get_semantic_cache = _make_noop_cache  # type: ignore[assignment]
    try:
        pipeline = qp.QueryPipeline()
    finally:
        qp.get_semantic_cache = original  # type: ignore[assignment]

    if type(pipeline.semantic_cache).__name__ != "NoOpSemanticCache":
        raise RuntimeError("Semantic cache was not replaced by the no-op; aborting.")

    pipeline.vector_db = ReadOnlyVectorDB(pipeline.vector_db)
    selftest_vector_guard(pipeline.vector_db)
    return pipeline


def describe_environment() -> Dict[str, Any]:
    from sqlalchemy.engine import make_url
    from app.core.config import settings

    url = make_url(settings.resolved_database_url)
    return {
        "qdrant_target": "TEST cluster" if settings.use_test_qdrant_db else "PRODUCTION cluster",
        "qdrant_is_prod": not bool(settings.use_test_qdrant_db),
        "qdrant_collection": settings.resolved_collection_name,
        "postgres": f"{url.host}:{url.port or ''}/{url.database}",
        "embedding_model": settings.embedding_model,
        "qa_model": getattr(settings, "llm_qa_model", None),
        "semantic_cache_provider": getattr(settings, "semantic_cache_provider", None),
    }


def require_safe_environment(allow_prod_read: bool) -> Dict[str, Any]:
    env = describe_environment()
    print("=" * 78)
    print("EVALUATION ENVIRONMENT (read-only mode)")
    for k, v in env.items():
        print(f"  {k:<26}: {v}")
    print("  write guards              : Postgres hook + read-only Qdrant proxy + no-op semantic cache")
    print("=" * 78)
    if env["qdrant_is_prod"] and not allow_prod_read:
        raise SystemExit(
            "Refusing to run: settings point at the PRODUCTION Qdrant cluster.\n"
            "Reads are safe (writes are blocked by the guards above) but eval traffic adds load and uses real data.\n"
            "Either set USE_TEST_QDRANT_DB=true against a staging copy (recommended), or re-run with --allow-prod-read."
        )
    install_postgres_write_guard()
    return env
