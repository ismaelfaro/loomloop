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
Python functions, classes, or **model-backed** for genuinely autonomous
decision-making. LoomLoop is **provider-agnostic**: a brain agent talks to a
pluggable `Backend`, so the same system runs offline (a mock), on Claude, or on
any model you wrap — swap the backend, not the agents.

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

The same agents, written with the `@nanoloop` decorator — the function *is* the
loop:

```python
from loomloop import nanoloop, Loom, Step

@nanoloop
async def pinger(ctx):
    ctx.send("ping", {"n": ctx.tick})
    return Step.cont()

@nanoloop(subscribe=["ping"])
async def ponger(ctx):
    for msg in ctx.recv_all():
        ctx.log("got", msg.payload)
    return Step.wait()

loom = Loom()
loom.add(pinger)
loom.add(ponger)
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
| **`Backend`** | A pluggable model for `BrainLoop`: `EchoBackend`, `CallableBackend`, `ClaudeBackend`, or your own. Keeps LoomLoop provider-agnostic. |
| **`OakRepo`** | Optional versioned substrate ([Oak](https://oak.space)): give each agent its own branch, commit work, snapshot runs. Degrades gracefully when `oak` isn't installed. |

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
- **`examples/brains.py`** — two model-backed agents (`planner` → `critic`) wired
  to a pluggable backend. Runs offline by default; set `LOOMLOOP_BACKEND=claude`
  to use a real model.
- **`examples/oak_session.py`** — branch-per-session collaboration over
  [Oak](https://oak.space): each agent works on its own branch, commits as it
  goes, and merges back. Runs offline (a recording runner prints the `oak`
  commands instead of executing them).

### Model-agnostic brain agents

`BrainLoop` makes an agent's decision a model call instead of a hand-written rule
— but it talks only to a `Backend`, so it's not tied to any provider:

```python
from loomloop import Loom, BrainLoop, EchoBackend, ClaudeBackend

backend = EchoBackend()          # offline/test: deterministic, no deps
# backend = ClaudeBackend()      # real autonomy: needs pip install ".[llm]" + ANTHROPIC_API_KEY

loom = Loom()
loom.add(BrainLoop(
    "researcher",
    backend=backend,
    system="Break a goal into 3 concrete sub-tasks. Reply as a numbered list.",
    listen=["goals"],
    emit="tasks",
))
loom.add(BrainLoop(
    "critic",
    backend=backend,
    system="Review a task list and flag the riskiest item in one sentence.",
    listen=["tasks"],
))
```

Built-in backends: `EchoBackend` (deterministic, no deps), `CallableBackend`
(wrap any `fn(prompt) -> str`), and `ClaudeBackend` (Claude Opus 4.8 with
adaptive thinking, async client). Roll your own by implementing one method:

```python
class MyBackend:
    async def generate(self, prompt, *, system="", history=None) -> str:
        ...
```

### Versioned workspace with Oak

Where the blackboard is in-memory shared state, [Oak](https://oak.space) is a
content-addressed VCS *built for agents* whose unit of work is
**branch-per-session**. Hand a `Loom` an `OakRepo` and every agent gets its own
branch to commit work onto — exactly how Oak is meant to be driven — while the
Loom coordinates merges and can snapshot the whole run into a commit:

```python
from loomloop import Loom, OakRepo, OakBranchLoop

repo = OakRepo("./workspace")     # thin wrapper over the `oak` CLI
loom = Loom(
    workspace=repo,
    branch_per_session=True,       # each agent → session/<name>
    snapshot=True,                 # commit a run manifest at the end
)

# Any agent can now reach Oak through its Context:
async def builder(ctx):
    # ... do work, write files under repo.root ...
    ctx.commit("built the parser")   # commits onto ctx.branch (session/builder)
    return Step.done()

# ...or use the turnkey agent that versions each message it receives:
loom.add(OakBranchLoop("builder", listen="task", merge_into="main"))
```

Oak's engine is Rust (the [`oak`](https://oak.space/install) binary), so the
adapter shells out to it. It's fully **optional**: nothing imports Oak until you
use it, `OakRepo.available()` checks for the binary, and a Loom with no
`workspace` behaves exactly as before. For tests and offline demos, inject a
`RecordingRunner` to capture the `oak` commands instead of running them.

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
  backend.py     # Backend protocol + Echo / Callable / Claude backends
  oak.py         # OakRepo — optional versioned substrate (Oak, agent-native VCS)
  agents/        # FunctionLoop, RelayLoop, @nanoloop, BrainLoop, OakBranchLoop
  cli.py         # python -m loomloop ...
examples/        # pipeline + swarm + brains + oak_session
tests/           # pytest suite
```

## License

MIT
