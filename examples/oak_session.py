"""Branch-per-session collaboration over Oak (https://oak.space).

Two ``builder`` agents each work on their *own* Oak branch — the branch-per-
session unit of work — committing their output as they go. A ``coordinator``
hands out work, and on teardown each builder's branch is merged back into
``main``. The Loom also snapshots the whole run into a final Oak commit.

It runs fully **offline**: instead of spawning the real ``oak`` binary we inject
a :class:`RecordingRunner`, so every ``oak`` command is printed and recorded
rather than executed. Drop the ``runner=`` argument (and point ``root`` at a real
Oak checkout) to drive the actual binary.

    python -m loomloop run examples/oak_session.py
"""

import asyncio
import tempfile

from loomloop import (
    FunctionLoop,
    Loom,
    OakBranchLoop,
    OakRepo,
    RecordingRunner,
    Step,
)

WORK = ["parser", "lexer"]  # one unit of work per builder


def build() -> tuple[Loom, RecordingRunner]:
    # A fake runner: records/echoes `oak ...` calls instead of running them.
    runner = RecordingRunner(echo=True, responses={"branch": "main\n"})
    repo = OakRepo(tempfile.mkdtemp(prefix="oak-session-"), runner=runner)

    loom = Loom(
        workspace=repo,
        branch_per_session=True,  # each agent gets session/<name>
        snapshot=True,            # commit a run manifest at the end
    )

    async def coordinator(ctx):
        if ctx.tick == 0:
            for unit, who in zip(WORK, ("builder-0", "builder-1")):
                ctx.send("task", {"unit": unit}, to=who)
            return Step.cont()
        return Step.done()

    loom.add(FunctionLoop("coordinator", coordinator))
    for i in range(len(WORK)):
        loom.add(
            OakBranchLoop(
                f"builder-{i}",
                listen="task",
                emit="committed",
                merge_into="main",  # fold the session branch back on teardown
            )
        )
    return loom, runner


async def main():
    loom, runner = build()
    report = await loom.run(max_ticks=10)
    print(report)
    print(f"\n{len(runner.calls)} oak commands issued across the run.")


if __name__ == "__main__":
    asyncio.run(main())
