"""Unified LLM client for DeepSeek, Qwen, and OpenAI via OpenAI-compatible APIs.

Uses httpx directly; no OpenAI SDK dependency.
Environment-driven provider selection: ``LLM_PROVIDER``, ``*_API_KEY``.
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Usage:
    """Token usage statistics returned by the LLM."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class LLMResponse:
    """Standardised LLM call result."""

    content: str
    usage: Usage
    model: str
    raw_response: dict[str, Any] | None = None

    @property
    def prompt_tokens(self) -> int:
        """Convenience accessor for prompt token count."""
        return self.usage.prompt_tokens

    @property
    def completion_tokens(self) -> int:
        """Convenience accessor for completion token count."""
        return self.usage.completion_tokens

    @property
    def total_tokens(self) -> int:
        """Convenience accessor for total token count."""
        return self.usage.total_tokens


# ---------------------------------------------------------------------------
# Abstract provider interface
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract base for LLM backends."""

    @abstractmethod
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        """Send a chat-completion request.

        Args:
            messages: Sequence of ``{"role": ..., "content": ...}`` dicts.
            **kwargs: Extra parameters forwarded to the API (temperature,
                max_tokens, top_p, etc.).

        Returns:
            An ``LLMResponse`` wrapping the assistant reply and token usage.
        """
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the model identifier used by this provider."""
        ...


# ---------------------------------------------------------------------------
# Base implementation for OpenAI-compatible endpoints
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(LLMProvider):
    """Generic provider for any OpenAI-compatible chat-completions API."""

    _DEFAULT_TIMEOUT: float = 60.0

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        extra_headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ):
        """Initialise the provider.

        Args:
            api_key: Bearer token sent in ``Authorization`` header.
            base_url: API base URL (e.g. ``https://api.deepseek.com``).
            model: Model ID passed in the request payload.
            extra_headers: Optional additional headers merged into every
                request (useful for beta features or custom auth).
            timeout: HTTP request timeout in seconds (default 60).
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._extra_headers = extra_headers or {}
        self._timeout = timeout or self._DEFAULT_TIMEOUT

    # -- LLMProvider interface -----------------------------------------------

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        """Send a chat-completion request.

        Args:
            messages: Conversation history as role/content dicts.
            **kwargs: API parameters (temperature, max_tokens, etc.).

        Returns:
            ``LLMResponse`` with the assistant message and token usage.

        Raises:
            httpx.HTTPError: On transport or HTTP-level failures.
        """
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            **self._extra_headers,
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            **kwargs,
        }

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

        choice = data["choices"][0]
        message = choice["message"]
        usage = data.get("usage", {})

        return LLMResponse(
            content=message.get("content", ""),
            usage=Usage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            ),
            model=self._model,
            raw_response=data,
        )

    def get_model_name(self) -> str:
        """Return the model name."""
        return self._model


# ---------------------------------------------------------------------------
# Concrete providers
# ---------------------------------------------------------------------------


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek chat-completions provider.

    Reads ``DEEPSEEK_API_KEY`` and optionally ``DEEPSEEK_BASE_URL`` from the
    environment if not passed explicitly.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "deepseek-chat",
    ):
        api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        super().__init__(api_key=api_key, base_url=base_url, model=model)


class QwenProvider(OpenAICompatibleProvider):
    """Alibaba Qwen (DashScope) chat-completions provider.

    Reads ``DASHSCOPE_API_KEY`` and optionally ``DASHSCOPE_BASE_URL`` from the
    environment if not passed explicitly.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "qwen-turbo",
    ):
        api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        base_url = os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        super().__init__(api_key=api_key, base_url=base_url, model=model)


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI chat-completions provider.

    Reads ``OPENAI_API_KEY`` and optionally ``OPENAI_BASE_URL`` from the
    environment if not passed explicitly.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
    ):
        api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        super().__init__(api_key=api_key, base_url=base_url, model=model)


# ---------------------------------------------------------------------------
# Provider registry & factory
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "qwen": QwenProvider,
    "openai": OpenAIProvider,
}

_DEFAULT_MODELS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "qwen": "qwen-turbo",
    "openai": "gpt-4o-mini",
}


def create_provider(
    name: str | None = None,
    **kwargs: Any,
) -> LLMProvider:
    """Factory: create an ``LLMProvider`` from an environment variable or string.

    Provider is resolved as follows:
    1. Explicit *name* argument.
    2. ``LLM_PROVIDER`` environment variable.
    3. Fallback ``"deepseek"``.

    Args:
        name: One of ``"deepseek"``, ``"qwen"``, ``"openai"``.
        **kwargs: Forwarded to the provider constructor (``model``, etc.).

    Returns:
        A ready-to-use ``LLMProvider`` instance.

    Raises:
        ValueError: If *name* is not a recognised provider.
    """
    name = (name or os.getenv("LLM_PROVIDER", "deepseek")).lower()
    if name not in _PROVIDER_REGISTRY:
        raise ValueError(
            f"Unknown provider '{name}'. "
            f"Available: {list(_PROVIDER_REGISTRY.keys())}"
        )

    cls = _PROVIDER_REGISTRY[name]
    kwargs.setdefault("model", _DEFAULT_MODELS[name])
    return cls(**kwargs)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------


def chat_with_retry(
    messages: list[dict[str, str]],
    provider: LLMProvider | None = None,
    provider_name: str | None = None,
    max_retries: int = 3,
    base_delay: float = 1.0,
    timeout: float = 60.0,
    **kwargs: Any,
) -> LLMResponse:
    """Call ``provider.chat(messages)`` with exponential-backoff retries.

    Args:
        messages: Chat message list.
        provider: Existing ``LLMProvider`` instance (takes precedence).
        provider_name: Provider name used to create a new provider when
            *provider* is ``None``.
        max_retries: Maximum number of attempts (default 3).
        base_delay: Initial backoff in seconds; doubles each retry.
        timeout: Request timeout forwarded to ``create_provider``.
        **kwargs: Forwarded to ``provider.chat()``.

    Returns:
        ``LLMResponse`` on success.

    Raises:
        RuntimeError: When all retry attempts are exhausted.
    """
    if provider is None:
        provider = create_provider(provider_name, timeout=timeout)

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return provider.chat(messages, **kwargs)
        except Exception as exc:
            last_error = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt + 1,
                    max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "All %d attempts exhausted. Last error: %s",
                    max_retries,
                    exc,
                )

    raise RuntimeError("chat_with_retry exhausted all retries") from last_error


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

# USD per 1M tokens (input / output)
_PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "qwen-turbo": {"input": 0.30, "output": 0.30},
    "qwen-plus": {"input": 0.80, "output": 0.80},
    "qwen-max": {"input": 2.40, "output": 9.60},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in *text* using character heuristics.

    Rough algorithm:
        - CJK characters  -> ~0.5 tokens each.
        - Other characters -> ~0.25 tokens each.

    Args:
        text: Arbitrary string (may be empty).

    Returns:
        Estimated token count (integer, rounded down).

    Examples:
        >>> estimate_tokens("Hello")
        1
        >>> estimate_tokens("你好世界")
        2
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk / 2 + other / 4)


def calculate_cost(
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    model: str | None = None,
    usage: Usage | None = None,
) -> float:
    """Compute the USD cost of a chat-completion call.

    Args:
        prompt_tokens: Input token count (ignored when *usage* is given).
        completion_tokens: Output token count (ignored when *usage* is given).
        model: Model ID used to look up pricing.  If unknown, returns 0.0.
        usage: ``Usage`` object; when provided, token values override the
            individual args.

    Returns:
        Cost in USD, rounded to 6 decimal places.

    Examples:
        >>> calculate_cost(1000, 500, "gpt-4o-mini")
        0.00045
    """
    if usage is not None:
        prompt_tokens = usage.prompt_tokens
        completion_tokens = usage.completion_tokens

    if model is None or model not in _PRICING:
        logger.debug("No pricing data for model %r -- cost set to 0", model)
        return 0.0

    pricing = _PRICING[model]
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


# ---------------------------------------------------------------------------
# Convenience helper
# ---------------------------------------------------------------------------


def quick_chat(
    prompt: str,
    system_prompt: str | None = None,
    provider: LLMProvider | str | None = None,
    **kwargs: Any,
) -> LLMResponse:
    """One-liner: send a single-turn prompt and get the response.

    Args:
        prompt: User message text.
        system_prompt: Optional system-level instruction.
        provider: ``LLMProvider`` instance, a provider name string, or
            ``None`` (auto-created via ``create_provider()``).
        **kwargs: Extra parameters passed to ``provider.chat()``.

    Returns:
        ``LLMResponse`` with the assistant reply and usage stats.

    Examples:
        >>> resp = quick_chat("What is 2+2?")
        >>> print(resp.content)
        4
    """
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    if provider is None:
        provider = create_provider()
    elif isinstance(provider, str):
        provider = create_provider(provider)

    return provider.chat(messages, **kwargs)


# ---------------------------------------------------------------------------
# Smoke test (run with: python -m pipeline.model_client)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== LLM 客户端测试 ===\n")

    providers_to_test = [
        ("deepseek", "用中文简要解释什么是 AI Agent（100 字以内）"),
    ]

    for pname, prompt in providers_to_test:
        try:
            print(f"提供商: {pname}")
            prov = create_provider(pname)
            logger.info(
                "创建 LLM 客户端: provider=%s, model=%s",
                pname,
                prov.get_model_name(),
            )

            messages = [
                {"role": "user", "content": prompt},
            ]
            resp = chat_with_retry(
                messages,
                provider=prov,
                max_retries=2,
                timeout=60.0,
                temperature=0.3,
            )

            logger.info(
                "Token 用量: %d (prompt) + %d (completion) = %d, 估算成本: $%.6f",
                resp.usage.prompt_tokens,
                resp.usage.completion_tokens,
                resp.usage.total_tokens,
                calculate_cost(usage=resp.usage, model=resp.model),
            )

            print(f"\n回复: {resp.content}")
            print()
        except Exception:
            logger.exception("提供商 %s 调用失败", pname)
            print()

    print("=== 测试完成 ===")
