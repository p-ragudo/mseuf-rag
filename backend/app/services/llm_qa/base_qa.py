from abc import ABC, abstractmethod
from .schema import QARequest, QAResponse

class BaseQASynthesizer(ABC):
    @abstractmethod
    async def generate_answer(self, request: QARequest) -> QAResponse:
        """Accepts a QARequest (query + retrieved contexts) and returns a QAResponse."""
        pass