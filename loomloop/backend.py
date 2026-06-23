"""Pluggable model backends — keep LoomLoop agnostic about *who* thinks.

A :class:`Backend` is anything that can turn a prompt into a reply. The agent
loop (:class:`loomloop.agents.brain.BrainLoop`) talks only to this interface, so
the same coordinated system runs on a local rule, a hosted LLM, or a mock —
swap the backend, not the agents.

Built in:

* :class:`EchoBackend`     — deterministic, dependency-free (tests, offline demos)
* :class:`CallableBackend` — adapt any function ``fn(prompt) -> str``
* :class:`ClaudeBackend`   — Anthropic's Claude (optional ``anthropic`` dependency)

Write your own by implementing one async method::

    class MyBackend:
        async def generate(self, prompt, *, system="", history=None) -> str:
            ...
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, List, Optional, Protocol, runtime_checkable

History = List[dict]


@runtime_checkable
class Backend(Protocol):
    """The one method every model backend must provide."""

    async def generate(self, prompt: str, *, system: str = "", history: Optional[History] = None) -> str:
        ...


class EchoBackend:
    """A deterministic backend with no dependencies.

    Returns a transform of the prompt. Use it in tests and offline demos so a
    multi-agent system runs end-to-end without any API keys or network.
    """

    def __init__(self, transform: Optional[Callable[[str], str]] = None) -> None:
        self._transform = transform or (lambda p: f"echo: {p}")

    async def generate(self, prompt: str, *, system: str = "", history: Optional[History] = None) -> str:
        return self._transform(prompt)


class CallableBackend:
    """Adapt any callable into a backend.

    The callable may be sync or async and is invoked as ``fn(prompt)``. Handy for
    wiring in a quick heuristic, a retrieval call, or a non-Claude SDK.
    """

    def __init__(self, fn: Callable[[str], "str | Awaitable[str]"]) -> None:
        self._fn = fn

    async def generate(self, prompt: str, *, system: str = "", history: Optional[History] = None) -> str:
        result = self._fn(prompt)
        if asyncio.iscoroutine(result):
            result = await result
        return str(result)


# Recommended default when using Claude. Kept here so callers don't hard-code it.
DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"


class ClaudeBackend:
    """A :class:`Backend` backed by Anthropic's Claude.

    Requires the optional ``anthropic`` package and ``ANTHROPIC_API_KEY`` in the
    environment. Defaults to Claude Opus 4.8 with adaptive thinking — the
    recommended setup for agentic decision-making — and uses the async client so
    a slow call on one agent doesn't stall the others on a tick.

    Pass a pre-built ``client`` to inject a mock or a platform client
    (Bedrock/Vertex/etc.).
    """

    def __init__(
        self,
        model: str = DEFAULT_CLAUDE_MODEL,
        *,
        max_tokens: int = 1024,
        effort: str = "medium",
        client: object | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self._client = client

    def _ensure_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - optional dep
                raise RuntimeError(
                    "ClaudeBackend needs the 'anthropic' package: "
                    'pip install "loomloop[llm]"'
                ) from exc
            self._client = anthropic.AsyncAnthropic()
        return self._client

    async def generate(self, prompt: str, *, system: str = "", history: Optional[History] = None) -> str:
        client = self._ensure_client()
        messages = list(history or []) + [{"role": "user", "content": prompt}]
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            messages=messages,
        )
        if system:
            kwargs["system"] = system
        resp = await client.messages.create(**kwargs)
        return "".join(b.text for b in resp.content if b.type == "text")


__all__ = [
    "Backend",
    "EchoBackend",
    "CallableBackend",
    "ClaudeBackend",
    "DEFAULT_CLAUDE_MODEL",
    "History",
]
