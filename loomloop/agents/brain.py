"""A nanoloop whose decisions come from a pluggable model :class:`Backend`.

This is the bridge between LoomLoop's coordination machinery and *any* model.
The agent is backend-agnostic: give it an :class:`~loomloop.backend.EchoBackend`
for an offline test, a :class:`~loomloop.backend.ClaudeBackend` for real
autonomy, or your own backend — the surrounding nanoloop, bus, and blackboard
never change.

Each message the agent receives becomes a turn; the backend's reply is published
back onto the bus (on ``emit``, or directly to the sender if ``emit`` is None).
"""

from __future__ import annotations

from typing import List, Optional

from ..backend import Backend
from ..nanoloop import Context, NanoLoop, Step


class BrainLoop(NanoLoop):
    """A nanoloop driven by a model backend.

    Parameters
    ----------
    name:
        Agent name (and bus identity).
    backend:
        Any :class:`~loomloop.backend.Backend`. This is what makes the agent
        provider-agnostic — LoomLoop never imports a specific SDK here.
    system:
        Role description handed to the backend on every turn.
    listen:
        Topic(s) to receive work on. Each message payload (stringified) becomes
        a prompt.
    emit:
        Topic to publish replies on. If ``None``, reply to the sender directly.
    keep_history:
        If true, prior turns are replayed so the agent has conversational memory.
    """

    def __init__(
        self,
        name: str,
        *,
        backend: Backend,
        system: str = "",
        listen: "str | List[str]",
        emit: Optional[str] = None,
        keep_history: bool = True,
    ) -> None:
        super().__init__(name)
        self.subscriptions = [listen] if isinstance(listen, str) else list(listen)
        self._backend = backend
        self._system = system
        self._emit = emit
        self._keep_history = keep_history
        self._history: List[dict] = []

    async def step(self, ctx: Context) -> Step:
        messages = ctx.recv_all()
        if not messages:
            return Step.wait()

        for msg in messages:
            prompt = str(msg.payload)
            reply = await self._backend.generate(
                prompt,
                system=self._system,
                history=self._history if self._keep_history else None,
            )
            ctx.log(f"-> {reply[:80]}")
            if self._keep_history:
                self._history.append({"role": "user", "content": prompt})
                self._history.append({"role": "assistant", "content": reply})
            if self._emit is not None:
                ctx.send(self._emit, reply)
            else:
                ctx.reply(msg, reply)
        return Step.wait()


# Backwards-friendly alias: "the LLM agent" is just a brain with an LLM backend.
LLMLoop = BrainLoop

__all__ = ["BrainLoop", "LLMLoop"]
