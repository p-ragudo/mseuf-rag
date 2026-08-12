import os
from typing import Any, Dict, List
from qdrant_client import QdrantClient


class QDrantService:

  def __init__(self):
    cluster_endpoint = os.getenv("QDRANT_CLUSTER_ENDPOINT")
    api_key = os.getenv("QDRANT_API_KEY")

    if not cluster_endpoint:
      raise ValueError("QDRANT_CLUSTER_ENDPOINT is not set in environment.")

    self.client = QdrantClient(url=cluster_endpoint, api_key=api_key)

  def search_vectors(
      self, 
      collection_name: str, 
      query_vector: List[float], 
      limit: int = 5
  ) -> List[Dict[str, Any]]:
    """Searches top-k similar documents by vector embedding."""
    response = self.client.query_points(
        collection_name=collection_name, 
        query=query_vector, 
        limit=limit
    )
    return [
        {"id": hit.id, "score": hit.score, "payload": hit.payload}
        for hit in response.points
    ]