"""Embedding provider used by the rebuildable local memory index."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Protocol


class EmbeddingProvider(Protocol):
    model_name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OpenAIEmbeddingProvider:
    def __init__(self, model_name: str | None = None):
        from langchain_openai import OpenAIEmbeddings

        self.model_name = model_name or os.getenv(
            "PHARMAMATE_EMBEDDING_MODEL", "text-embedding-3-small"
        )
        self.client = OpenAIEmbeddings(
            model=self.model_name,
            timeout=30,
            max_retries=1,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.client.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.client.embed_query(text)


@lru_cache(maxsize=2)
def get_embedding_provider(model_name: str | None = None) -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(model_name)
