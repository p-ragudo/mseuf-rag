from functools import lru_cache
from app.core.config import settings
from app.services.reranker.base import BaseReranker
from app.services.reranker.fastembed_provider import FastEmbedReranker


class RerankerFactory:
    @staticmethod
    def create() -> BaseReranker:
        model_name = getattr(
            settings,
            "reranker_model_name",
            "Xenova/ms-marco-MiniLM-L-12-v2",
        )
        return FastEmbedReranker(model_name=model_name)


@lru_cache(maxsize=1)
def get_reranker() -> BaseReranker:
    return RerankerFactory.create()