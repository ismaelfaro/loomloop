"""The nanoloop: the minimal autonomous agent, plus the context it runs in."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Optional

from .message import Message

if TYPE_CHECKING:  # pragma: no cover
    from .loom import Loom, AgentRecord
    from .oak import OakRepo, OakResult


class Status(enum.Enum):
    """What an agent wants the Loom to do with it after a step."""

    CONTINUE = "continue"  # schedule me again (optionally after a delay)
    WAIT = "wait"          # block me until a message lands in my inbox
    DONE = "done"          # I'm finished — retire me


@dataclass(frozen=True)
class Step:
    """The result a nanoloop returns from each ``step()``."""

    status: Status
    delay: int = 0  # CONTINUE only: extra ticks to skip before running again

    @classmethod
    def cont(cls, delay: int = 0) -> "Step":
        return cls(Status.CONTINUE, delay=delay)

    @classmethod
    def wait(cls) -> "Step":
        return cls(Status.WAIT)

    @classmethod
    def done(cls) -> "Step":
        return cls(Status.DONE)


class Context:
    """Everything a nanoloop touches the outside world through.

    A fresh Context is handed to the agent on each ``step()``. It exposes the
    current tick, the agent's inbox, the message bus, and the shared blackboard,
    plus convenience methods for the things agents do constantly: send, receive,
    log, spawn, and stop.
    """

    def __init__(self, loom: "Loom", record: "AgentRecord") -> None:
        self._loom = loom
        self._record = record

    # -- identity / clock ----------------------------------------------
    @property
    def name(self) -> str:
        return self._record.agent.name

    @property
    def tick(self) -> int:
        return self._loom.tick

    @property
    def loom(self) -> "Loom":
        return self._loom

    @property
    def blackboard(self):
        return self._loom.blackboard

    # -- receiving ------------------------------------------------------
    @property
    def inbox_size(self) -> int:
        return self._loom.bus.pending(self.name)

    def recv(self) -> Optional[Message]:
        """Pop the oldest message, or ``None`` if the inbox is empty."""
        box = self._loom.bus.inbox(self.name)
        return box.popleft() if box else None

    def recv_all(self) -> List[Message]:
        """Drain and return every queued message (oldest first)."""
        box = self._loom.bus.inbox(self.name)
        msgs = list(box)
        box.clear()
        return msgs

    # -- sending --------------------------------------------------------
    def send(self, topic: str, payload: Any, *, to: Optional[str] = None) -> int:
        """Publish a message. ``to`` addresses one agent; otherwise fan out by topic."""
        msg = Message(topic=topic, payload=payload, sender=self.name,
                      recipient=to, tick=self.tick)
        return self._loom.bus.publish(msg)

    def reply(self, msg: Message, payload: Any, *, topic: Optional[str] = None) -> int:
        out = Message(topic=topic or msg.topic, payload=payload,
                      sender=self.name, recipient=msg.sender, tick=self.tick)
        return self._loom.bus.publish(out)

    # -- shared state ---------------------------------------------------
    def post(self, key: str, value: Any) -> int:
        return self._loom.blackboard.set(key, value, who=self.name)

    def read(self, key: str, default: Any = None) -> Any:
        return self._loom.blackboard.get(key, default)

    # -- versioned workspace (Oak) -------------------------------------
    @property
    def workspace(self) -> Optional["OakRepo"]:
        """The Loom's Oak repository, or ``None`` if no workspace is configured.

        Lets a nanoloop read/write/branch the shared substrate directly::

            if ctx.workspace:
                ctx.workspace.status()
        """
        return self._loom.workspace

    @property
    def branch(self) -> Optional[str]:
        """This agent's session branch (branch-per-session), or ``None``."""
        return self._record.branch

    def commit(self, description: str, paths: Optional[List[str]] = None) -> "OakResult":
        """Version this agent's work onto its session branch.

        Switches to the agent's branch (if it has one) and commits. Raises a
        clear error when no Oak workspace is configured, so the dependency stays
        opt-in for agents that never touch it.
        """
        repo = self._loom.workspace
        if repo is None:
            raise RuntimeError(
                "ctx.commit() needs an Oak workspace: "
                "Loom(workspace=OakRepo(...))"
            )
        if self._record.branch:
            repo.switch(self._record.branch)
        return repo.commit(paths=paths, description=description)

    # -- lifecycle / orchestration -------------------------------------
    def subscribe(self, topic: str) -> None:
        self._loom.bus.subscribe(self.name, topic)

    def spawn(self, agent: "NanoLoop", *, subscribe: Optional[List[str]] = None) -> None:
        """Add a new agent to the running loom (it starts on the next tick)."""
        self._loom.add(agent, subscribe=subscribe)

    def stop_self(self) -> None:
        self._record.status = Status.DONE

    def stop_loom(self) -> None:
        self._loom.stop()

    def log(self, *parts: Any) -> None:
        self._loom.log(self.name, *parts)


class NanoLoop:
    """Base class for an agent. Subclass and implement :meth:`step`.

    Override ``subscriptions`` (or pass ``subscribe=`` to :meth:`Loom.add`) to
    receive messages on those topics. ``setup`` / ``teardown`` are optional hooks
    run once when the agent joins and leaves the loom.
    """

    subscriptions: List[str] = []

    def __init__(self, name: str) -> None:
        self.name = name

    async def setup(self, ctx: Context) -> None:  # noqa: D401 - hook
        """Run once before the agent's first step."""

    async def step(self, ctx: Context) -> Step:
        raise NotImplementedError("a nanoloop must implement step()")

    async def teardown(self, ctx: Context) -> None:  # noqa: D401 - hook
        """Run once after the agent is retired."""

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{type(self).__name__} {self.name!r}>"
