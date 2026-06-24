"""Oak — give LoomLoop agents a real, versioned substrate to collaborate through.

`Oak <https://oak.space>`_ is a content-addressed VCS built *for agents*, whose
organizing idea is **branch-per-session as the unit of work**: agents read,
write, branch, and collaborate through a repository, using branch *descriptions*
in place of per-commit messages. That lines up exactly with what a Loom does —
coordinate many autonomous agents — so Oak slots in as the shared workspace
those agents commit their work to.

Oak's engine is Rust (the ``oak`` CLI / ``oakvcs-core`` crate). The practical
Python integration is to shell out to the ``oak`` binary, so this adapter is a
thin, dependency-injected wrapper around it — kept **optional** and
**gracefully degrading**, mirroring :class:`loomloop.backend.ClaudeBackend`:

* nothing here imports or requires ``oak`` until you actually call it;
* :meth:`OakRepo.available` lets callers check before they commit to a path;
* a missing binary (or any non-zero exit) raises a clear :class:`OakError`.

Every ``oak`` command string lives in exactly one place — the small ``_cmd``
table consumed by :meth:`OakRepo._run`. That's the single spot to reconcile
against ``oak --help`` once a real binary is in hand; nothing else in the
codebase hard-codes a flag.

Wire it into a Loom and hand each agent its own branch::

    from loomloop import Loom, OakRepo

    repo = OakRepo("./workspace")          # wraps the `oak` binary
    loom = Loom(workspace=repo, branch_per_session=True, snapshot=True)
    # each agent now gets ctx.workspace + ctx.branch; ctx.commit(...) versions
    # its work onto that branch, and the run is snapshotted at the end.

For tests and offline demos, inject a ``runner`` that records commands instead
of spawning a process — see :class:`RecordingRunner`.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence


class OakError(RuntimeError):
    """Raised when an ``oak`` invocation fails or the binary is missing."""


@dataclass
class OakResult:
    """The outcome of one ``oak`` invocation (a subset of ``CompletedProcess``)."""

    args: List[str]
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


# A runner turns a fully-formed argv (``["oak", "branch", ...]``) into a result.
# Injecting one is how callers swap the real subprocess for a fake (tests/demos).
Runner = Callable[[List[str]], OakResult]


@dataclass
class RecordingRunner:
    """A fake :data:`Runner` that records commands instead of running them.

    Use it to drive an Oak-backed Loom offline — every ``oak`` call is captured
    in :attr:`calls` (as argv lists) and returns canned output. Optional
    ``responses`` maps a subcommand (the first arg after ``oak``) to stdout, so
    things like ``current_branch`` can return something sensible.
    """

    calls: List[List[str]] = field(default_factory=list)
    responses: dict = field(default_factory=dict)
    echo: bool = False

    def __call__(self, args: List[str]) -> OakResult:
        self.calls.append(list(args))
        if self.echo:
            print("$ " + " ".join(args))
        sub = args[1] if len(args) > 1 else ""
        return OakResult(args=list(args), returncode=0,
                         stdout=self.responses.get(sub, ""))


def _subprocess_runner(root: str, bin: str) -> Runner:
    """The default runner: actually spawn ``oak`` in ``root``."""

    def run(args: List[str]) -> OakResult:
        if shutil.which(bin) is None:
            raise OakError(
                f"the {bin!r} binary is not installed or not on PATH. "
                "Install Oak (https://oak.space/install) or pass a runner=."
            )
        proc = subprocess.run(args, cwd=root, capture_output=True, text=True)
        return OakResult(args=list(args), returncode=proc.returncode,
                         stdout=proc.stdout, stderr=proc.stderr)

    return run


class OakRepo:
    """A thin, optional wrapper around the ``oak`` CLI for one repository.

    Parameters
    ----------
    root:
        Working directory the ``oak`` commands run in (the repo checkout).
    bin:
        Name/path of the Oak binary (default ``"oak"``).
    runner:
        Inject a callable ``(argv) -> OakResult`` to bypass the real process —
        the testing/offline seam, analogous to ``ClaudeBackend(client=...)``.
    """

    # The one place command strings live. Reconcile with `oak --help` here and
    # nowhere else. Each entry maps a method to its ``oak`` subcommand argv head.
    _cmd = {
        "init": ["init"],
        "clone": ["clone"],
        "branch": ["branch"],
        "switch": ["switch"],
        "commit": ["commit"],
        "merge": ["merge"],
        "push": ["push"],
        "pull": ["pull"],
        "mount": ["mount"],
        "status": ["status"],
        "log": ["log"],
        "current_branch": ["branch", "--show-current"],
    }

    def __init__(self, root: str = ".", *, bin: str = "oak",
                 runner: Optional[Runner] = None) -> None:
        self.root = root
        self.bin = bin
        self._runner = runner or _subprocess_runner(root, bin)

    # -- availability ---------------------------------------------------
    @staticmethod
    def available(bin: str = "oak") -> bool:
        """True if the ``oak`` binary is on PATH (cheap pre-flight check)."""
        return shutil.which(bin) is not None

    # -- the single funnel ----------------------------------------------
    def _run(self, key: str, *extra: str) -> OakResult:
        """Run one ``oak`` subcommand; raise :class:`OakError` on failure."""
        argv = [self.bin] + self._cmd[key] + [a for a in extra if a is not None]
        result = self._runner(argv)
        if result.returncode != 0:
            raise OakError(
                f"`{' '.join(argv)}` failed ({result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    # -- repository lifecycle -------------------------------------------
    def init(self) -> OakResult:
        return self._run("init")

    def clone(self, url: str) -> OakResult:
        return self._run("clone", url)

    # -- branches (branch-per-session; description in place of messages) -
    def branch(self, name: str, description: str = "") -> OakResult:
        """Create ``name``. Oak carries the *session description* on the branch."""
        extra = [name]
        if description:
            extra += ["--description", description]
        return self._run("branch", *extra)

    def switch(self, name: str) -> OakResult:
        return self._run("switch", name)

    def current_branch(self) -> str:
        return self._run("current_branch").stdout.strip()

    def merge(self, branch: str, into: Optional[str] = None) -> OakResult:
        if into is not None:
            self.switch(into)
        return self._run("merge", branch)

    # -- changes --------------------------------------------------------
    def commit(self, paths: Optional[Sequence[str]] = None,
               description: str = "") -> OakResult:
        """Commit ``paths`` (or everything). ``description`` annotates the commit."""
        extra: List[str] = []
        if description:
            extra += ["--description", description]
        if paths:
            extra += list(paths)
        return self._run("commit", *extra)

    # -- sync / mount / introspection -----------------------------------
    def push(self) -> OakResult:
        return self._run("push")

    def pull(self) -> OakResult:
        return self._run("pull")

    def mount(self, path: str) -> OakResult:
        return self._run("mount", path)

    def status(self) -> str:
        return self._run("status").stdout

    def log(self) -> str:
        return self._run("log").stdout

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<OakRepo root={self.root!r} bin={self.bin!r}>"


__all__ = ["OakRepo", "OakError", "OakResult", "Runner", "RecordingRunner"]
