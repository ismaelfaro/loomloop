"""A small CLI for poking at LoomLoop without writing a script.

    python -m loomloop demo          # run the built-in ping/pong demo
    python -m loomloop demo --ticks 5
    python -m loomloop run examples/pipeline.py   # run an example module's main()
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

from . import FunctionLoop, Loom, Step


async def _demo(ticks: int) -> None:
    loom = Loom()

    async def pinger(ctx):
        ctx.send("ping", {"n": ctx.tick})
        return Step.cont()

    async def ponger(ctx):
        for msg in ctx.recv_all():
            ctx.post("last", msg.payload["n"])
            ctx.log("pong for", msg.payload)
        return Step.wait()

    loom.add(FunctionLoop("pinger", pinger))
    loom.add(FunctionLoop("ponger", ponger), subscribe=["ping"])
    report = await loom.run(max_ticks=ticks)
    print(report)


def _run_module(path: str) -> None:
    file = Path(path)
    if not file.exists():
        sys.exit(f"no such file: {path}")
    spec = importlib.util.spec_from_file_location(file.stem, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    main = getattr(module, "main", None)
    if main is None:
        sys.exit(f"{path} has no main()")
    result = main()
    if asyncio.iscoroutine(result):
        asyncio.run(result)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="loomloop", description="Weave autonomous agent loops.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="run the built-in ping/pong demo")
    d.add_argument("--ticks", type=int, default=3)

    r = sub.add_parser("run", help="run main() from a Python file")
    r.add_argument("path")

    args = parser.parse_args(argv)
    if args.cmd == "demo":
        asyncio.run(_demo(args.ticks))
    elif args.cmd == "run":
        _run_module(args.path)


if __name__ == "__main__":  # pragma: no cover
    main()
