import os
from typing import Any, Dict, List
from qdrant_client import QdrantClient
from dotenv import load_dotenv

load_dotenv()

class QDrantService:

    def __init__(self):
        # Checks if DEVELOPMENT is set to 'true', '1', or 'yes' (case-insensitive)
        is_dev = os.getenv("DEVELOPMENT", "false").lower() in ("true", "1", "yes")

        if is_dev:
            cluster_endpoint = os.getenv("TEST_QDRANT_CLUSTER_ENDPOINT")
            api_key = os.getenv("TEST_QDRANT_API_KEY")
        else:
            cluster_endpoint = os.getenv("QDRANT_CLUSTER_ENDPOINT")
            api_key = os.getenv("QDRANT_API_KEY")

        if not cluster_endpoint:
            env_name = "TEST_QDRANT_CLUSTER_ENDPOINT" if is_dev else "QDRANT_CLUSTER_ENDPOINT"
            raise ValueError(f"{env_name} is not set in environment.")

        self.client = QdrantClient(url=cluster_endpoint, api_key=api_key)

    def search_vectors(
        self, 
        collection_name: str, 
        query_vector: List[float], 
        limit: int = 5,
        with_payload: bool = True
    ) -> List[Dict[str, Any]]:
        """Searches top-k similar documents by vector embedding."""
        response = self.client.query_points(
            collection_name=collection_name, 
            query=query_vector, 
            limit=limit,
            with_payload=with_payload
        )
        return [
            {"id": hit.id, "score": hit.score, "payload": hit.payload}
            for hit in response.points
        ]