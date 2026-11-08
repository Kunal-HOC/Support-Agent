"""Helpers shared by the test suites (imported by conftest.py and tests)."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.config import Settings

SETTING_KEYS = (
    "DATABASE_URL",
    "EMBEDDING_DIMENSION",
    "APP_ENV",
    "LOG_LEVEL",
    "UPLOAD_DIR",
    "MAX_UPLOAD_BYTES",
    "MAX_PAGES",
    "SOP_CATEGORIES",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "OPENAI_API_KEY",
    "EMBEDDING_BATCH_SIZE",
    "CHUNKING_STRATEGY",
    "CHUNK_MAX_TOKENS",
    "CHUNK_OVERLAP_TOKENS",
    "TOKENIZER_ENCODING",
)
TEST_DATABASE_URL_VAR = "TEST_DATABASE_URL"

# Port 1 on localhost has nothing listening, so connections fail fast.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://user:pass@127.0.0.1:1/unreachable"

# Valid values for every key except UPLOAD_DIR, which tests set to a temp directory.
VALID_VALUES: dict[str, Any] = {
    "DATABASE_URL": UNREACHABLE_DATABASE_URL,
    "EMBEDDING_DIMENSION": 8,
    "APP_ENV": "test",
    "LOG_LEVEL": "WARNING",
    "MAX_UPLOAD_BYTES": 10_485_760,
    "MAX_PAGES": 150,
    "SOP_CATEGORIES": "Facilities,IT,HR",
    "EMBEDDING_PROVIDER": "openai",
    "EMBEDDING_MODEL": "fake-embedding-model",
    "OPENAI_API_KEY": "sk-test-not-a-real-key",
    "EMBEDDING_BATCH_SIZE": 4,
    "CHUNKING_STRATEGY": "heading",
    "CHUNK_MAX_TOKENS": 200,
    "CHUNK_OVERLAP_TOKENS": 20,
    "TOKENIZER_ENCODING": "cl100k_base",
}

MakeSettings = Callable[..., Settings]


@asynccontextmanager
async def running_app(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Run the app's lifespan and yield an HTTP client bound to it."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


# --- M2 ingestion helpers -------------------------------------------------

REPO_DIR = Path(__file__).resolve().parent
SOP_FIXTURES = REPO_DIR / "core" / "tests" / "fixtures" / "sop"
SOP_BASENAME = "workspace_booking"
TIKTOKEN_FIXTURE = REPO_DIR / "core" / "tests" / "fixtures" / "tiktoken" / "cl100k_base.tiktoken"
TIKTOKEN_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"

# The section paths the fictional SOP produces in every format.
SOP_TITLE = "Workspace Booking Procedure"
EXPECTED_SECTION_PATHS: list[tuple[str, ...]] = [
    (SOP_TITLE,),
    (SOP_TITLE, "1. Purpose"),
    (SOP_TITLE, "2. Scope"),
    (SOP_TITLE, "3. Booking a Desk", "3.1 Before You Book"),
    (SOP_TITLE, "3. Booking a Desk", "3.2 Making a Booking"),
    (SOP_TITLE, "4. Cancellations"),
    (SOP_TITLE, "5. Escalation"),
]
# PDF page of each section above (Cancellations starts page 2).
EXPECTED_PDF_PAGES = [1, 1, 1, 1, 1, 2, 2]


def load_sop_generator() -> ModuleType:
    """Import the fixture generator script by path."""
    name = "sop_fixture_generator"
    if name in sys.modules:
        return sys.modules[name]
    path = SOP_FIXTURES / "generate.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


def sop_fixture(extension: str) -> Path:
    return SOP_FIXTURES / f"{SOP_BASENAME}{extension}"


class FakeTokenizer:
    """Word-level tokenizer for unit tests: each word plus trailing space is a token."""

    _pattern = re.compile(r"\S+\s*|\s+")

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._pieces: list[str] = []

    def encode(self, text: str) -> list[int]:
        tokens: list[int] = []
        for piece in self._pattern.findall(text):
            if piece not in self._ids:
                self._ids[piece] = len(self._pieces)
                self._pieces.append(piece)
            tokens.append(self._ids[piece])
        return tokens

    def decode(self, tokens: Sequence[int]) -> str:
        return "".join(self._pieces[t] for t in tokens)


class FakeEmbedder:
    """Deterministic embedder: each vector is derived from the SHA-256 of its text."""

    def __init__(
        self,
        dimension: int,
        *,
        model: str = "fake-embedding-model",
        error: Exception | None = None,
    ) -> None:
        self.dimension = dimension
        self._model = model
        self.error = error
        self.batches: list[list[str]] = []

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        if self.error is not None:
            raise self.error
        return [fake_vector(text, self.dimension) for text in texts]

    async def aclose(self) -> None:
        return None


def fake_vector(text: str, dimension: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [(digest[i % len(digest)] / 127.5) - 1.0 for i in range(dimension)]
