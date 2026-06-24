"""A nanoloop that versions its work onto an Oak branch.

:class:`OakBranchLoop` is the turnkey "agent as a session" — it owns the
lifecycle of one Oak branch so that plain nanoloops stay Oak-unaware. It listens
on a topic; for every message it receives it writes the payload to a file and
commits it onto its own branch (branch-per-session). On teardown it can merge
that branch back and/or push.

It leans on the Loom's workspace (``ctx.workspace``) and the branch the Loom
assigned it (``ctx.branch``), so the same agent is a no-op-with-a-warning when no
Oak workspace is configured — never a hard failure.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, List, Optional

from ..nanoloop import Context, NanoLoop, Step


def _default_render(payload: Any) -> str:
    """Serialize a message payload to file contents (JSON, falling back to str)."""
    try:
        return json.dumps(payload, indent=2, default=str)
    except TypeError:  # pragma: no cover - defensive
        return str(payload)


class OakBranchLoop(NanoLoop):
    """Commit every inbound message onto this agent's Oak session branch.

    Parameters
    ----------
    name:
        Agent name (also the basis for its ``session/<name>`` branch).
    listen:
        Topic to subscribe to. Each received message becomes a commit.
    path:
        File (relative to the repo root) the payload is written to before each
        commit. Defaults to ``"<name>.json"``.
    render:
        ``payload -> str`` serializer for the file contents (default JSON).
    emit:
        Optional topic to announce each commit on (payload: the description).
    merge_into:
        On teardown, merge this agent's branch into the given branch.
    push:
        On teardown, ``oak push`` after any merge.
    """

    def __init__(
        self,
        name: str,
        *,
        listen: str,
        path: Optional[str] = None,
        render: Optional[Callable[[Any], str]] = None,
        emit: Optional[str] = None,
        merge_into: Optional[str] = None,
        push: bool = False,
    ) -> None:
        super().__init__(name)
        self.subscriptions = [listen]
        self._path = path or f"{name}.json"
        self._render = render or _default_render
        self._emit = emit
        self._merge_into = merge_into
        self._push = push
        self._commits = 0

    async def step(self, ctx: Context) -> Step:
        repo = ctx.workspace
        if repo is None:
            ctx.log("no Oak workspace configured; dropping messages")
            ctx.recv_all()
            return Step.wait()

        for msg in ctx.recv_all():
            file_path = os.path.join(repo.root, self._path)
            with open(file_path, "w") as fh:
                fh.write(self._render(msg.payload))
            description = f"{self.name}: {msg.topic} @ t{msg.tick}"
            ctx.commit(description, paths=[self._path])
            self._commits += 1
            ctx.post(f"{self.name}.commits", self._commits)
            if self._emit:
                ctx.send(self._emit, {"branch": ctx.branch, "description": description})
        return Step.wait()

    async def teardown(self, ctx: Context) -> None:
        repo = ctx.workspace
        if repo is None or ctx.branch is None:
            return
        try:
            if self._merge_into:
                repo.merge(ctx.branch, into=self._merge_into)
            if self._push:
                repo.push()
        except Exception as exc:  # teardown must stay quiet about Oak hiccups
            ctx.log(f"oak teardown ERROR: {exc!r}")


__all__ = ["OakBranchLoop"]
