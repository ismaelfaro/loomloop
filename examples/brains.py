"""A coordination pattern: a model-agnostic agent collective.

Two brain nanoloops collaborate — a ``planner`` turns a goal into sub-tasks and a
``critic`` flags the riskiest one. Because LoomLoop talks to a pluggable
``Backend``, the *same* wiring runs offline (EchoBackend) or on a real model
(ClaudeBackend) — only the backend changes.

    python -m loomloop run examples/brains.py            # offline, deterministic
    LOOMLOOP_BACKEND=claude python -m loomloop run examples/brains.py  # uses Claude
"""

import asyncio
import os

from loomloop import BrainLoop, ClaudeBackend, EchoBackend, FunctionLoop, Loom, Step


def pick_backend():
    """Choose a backend from the environment, defaulting to the offline one."""
    if os.environ.get("LOOMLOOP_BACKEND") == "claude":
        # Claude Opus 4.8 with adaptive thinking; needs anthropic + ANTHROPIC_API_KEY
        return ClaudeBackend()
    # Deterministic stand-in so the demo runs with no keys or network.
    return EchoBackend(lambda p: f"[plan for: {p}] 1) scope 2) build 3) ship")


def build() -> Loom:
    loom = Loom()
    backend = pick_backend()

    async def kickoff(ctx):
        ctx.send("goals", "launch a coordinated multi-agent demo")
        return Step.done()

    loom.add(FunctionLoop("kickoff", kickoff))
    loom.add(BrainLoop(
        "planner",
        backend=backend,
        system="Break the goal into 3 concrete sub-tasks. Reply as a numbered list.",
        listen="goals",
        emit="tasks",
    ))
    loom.add(BrainLoop(
        "critic",
        backend=backend,
        system="Given a task list, name the single riskiest item in one sentence.",
        listen="tasks",
        emit="review",
    ))

    async def report(ctx):
        for msg in ctx.recv_all():
            ctx.post("review", msg.payload)
            ctx.log("review:", msg.payload)
        return Step.wait()

    loom.add(FunctionLoop("report", report), subscribe=["review"])
    return loom


async def main():
    loom = build()
    report = await loom.run(max_ticks=20)
    print(report)
    print("final review:", loom.blackboard.get("review"))


if __name__ == "__main__":
    asyncio.run(main())
