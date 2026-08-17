from abc import ABC, abstractmethod
from typing import List
from ..schema import RawChunk, GeneratedQuestion

class BaseQuestionGenerator(ABC):
    @abstractmethod
    async def generate_questions(self, chunk: RawChunk) -> List[GeneratedQuestion]:
        """Accepts a RawChunk and returns a list of GeneratedQuestion objects."""
        pass