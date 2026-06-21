"""LoomLoop — coordinate many autonomous agents by weaving their nanoloops together.

The fundamental unit is the *nanoloop*: a minimal autonomous agent that does one
thing per ``step()`` (sense -> decide -> act -> observe). The *Loom* is the
coordinator that weaves many nanoloops together — ticking them on a schedule,
routing messages between them over a bus, and giving them a shared blackboard.

Quick start::

    import asyncio
    from loomloop import Loom, FunctionLoop, Step

    async def main():
        loom = Loom()

        async def pinger(ctx):
            ctx.send("ping", {"n": ctx.tick})
            return Step.cont()

        async def ponger(ctx):
            for msg in ctx.recv_all():
                ctx.log(f"got {msg.payload}")
            return Step.wait()

        loom.add(FunctionLoop("pinger", pinger))
        loom.add(FunctionLoop("ponger", ponger), subscribe=["ping"])
        await loom.run(max_ticks=3)

    asyncio.run(main())
"""

from .message import Message
from .bus import MessageBus
from .blackboard import Blackboard
from .nanoloop import NanoLoop, Context, Step, Status
from .scheduler import Scheduler, AllReady, RoundRobin, Priority
from .loom import Loom
from .agents import FunctionLoop, RelayLoop

__version__ = "0.1.0"

__all__ = [
    "Message",
    "MessageBus",
    "Blackboard",
    "NanoLoop",
    "Context",
    "Step",
    "Status",
    "Scheduler",
    "AllReady",
    "RoundRobin",
    "Priority",
    "Loom",
    "FunctionLoop",
    "RelayLoop",
]
