"""A small client for OpenRouter (or any OpenAI-compatible chat endpoint).

Configuration only: LLM_MODEL and LLM_API_KEY (and LLM_BASE_URL if you point it elsewhere).
The key stays on the server and never reaches the browser.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings, get_settings


class LlmUnavailable(Exception):
    """The model could not be reached or refused. `retry_after` is set for rate limits."""

    def __init__(self, message: str, status_code: int = 503, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    seconds: float


class ChatClient(Protocol):
    model: str

    def complete(self, messages: list[dict]) -> Completion: ...


def configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(s.llm_base_url.strip() and s.llm_model.strip() and s.llm_api_key.strip())


class OpenAICompatibleClient:
    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None):
        self.s = settings or get_settings()
        self.model = self.s.llm_model
        self._transport = transport

    def complete(self, messages: list[dict]) -> Completion:
        s = self.s
        body: dict = {
            "model": s.llm_model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": s.llm_max_tokens,
        }
        if s.llm_json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json", "X-Title": "Chess Review Lab"}  # OpenRouter attribution
        if s.llm_api_key:
            headers["Authorization"] = f"Bearer {s.llm_api_key}"
        url = s.llm_base_url.rstrip("/") + "/chat/completions"
        start = time.perf_counter()
        try:
            with httpx.Client(timeout=s.llm_timeout_seconds, transport=self._transport) as http:
                resp = http.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise LlmUnavailable("The explanation model took too long to answer.", 504) from exc
        except httpx.HTTPError as exc:
            raise LlmUnavailable("The explanation model could not be reached.", 502) from exc
        took = time.perf_counter() - start

        if resp.status_code == 429:
            try:
                wait = int(float(resp.headers.get("retry-after", "30")))
            except ValueError:
                wait = 30
            raise LlmUnavailable("The explanation model is busy. Try again shortly.", 429, wait)
        if resp.status_code in (401, 403):
            raise LlmUnavailable("The explanation service rejected the API key.", 502)
        if resp.status_code == 402:
            raise LlmUnavailable("The explanation service has no credit left for this model.", 502)
        if resp.status_code >= 400:
            # never echo the provider's body: it may contain details about the key or the request
            raise LlmUnavailable(f"The explanation model returned an error ({resp.status_code}).", 502)
        try:
            payload = resp.json()
            text = payload["choices"][0]["message"]["content"] or ""
            usage = payload.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LlmUnavailable("The explanation model sent an unreadable reply.", 502) from exc
        return Completion(
            text=text,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            seconds=took,
        )
