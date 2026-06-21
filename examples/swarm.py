"""A coordination pattern: a worker swarm pulling from a shared queue.

A ``dispatcher`` fills a work queue on the shared blackboard. Several identical
``worker`` nanoloops pull tasks off it — because the Loom runs each tick's steps
atomically (a step has no ``await`` mid-way), two workers never grab the same
task. A ``monitor`` watches progress and stops the loom when the queue drains.

This shows the blackboard used as a coordination surface (a shared queue + a
results ledger) and a supervisory agent that ends the run.

    python -m loomloop run examples/swarm.py
"""

import asyncio

from loomloop import FunctionLoop, Loom, NanoLoop, Step

NUM_TASKS = 9
NUM_WORKERS = 3


def build() -> Loom:
    loom = Loom()

    async def dispatcher(ctx):
        ctx.post("queue", list(range(NUM_TASKS)))
        ctx.log(f"queued {NUM_TASKS} tasks")
        return Step.done()

    class Worker(NanoLoop):
        async def step(self, ctx):
            queue = ctx.read("queue")
            if not queue:
                return Step.cont()  # nothing right now; check again next tick
            task = queue[0]
            ctx.post("queue", queue[1:])  # claim by popping
            done = ctx.read("done", [])
            ctx.post("done", done + [(self.name, task)])
            ctx.log(f"handled task {task}")
            return Step.cont()

    async def monitor(ctx):
        if ctx.read("queue") == [] and len(ctx.read("done", [])) >= NUM_TASKS:
            ctx.log("all tasks complete:", sorted(t for _, t in ctx.read("done")))
            ctx.stop_loom()
            return Step.done()
        return Step.cont()

    loom.add(FunctionLoop("dispatcher", dispatcher))
    for w in range(NUM_WORKERS):
        loom.add(Worker(f"worker-{w}"))
    loom.add(FunctionLoop("monitor", monitor))
    return loom


async def main():
    loom = build()
    report = await loom.run(max_ticks=100)
    print(report)
    by_worker: dict[str, int] = {}
    for who, _ in loom.blackboard.get("done", []):
        by_worker[who] = by_worker.get(who, 0) + 1
    print("tasks per worker:", by_worker)


if __name__ == "__main__":
    asyncio.run(main())
