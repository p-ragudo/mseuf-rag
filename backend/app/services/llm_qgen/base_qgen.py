from abc import ABC, abstractmethod
from typing import Dict, List
from .schema import RawChunk, GeneratedQuestion


class BaseQuestionGenerator(ABC):
    @abstractmethod
    async def generate_questions(self, chunk: RawChunk) -> List[GeneratedQuestion]:
        """Accepts a RawChunk and returns a list of GeneratedQuestion objects."""
        pass

    @abstractmethod
    async def generate_questions_batch(self, chunks: List[RawChunk]) -> Dict[str, List[GeneratedQuestion]]:
        """
        Accepts a batch of RawChunks and returns a mapping of chunk_id to GeneratedQuestions.
        Contract: a chunk id is present in the result ONLY if the model actually answered for it
        (an empty list means "boilerplate, no questions"). Missing ids mean "retry later".
        Raises on unparseable output.
        """
        pass
