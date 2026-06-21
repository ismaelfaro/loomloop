"""Schedulers decide *which* of the ready agents actually run on a given tick.

The Loom computes the set of agents that *could* run (active, awake, and — if
waiting — holding mail). The scheduler then chooses, from that set, who runs this
tick and in what order. Swapping the scheduler changes the coordination dynamics
without touching any agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict, List

if TYPE_CHECKING:  # pragma: no cover
    from .loom import AgentRecord


class Scheduler:
    def select(self, ready: List["AgentRecord"], tick: int) -> List["AgentRecord"]:
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{type(self).__name__}>"


class AllReady(Scheduler):
    """Run every ready agent each tick (maximum concurrency). The default."""

    def select(self, ready: List["AgentRecord"], tick: int) -> List["AgentRecord"]:
        return ready


class RoundRobin(Scheduler):
    """Run one agent per tick, cycling fairly through the ready set."""

    def __init__(self) -> None:
        self._cursor = 0

    def select(self, ready: List["AgentRecord"], tick: int) -> List["AgentRecord"]:
        if not ready:
            return []
        pick = ready[self._cursor % len(ready)]
        self._cursor += 1
        return [pick]


class Priority(Scheduler):
    """Order ready agents by a per-agent priority (higher runs first).

    ``key`` maps an agent name to a number; unknown agents default to ``0``.
    With ``top_k`` set, only the highest-priority ``k`` agents run each tick.
    """

    def __init__(self, key: Dict[str, float] | Callable[[str], float], top_k: int | None = None) -> None:
        self._key = key
        self._top_k = top_k

    def _priority(self, name: str) -> float:
        if callable(self._key):
            return self._key(name)
        return self._key.get(name, 0.0)

    def select(self, ready: List["AgentRecord"], tick: int) -> List["AgentRecord"]:
        ordered = sorted(ready, key=lambda r: self._priority(r.agent.name), reverse=True)
        return ordered if self._top_k is None else ordered[: self._top_k]
