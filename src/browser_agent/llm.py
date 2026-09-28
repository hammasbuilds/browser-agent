"""Chat clients for the model arm: Ollama over HTTP, an on-disk cache, and a test fake.

Only the standard library is used for HTTP. Every generation is cached under
``cache/<model>/<sha256>.json`` keyed by (model, messages, options), so an interrupted run
resumes without repeating a single call, and a finished run can be re-scored for free.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

Message = dict[str, str]
DEFAULT_MODEL = "qwen2.5:14b-instruct"
DEFAULT_URL = "http://127.0.0.1:11434"


class ChatClient(Protocol):
    model: str

    def chat(self, messages: list[Message], options: dict[str, Any]) -> str: ...


class LLMUnavailableError(RuntimeError):
    pass


# 4xx statuses that can succeed on a retry; any other 4xx (unknown model, bad request) cannot.
RETRYABLE_4XX = {408, 429}


def _http_reason(exc: urllib.error.HTTPError) -> str:
    """``HTTP 404: model "x" not found``: the status plus Ollama's own ``error`` text."""
    try:
        body = exc.read().decode("utf-8", errors="replace").strip()
    except OSError:
        body = ""
    try:
        detail = json.loads(body).get("error") or body
    except (ValueError, AttributeError):
        detail = body
    return f"HTTP {exc.code}: {detail or exc.reason}"


@dataclass
class OllamaClient:
    """``/api/chat`` over HTTP. Transient failures (connection refused or dropped, a stalled
    reply, a malformed or error payload, a 5xx) are retried with exponential backoff; if every
    attempt fails the result is one :class:`LLMUnavailableError`, never a raw traceback. A 4xx
    (other than 408/429) is the request's fault, so it fails at once, with the body's reason."""

    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_URL
    timeout_s: float = 600.0
    attempts: int = 3
    backoff_s: float = 2.0

    def chat(self, messages: list[Message], options: dict[str, Any]) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": options,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat", data=body, headers={"Content-Type": "application/json"}
        )
        last = ""
        for attempt in range(self.attempts):
            if attempt:
                time.sleep(self.backoff_s * 2 ** (attempt - 1))
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                content = payload["message"]["content"]
                if not isinstance(content, str):
                    raise TypeError("message content is not a string")
                return content
            except urllib.error.HTTPError as exc:
                last = _http_reason(exc)
                if 400 <= exc.code < 500 and exc.code not in RETRYABLE_4XX:
                    raise LLMUnavailableError(
                        f"ollama at {self.base_url} refused the request; {last}"
                    ) from None
            except (OSError, http.client.HTTPException, ValueError) as exc:
                # OSError covers URLError, timeouts and dropped connections; ValueError covers
                # a body that is not JSON.
                last = f"{type(exc).__name__}: {exc}"
            except (KeyError, TypeError) as exc:
                error = payload.get("error") if isinstance(payload, dict) else None
                last = f"unexpected reply ({error or exc!r})"
        raise LLMUnavailableError(
            f"ollama at {self.base_url} failed {self.attempts} times; last: {last}"
        )


def cache_key(model: str, messages: list[Message], options: dict[str, Any]) -> str:
    blob = json.dumps({"model": model, "messages": messages, "options": options}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class CachedClient:
    inner: ChatClient
    root: Path
    hits: int = 0
    misses: int = 0

    @property
    def model(self) -> str:
        return self.inner.model

    def path_for(self, messages: list[Message], options: dict[str, Any]) -> Path:
        safe_model = self.inner.model.replace(":", "_").replace("/", "_")
        return self.root / safe_model / f"{cache_key(self.model, messages, options)}.json"

    def chat(self, messages: list[Message], options: dict[str, Any]) -> str:
        path = self.path_for(messages, options)
        if path.is_file():
            self.hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        self.misses += 1
        response = self.inner.chat(messages, options)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"response": response}), encoding="utf-8")
        tmp.replace(path)
        return response


@dataclass
class FakeClient:
    """Deterministic stand-in: ``policy`` maps the conversation to a reply."""

    policy: Callable[[list[Message]], str]
    model: str = "fake"
    calls: list[list[Message]] = field(default_factory=list)

    def chat(self, messages: list[Message], options: dict[str, Any]) -> str:
        self.calls.append(messages)
        return self.policy(messages)
