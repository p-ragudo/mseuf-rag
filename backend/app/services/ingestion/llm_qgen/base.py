from abc import ABC, abstractmethod
from app.services.ingestion.llm_qgen.qgen import RawChunk, GeneratedQuestionSet

class BaseQuestionGenerator(ABC):
    @abstractmethod
    async def generate_questions(self, chunk: RawChunk) -> GeneratedQuestionSet:
        """Accepts a RawChunk and returns a validated GeneratedQuestionSet."""
        pass