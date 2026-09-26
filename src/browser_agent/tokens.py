"""Token counts with the Qwen2.5 tokenizer, the tokenizer of the model the agent arm uses.

The tokenizer (``tokenizer.json`` from Qwen/Qwen2.5-14B-Instruct, git blob
``443909a61d429dff23010e5bddd28ff530edda00``) is vendored gzipped, so counting needs no network
and no model: it is a BPE table, not weights.
"""

from __future__ import annotations

import gzip
from functools import lru_cache
from pathlib import Path

from tokenizers import Tokenizer

TOKENIZER_PATH = Path(__file__).resolve().parents[2] / "vendor" / "qwen2.5-tokenizer.json.gz"


@lru_cache(maxsize=1)
def qwen_tokenizer() -> Tokenizer:
    if not TOKENIZER_PATH.is_file():
        raise FileNotFoundError(f"vendored tokenizer missing: {TOKENIZER_PATH}")
    return Tokenizer.from_str(gzip.decompress(TOKENIZER_PATH.read_bytes()).decode("utf-8"))


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(qwen_tokenizer().encode(text, add_special_tokens=False).ids)
