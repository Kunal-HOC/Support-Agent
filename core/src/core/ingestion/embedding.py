"""Embedding providers."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

import openai

from core.config import Settings
from core.ingestion.errors import EmbeddingError

_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-*]+")


class Embedder(Protocol):
    @property
    def model(self) -> str: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per text, in order."""
        ...

    async def aclose(self) -> None: ...


class OpenAIEmbedder:
    """OpenAI embeddings. Sends ``dimensions`` so vectors match EMBEDDING_DIMENSION."""

    def __init__(self, *, api_key: str, model: str, dimensions: int) -> None:
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._client = openai.AsyncOpenAI(api_key=api_key)

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenAIEmbedder:
        return cls(
            api_key=settings.OPENAI_API_KEY.get_secret_value(),
            model=settings.EMBEDDING_MODEL,
            dimensions=settings.EMBEDDING_DIMENSION,
        )

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = await self._client.embeddings.create(
                model=self._model, input=list(texts), dimensions=self._dimensions
            )
        except openai.OpenAIError as exc:
            raise EmbeddingError(self._redact(f"{type(exc).__name__}: {exc}")) from None
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]

    def _redact(self, message: str) -> str:
        message = message.replace(self._api_key, "***")
        return _API_KEY_PATTERN.sub("sk-***", message)

    async def aclose(self) -> None:
        await self._client.close()
