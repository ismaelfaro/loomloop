"""Lightweight nanoloops built from plain functions."""

from __future__ import annotations

from typing import Awaitable, Callable, List, Optional, Union

from ..nanoloop import Context, NanoLoop, Step


StepFn = Callable[[Context], Awaitable[Step]]


def nanoloop(
    fn: Optional[StepFn] = None,
    *,
    name: Optional[str] = None,
    subscribe: Optional[List[str]] = None,
) -> Union[NanoLoop, Callable[[StepFn], NanoLoop]]:
    """Decorator that turns an ``async def step(ctx)`` into a nanoloop.

    The most direct way to declare an agent — the function *is* the loop::

        @nanoloop(subscribe=["ping"])
        async def ponger(ctx):
            for msg in ctx.recv_all():
                ctx.log("got", msg.payload)
            return Step.wait()

        loom.add(ponger)

    The agent's name defaults to the function name; override with ``name=``.
    Usable bare (``@nanoloop``) or called (``@nanoloop(subscribe=[...])``).
    """

    def wrap(f: StepFn) -> NanoLoop:
        return FunctionLoop(name or f.__name__, f, subscriptions=subscribe)

    return wrap if fn is None else wrap(fn)


class FunctionLoop(NanoLoop):
    """Wrap an ``async def step(ctx) -> Step`` function as a nanoloop.

    The quickest way to define an agent without writing a class::

        async def worker(ctx):
            for msg in ctx.recv_all():
                ctx.post("result", msg.payload * 2)
            return Step.wait()

        loom.add(FunctionLoop("worker", worker), subscribe=["jobs"])
    """

    def __init__(self, name: str, step_fn: StepFn, *, subscriptions: Optional[List[str]] = None) -> None:
        super().__init__(name)
        self._step_fn = step_fn
        self.subscriptions = list(subscriptions or [])

    async def step(self, ctx: Context) -> Step:
        return await self._step_fn(ctx)


class RelayLoop(NanoLoop):
    """Forward every incoming message to another topic, optionally transforming it.

    Useful as a pipe between stages of a pipeline, or as an adapter that renames
    topics so otherwise-incompatible agents can be wired together.
    """

    def __init__(
        self,
        name: str,
        *,
        listen: str,
        emit: str,
        transform: Optional[Callable[[object], object]] = None,
    ) -> None:
        super().__init__(name)
        self.subscriptions = [listen]
        self._emit = emit
        self._transform = transform or (lambda x: x)

    async def step(self, ctx: Context) -> Step:
        for msg in ctx.recv_all():
            ctx.send(self._emit, self._transform(msg.payload))
        return Step.wait()
