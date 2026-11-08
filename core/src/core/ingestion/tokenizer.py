"""Token counting for chunking."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Protocol

import tiktoken


class Tokenizer(Protocol):
    def encode(self, text: str) -> list[int]: ...

    def decode(self, tokens: Sequence[int]) -> str: ...


class TiktokenTokenizer:
    """tiktoken encoding, loaded on first use.

    tiktoken downloads the encoding file the first time it is used (cached in
    TIKTOKEN_CACHE_DIR if set). Loading lazily keeps app startup independent of
    that download.
    """

    def __init__(self, encoding_name: str) -> None:
        self.encoding_name = encoding_name
        self._encoding: tiktoken.Encoding | None = None
        self._lock = threading.Lock()

    def _get(self) -> tiktoken.Encoding:
        with self._lock:
            if self._encoding is None:
                self._encoding = tiktoken.get_encoding(self.encoding_name)
            return self._encoding

    def encode(self, text: str) -> list[int]:
        return self._get().encode(text, disallowed_special=())

    def decode(self, tokens: Sequence[int]) -> str:
        return self._get().decode(list(tokens))
