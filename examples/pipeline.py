"""A coordination pattern: a staged pipeline.

Three nanoloops are woven into an assembly line. ``source`` emits raw numbers,
``square`` transforms them, and ``collector`` accumulates results onto the shared
blackboard. Each stage only knows the topic it listens on and the topic it emits
— the Loom wires the data flow.

    python -m loomloop run examples/pipeline.py
"""

import asyncio

from loomloop import FunctionLoop, Loom, RelayLoop, Step


def build() -> Loom:
    loom = Loom()

    async def source(ctx):
        n = ctx.read("next", 0)
        if n >= 5:
            return Step.done()
        ctx.send("raw", n)
        ctx.post("next", n + 1)
        return Step.cont()

    async def collector(ctx):
        for msg in ctx.recv_all():
            ctx.post("sum", ctx.read("sum", 0) + msg.payload)
            ctx.log("collected", msg.payload, "running sum", ctx.read("sum"))
        return Step.wait()

    loom.add(FunctionLoop("source", source))
    # square stage: listen on "raw", emit squared values on "squared"
    loom.add(RelayLoop("square", listen="raw", emit="squared", transform=lambda x: x * x))
    loom.add(FunctionLoop("collector", collector), subscribe=["squared"])
    return loom


async def main():
    loom = build()
    report = await loom.run(max_ticks=50)
    print(report)
    print("sum of squares 0..4 =", loom.blackboard.get("sum"))


if __name__ == "__main__":
    asyncio.run(main())
