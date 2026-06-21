"""A Claude-backed nanoloop.

This turns a coordinated agent into a genuinely autonomous one: instead of a
hand-written rule in ``step()``, the agent's decision is produced by Claude. Each
message it receives becomes a turn; Claude's reply is published back onto the bus.

Requires the optional ``anthropic`` package and an ``ANTHROPIC_API_KEY`` in the
environment::

    pip install "loomloop[llm]"   # or: pip install anthropic

The model defaults to Claude Opus 4.8 with adaptive thinking — the recommended
configuration for agentic decision-making.
"""

from __future__ import annotations

from typing import List, Optional

from ..nanoloop import Context, NanoLoop, Step

DEFAULT_MODEL = "claude-opus-4-8"


class LLMLoop(NanoLoop):
    """An agent whose every step is a Claude completion.

    Parameters
    ----------
    name:
        Agent name (and bus identity).
    system:
        System prompt describing this agent's role in the collective.
    listen:
        Topic(s) to receive work on. Each message's payload (stringified) is fed
        to Claude as a user turn.
    emit:
        Topic to publish Claude's reply on. If ``None``, the agent replies
        directly to whichever agent sent the message.
    model:
        Claude model id. Defaults to Claude Opus 4.8.
    max_tokens, effort:
        Standard generation controls.
    keep_history:
        If true, prior turns are resent so the agent has conversational memory.
    """

    def __init__(
        self,
        name: str,
        *,
        system: str,
        listen: str | List[str],
        emit: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1024,
        effort: str = "medium",
        keep_history: bool = True,
    ) -> None:
        super().__init__(name)
        self.subscriptions = [listen] if isinstance(listen, str) else list(listen)
        self._system = system
        self._emit = emit
        self._model = model
        self._max_tokens = max_tokens
        self._effort = effort
        self._keep_history = keep_history
        self._history: List[dict] = []
        self._client = None

    async def setup(self, ctx: Context) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise RuntimeError(
                "LLMLoop needs the 'anthropic' package: pip install \"loomloop[llm]\""
            ) from exc
        # AsyncAnthropic so a slow call doesn't stall other agents on the tick.
        self._client = anthropic.AsyncAnthropic()

    async def step(self, ctx: Context) -> Step:
        messages = ctx.recv_all()
        if not messages:
            return Step.wait()

        for msg in messages:
            reply = await self._respond(str(msg.payload))
            ctx.log(f"-> {reply[:80]}")
            if self._emit is not None:
                ctx.send(self._emit, reply)
            else:
                ctx.reply(msg, reply)
        return Step.wait()

    async def _respond(self, user_text: str) -> str:
        turns = list(self._history) if self._keep_history else []
        turns.append({"role": "user", "content": user_text})

        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=self._system,
            thinking={"type": "adaptive"},
            output_config={"effort": self._effort},
            messages=turns,
        )
        text = "".join(b.text for b in resp.content if b.type == "text")

        if self._keep_history:
            self._history.append({"role": "user", "content": user_text})
            self._history.append({"role": "assistant", "content": text})
        return text
