from typing import Dict, List, Optional
import math
from datetime import datetime, timezone

from .base import BaseSemanticCache
from .schemas import CacheEntry, CacheMetadata


def _cosine_distance(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = math.sqrt(sum(a * a for a in v1))
    norm_v2 = math.sqrt(sum(b * b for b in v2))
    if norm_v1 == 0 or norm_v2 == 0:
        return 1.0
    cosine_sim = dot / (norm_v1 * norm_v2)
    # Cosine distance = 1 - cosine similarity
    return max(0.0, min(2.0, 1.0 - cosine_sim))


class InMemorySemanticCache(BaseSemanticCache):
    def __init__(
        self,
        distance_threshold: float = 0.25,
        threshold: Optional[float] = None,
        **kwargs,
    ) -> None:
        self.distance_threshold = (
            threshold if threshold is not None else distance_threshold
        )
        # Key: org_id (scope) -> List of stored entries
        self._store: Dict[str, List[dict]] = {}

    async def get(
        self,
        vector: List[float],
        org_id: int | str,
    ) -> Optional[CacheEntry]:
        scope = str(org_id)
        entries = self._store.get(scope, [])
        if not entries:
            return None

        best_entry = None
        min_dist = float("inf")

        for item in entries:
            dist = _cosine_distance(vector, item["vector"])
            if dist <= self.distance_threshold and dist < min_dist:
                min_dist = dist
                best_entry = item

        if best_entry:
            return CacheEntry(
                query=best_entry["query"],
                response=best_entry["response"],
                metadata=best_entry["metadata"],
                distance=min_dist,
            )
        return None

    async def set(
        self,
        query: str,
        vector: List[float],
        response: str,
        org_id: int | str,
        metadata: Optional[CacheMetadata] = None,
    ) -> None:
        scope = str(org_id)
        if scope not in self._store:
            self._store[scope] = []

        self._store[scope].append(
            {
                "query": query,
                "vector": vector,
                "response": response,
                "metadata": metadata or CacheMetadata(),
                "created_at": datetime.now(timezone.utc),
            }
        )

    async def clear(self) -> None:
        self._store.clear()