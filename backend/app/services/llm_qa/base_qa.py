from abc import ABC, abstractmethod
from .schema import QARequest, QAResponse


class BaseQASynthesizer(ABC):
    @abstractmethod
    async def generate_answer(self, request: QARequest, org_name: str = "the institution") -> QAResponse:
        """Accepts a QARequest (query + retrieved contexts) and returns a QAResponse."""
        pass