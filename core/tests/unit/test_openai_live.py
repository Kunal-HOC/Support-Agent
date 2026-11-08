"""Opt-in: calls the real OpenAI API. Run with: pytest -m openai --run-openai

Needs TEST_OPENAI_API_KEY and TEST_EMBEDDING_MODEL in the environment.
"""

from __future__ import annotations

import os

import pytest

from core.ingestion.embedding import OpenAIEmbedder

pytestmark = pytest.mark.openai


async def test_real_openai_embeddings() -> None:
    api_key = os.environ.get("TEST_OPENAI_API_KEY")
    model = os.environ.get("TEST_EMBEDDING_MODEL")
    if not api_key or not model:
        pytest.fail("Set TEST_OPENAI_API_KEY and TEST_EMBEDDING_MODEL to run this test.")
    embedder = OpenAIEmbedder(api_key=api_key, model=model, dimensions=256)
    try:
        vectors = await embedder.embed(["Book a desk before Monday.", "Cancel two hours ahead."])
    finally:
        await embedder.aclose()
    assert len(vectors) == 2
    assert all(len(vector) == 256 for vector in vectors)
