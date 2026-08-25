from typing import List, Optional
from pydantic import BaseModel, Field, computed_field


class EmbedderConfig(BaseModel):
    provider: str
    model_name: str
    api_key: str
    task_type: Optional[str] = None
    output_dimensionality: Optional[int] = None


class EmbeddingResult(BaseModel):
    values: List[float]

    @computed_field
    @property
    def dimension(self) -> int:
        return len(self.values)