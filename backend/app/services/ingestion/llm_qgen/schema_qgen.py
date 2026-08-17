from typing import List, Dict, Any
from pydantic import BaseModel, Field

class GeneratedQuestionSet(BaseModel):
    """The strict schema enforced on the LLM output."""
    questions: List[str] = Field(
        description="3 to 5 realistic questions that this text chunk answers directly."
    )

class RawChunk(BaseModel):
    """Input chunk received from the scraping/cleaning team."""
    chunk_id: str
    document_id: str = Field(..., description="Unique hash/ID of the parent scraped document/URL")
    source_url: str
    title: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class EnrichedChunk(RawChunk):
    """Output chunk containing the original data + generated query variants."""
    generated_questions: List[str] = Field(default_factory=list)