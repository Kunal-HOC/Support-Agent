from __future__ import annotations

import json

import httpx2 as httpx
import openai
import pytest

from core.ingestion.embedding import OpenAIEmbedder
from core.ingestion.errors import EmbeddingError

API_KEY = "sk-test-abcdefghijklmnop1234"


def _embedder(handler: httpx.MockTransport) -> OpenAIEmbedder:
    embedder = OpenAIEmbedder(api_key=API_KEY, model="text-embedding-3-small", dimensions=3)
    embedder._client = openai.AsyncOpenAI(  # noqa: SLF001 - swap in a mocked transport
        api_key=API_KEY, http_client=httpx.AsyncClient(transport=handler), max_retries=0
    )
    return embedder


async def test_sends_model_and_dimensions_and_orders_results() -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        data = [
            {"object": "embedding", "index": 1, "embedding": [0.4, 0.5, 0.6]},
            {"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]},
        ]
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": data,
                "model": "text-embedding-3-small",
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    embedder = _embedder(httpx.MockTransport(handle))
    vectors = await embedder.embed(["first", "second"])
    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert seen["model"] == "text-embedding-3-small"
    assert seen["dimensions"] == 3
    assert seen["input"] == ["first", "second"]
    await embedder.aclose()


async def test_errors_never_contain_the_api_key() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        message = f"Incorrect API key provided: {API_KEY}. Also sk-test-abc***1234."
        return httpx.Response(401, json={"error": {"message": message, "type": "invalid"}})

    embedder = _embedder(httpx.MockTransport(handle))
    with pytest.raises(EmbeddingError) as info:
        await embedder.embed(["x"])
    assert "AuthenticationError" in str(info.value)
    assert API_KEY not in str(info.value)
    assert "sk-test" not in str(info.value)
    await embedder.aclose()
