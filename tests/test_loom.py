import asyncio

from loomloop import FunctionLoop, Loom, NanoLoop, Step, Status
from loomloop.scheduler import RoundRobin, Priority


def run(coro):
    return asyncio.run(coro)


def test_max_ticks_and_continue():
    loom = Loom(logger=lambda _l: None)

    async def counter(ctx):
        ctx.post("n", ctx.read("n", 0) + 1)
        return Step.cont()

    loom.add(FunctionLoop("counter", counter))
    report = run(loom.run(max_ticks=5))
    assert loom.blackboard.get("n") == 5
    assert report.ticks == 5
    assert report.steps == 5


def test_done_retires_agent():
    loom = Loom(logger=lambda _l: None)

    async def once(ctx):
        ctx.post("ran", True)
        return Step.done()

    loom.add(FunctionLoop("once", once))
    run(loom.run(max_ticks=10))
    assert loom.blackboard.get("ran") is True
    assert loom.status()["once"] is Status.DONE


def test_quiescence_stops_early():
    # an agent that only WAITs and never receives mail -> loom goes quiescent
    loom = Loom(logger=lambda _l: None)

    async def waiter(ctx):
        return Step.wait()

    loom.add(FunctionLoop("waiter", waiter))
    report = run(loom.run(max_ticks=100))
    assert report.ticks <= 1  # nothing to do; stops immediately


def test_message_delivery_between_agents():
    loom = Loom(logger=lambda _l: None)

    async def producer(ctx):
        if ctx.tick < 3:
            ctx.send("nums", ctx.tick)
            return Step.cont()
        return Step.done()

    async def consumer(ctx):
        for msg in ctx.recv_all():
            ctx.post("seen", ctx.read("seen", []) + [msg.payload])
        return Step.wait()

    loom.add(FunctionLoop("producer", producer))
    loom.add(FunctionLoop("consumer", consumer), subscribe=["nums"])
    run(loom.run(max_ticks=20))
    assert loom.blackboard.get("seen") == [0, 1, 2]


def test_delay_skips_ticks():
    loom = Loom(logger=lambda _l: None)

    async def slow(ctx):
        ctx.post("runs", ctx.read("runs", 0) + 1)
        return Step.cont(delay=1)  # run every other tick

    loom.add(FunctionLoop("slow", slow))
    run(loom.run(max_ticks=6))
    # ran at ticks 0,2,4 -> 3 times within 6 ticks
    assert loom.blackboard.get("runs") == 3


def test_agent_error_is_isolated():
    loom = Loom(logger=lambda _l: None)

    async def boom(ctx):
        raise ValueError("kaboom")

    async def survivor(ctx):
        ctx.post("alive", ctx.read("alive", 0) + 1)
        return Step.cont()

    loom.add(FunctionLoop("boom", boom))
    loom.add(FunctionLoop("survivor", survivor))
    report = run(loom.run(max_ticks=3))
    assert report.errors == 1
    assert loom.blackboard.get("alive") == 3
    assert loom.status()["boom"] is Status.DONE


def test_spawn_during_run():
    loom = Loom(logger=lambda _l: None)

    async def parent(ctx):
        if ctx.tick == 0:
            async def child(c):
                c.post("child_ran", True)
                return Step.done()
            ctx.spawn(FunctionLoop("child", child))
        return Step.cont()

    loom.add(FunctionLoop("parent", parent))
    run(loom.run(max_ticks=3))
    assert loom.blackboard.get("child_ran") is True


def test_round_robin_runs_one_per_tick():
    loom = Loom(scheduler=RoundRobin(), logger=lambda _l: None)

    async def a(ctx):
        ctx.post("a", ctx.read("a", 0) + 1)
        return Step.cont()

    async def b(ctx):
        ctx.post("b", ctx.read("b", 0) + 1)
        return Step.cont()

    loom.add(FunctionLoop("a", a))
    loom.add(FunctionLoop("b", b))
    run(loom.run(max_ticks=4))
    # 4 ticks, alternating -> 2 each
    assert loom.blackboard.get("a") == 2
    assert loom.blackboard.get("b") == 2


def test_priority_top_k():
    loom = Loom(scheduler=Priority({"hi": 10, "lo": 1}, top_k=1), logger=lambda _l: None)

    async def hi(ctx):
        ctx.post("hi", ctx.read("hi", 0) + 1)
        return Step.cont()

    async def lo(ctx):
        ctx.post("lo", ctx.read("lo", 0) + 1)
        return Step.cont()

    loom.add(FunctionLoop("hi", hi))
    loom.add(FunctionLoop("lo", lo))
    run(loom.run(max_ticks=3))
    assert loom.blackboard.get("hi") == 3
    assert loom.blackboard.get("lo") is None


def test_duplicate_name_rejected():
    loom = Loom(logger=lambda _l: None)
    loom.add(FunctionLoop("x", lambda ctx: None))
    try:
        loom.add(FunctionLoop("x", lambda ctx: None))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on duplicate name")
