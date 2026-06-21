# LoomLoop

**Coordinate many autonomous agents by weaving their *nanoloops* together.**

The fundamental idea: every autonomous agent is a *loop* — sense → decide → act →
observe → repeat. A **nanoloop** is the tiniest possible version of that: an agent
that does exactly one thing per `step()`. On its own a nanoloop is just a tick.

**LoomLoop is the loom that weaves nanoloops into a system.** It drives them on a
shared clock, routes messages between them over a bus, gives them a common
blackboard to collaborate through, and lets a scheduler decide who runs when —
so a handful of tiny, single-purpose loops become a coordinated collective.

```
   nanoloop      nanoloop      nanoloop          each agent = one minimal loop
      │             │             │
      └──────┬──────┴──────┬──────┘
             ▼             ▼
         message bus   blackboard               shared communication + memory
             └──────┬──────┘
                    ▼
                  Loom                            ticks, schedules, weaves
```

No heavy dependencies — the core is pure-stdlib `asyncio`. Agents can be plain
Python functions, classes, or **Claude-backed** (optional) for genuinely
autonomous decision-making.

---

## Install

```bash
pip install -e .            # core (pure stdlib)
pip install -e ".[llm]"     # + Claude-backed agents (anthropic SDK)
pip install -e ".[dev]"     # + pytest
```

## 60-second tour

```python
import asyncio
from loomloop import Loom, FunctionLoop, Step

async def main():
    loom = Loom()

    async def pinger(ctx):
        ctx.send("ping", {"n": ctx.tick})      # publish on a topic
        return Step.cont()                      # run me again next tick

    async def ponger(ctx):
        for msg in ctx.recv_all():              # drain my inbox
            ctx.log("got", msg.payload)
        return Step.wait()                       # sleep until more mail arrives

    loom.add(FunctionLoop("pinger", pinger))
    loom.add(FunctionLoop("ponger", ponger), subscribe=["ping"])
    await loom.run(max_ticks=3)

asyncio.run(main())
```

Or from the CLI:

```bash
python -m loomloop demo                  # built-in ping/pong
python -m loomloop run examples/swarm.py # worker swarm pulling a shared queue
```

## Core concepts

| Concept | What it is |
|---|---|
| **`NanoLoop`** | An agent. Implement `async step(ctx) -> Step`. Optional `setup`/`teardown` hooks. |
| **`Step`** | What a step returns: `Step.cont(delay=0)` (run again), `Step.wait()` (block on inbox), `Step.done()` (retire). |
| **`Context`** | The agent's window on the world: `send` / `recv_all` / `post` / `read` / `spawn` / `log` / `stop_self`. |
| **`Loom`** | The coordinator. Owns the clock, bus, blackboard, and scheduler; runs the tick loop. |
| **`MessageBus`** | In-process pub/sub. Topic fan-out, or direct addressing with `to=`. |
| **`Blackboard`** | Shared, versioned key/value workspace with an audit trail. |
| **`Scheduler`** | Decides which ready agents run each tick: `AllReady` (default), `RoundRobin`, `Priority`. |

### How a tick works

1. The Loom computes which agents are **ready** (active, awake, and — if waiting —
   holding mail).
2. The **scheduler** picks who runs this tick, and in what order.
3. Their `step()` coroutines run, and each returns a `Step` telling the Loom what
   to do next.
4. The run ends when every agent is `done`, `max_ticks` is hit, an agent calls
   `stop_loom()`, or the system goes **quiescent** (nobody can make progress and
   no messages are in flight).

Because a `step()` has no `await` mid-way, all of a tick's steps are effectively
atomic with respect to each other — two workers pulling from a shared queue never
grab the same item (see `examples/swarm.py`).

## Three coordination patterns, three example files

- **`examples/pipeline.py`** — a staged assembly line (`source → square → collector`)
  wired purely by topic names.
- **`examples/swarm.py`** — N interchangeable workers pulling from one shared
  blackboard queue, with a supervisor that ends the run.
- **Claude-backed agents** — drop in `LLMLoop` to make an agent's decision a Claude
  completion instead of a hand-written rule:

```python
from loomloop import Loom
from loomloop.agents.llm import LLMLoop   # needs: pip install -e ".[llm]"

loom = Loom()
loom.add(LLMLoop(
    "researcher",
    system="You break a goal into 3 concrete sub-tasks. Reply as a numbered list.",
    listen=["goals"],
    emit="tasks",
))
loom.add(LLMLoop(
    "critic",
    system="You review a task list and flag the riskiest item in one sentence.",
    listen=["tasks"],
))
```

`LLMLoop` uses **Claude Opus 4.8** with adaptive thinking by default and an async
client, so a slow model call on one agent doesn't stall the others on the tick.
Set `ANTHROPIC_API_KEY` in your environment.

## Run the tests

```bash
python -m pytest
```

## Project layout

```
loomloop/
  nanoloop.py    # NanoLoop, Context, Step, Status — the agent contract
  loom.py        # Loom (the coordinator) + RunReport
  bus.py         # MessageBus (pub/sub)
  blackboard.py  # Blackboard (shared versioned state)
  scheduler.py   # AllReady / RoundRobin / Priority
  agents/        # FunctionLoop, RelayLoop, and the optional Claude-backed LLMLoop
  cli.py         # python -m loomloop ...
examples/        # pipeline + swarm
tests/           # pytest suite
```

## License

MIT
