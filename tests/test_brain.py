import asyncio

from loomloop import (
    BrainLoop,
    CallableBackend,
    EchoBackend,
    FunctionLoop,
    Loom,
    Step,
    nanoloop,
)


def run(coro):
    return asyncio.run(coro)


def test_brain_loop_with_echo_backend():
    loom = Loom(logger=lambda _l: None)

    async def source(ctx):
        if ctx.tick == 0:
            ctx.send("q", "hello")
            return Step.cont()
        return Step.done()

    async def sink(ctx):
        for msg in ctx.recv_all():
            ctx.post("answer", msg.payload)
        return Step.wait()

    loom.add(FunctionLoop("source", source))
    loom.add(
        BrainLoop(
            "brain",
            backend=EchoBackend(lambda p: p.upper()),
            listen="q",
            emit="a",
        )
    )
    loom.add(FunctionLoop("sink", sink), subscribe=["a"])
    run(loom.run(max_ticks=10))
    assert loom.blackboard.get("answer") == "HELLO"


def test_brain_loop_keeps_history():
    seen_histories = []

    def fn(prompt):
        return f"reply-{prompt}"

    backend = CallableBackend(fn)

    # wrap to capture history length over turns
    class Recording(EchoBackend):
        async def generate(self, prompt, *, system="", history=None):
            seen_histories.append(len(history or []))
            return f"r{prompt}"

    loom = Loom(logger=lambda _l: None)

    async def source(ctx):
        if ctx.tick < 2:
            ctx.send("q", str(ctx.tick))
            return Step.cont()
        return Step.done()

    loom.add(FunctionLoop("source", source))
    loom.add(BrainLoop("brain", backend=Recording(), listen="q"))
    run(loom.run(max_ticks=10))
    # first turn sees empty history, second turn sees the prior user+assistant pair
    assert seen_histories[0] == 0
    assert seen_histories[-1] == 2


def test_nanoloop_decorator():
    loom = Loom(logger=lambda _l: None)

    @nanoloop
    async def emitter(ctx):
        if ctx.tick == 0:
            ctx.send("t", 42)
        return Step.cont() if ctx.tick < 1 else Step.done()

    @nanoloop(name="catcher", subscribe=["t"])
    async def _catch(ctx):
        for m in ctx.recv_all():
            ctx.post("caught", m.payload)
        return Step.wait()

    loom.add(emitter)
    loom.add(_catch)
    run(loom.run(max_ticks=5))
    assert loom.blackboard.get("caught") == 42
    assert emitter.name == "emitter"
    assert _catch.name == "catcher"
