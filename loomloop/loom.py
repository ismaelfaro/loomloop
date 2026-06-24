"""The Loom: the coordinator that weaves nanoloops together.

The Loom owns the clock, the message bus, the blackboard, and the scheduler. Each
*tick* it asks the scheduler which ready agents to run, runs their ``step()``
concurrently, and applies the results. It stops when every agent is done, when
``max_ticks`` is hit, when an agent calls ``stop_loom()``, or when the system goes
quiescent (no agent can make progress and no mail is in flight).
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from .blackboard import Blackboard
from .bus import MessageBus
from .nanoloop import Context, NanoLoop, Status, Step
from .scheduler import AllReady, Scheduler

if TYPE_CHECKING:  # pragma: no cover
    from .oak import OakRepo


@dataclass
class AgentRecord:
    """The Loom's bookkeeping for one agent."""

    agent: NanoLoop
    status: Status = Status.CONTINUE
    wake_tick: int = 0          # earliest tick this agent may run again
    started: bool = False       # has setup() run yet?
    steps: int = 0
    branch: Optional[str] = None  # Oak session branch (branch-per-session)

    @property
    def is_done(self) -> bool:
        return self.status is Status.DONE


class Loom:
    def __init__(
        self,
        *,
        scheduler: Optional[Scheduler] = None,
        tick_interval: float = 0.0,
        logger: Optional[Callable[[str], None]] = None,
        workspace: Optional["OakRepo"] = None,
        branch_per_session: bool = False,
        snapshot: bool = False,
    ) -> None:
        self.bus = MessageBus()
        self.blackboard = Blackboard()
        self.scheduler = scheduler or AllReady()
        self.tick_interval = tick_interval
        self.tick = 0
        # Oak: the optional versioned substrate agents collaborate through.
        self.workspace = workspace
        self.branch_per_session = branch_per_session
        self.snapshot = snapshot
        self._records: Dict[str, AgentRecord] = {}
        self._pending_add: List[AgentRecord] = []
        self._stopped = False
        self._logger = logger or (lambda line: print(line))

    # -- composition ----------------------------------------------------
    def add(self, agent: NanoLoop, *, subscribe: Optional[List[str]] = None) -> NanoLoop:
        """Register an agent. Safe to call before or during a run."""
        if agent.name in self._records or any(r.agent.name == agent.name for r in self._pending_add):
            raise ValueError(f"duplicate agent name: {agent.name!r}")
        self.bus.register(agent.name)
        for topic in list(agent.subscriptions) + list(subscribe or []):
            self.bus.subscribe(agent.name, topic)
        record = AgentRecord(agent=agent)
        # Agents added mid-run join after the current tick settles.
        if self._running:
            self._pending_add.append(record)
        else:
            self._records[agent.name] = record
        return agent

    @property
    def _running(self) -> bool:
        return getattr(self, "_run_active", False)

    # -- control --------------------------------------------------------
    def stop(self) -> None:
        self._stopped = True

    def log(self, who: str, *parts: Any) -> None:
        self._logger(f"[t{self.tick:>3} {who}] " + " ".join(str(p) for p in parts))

    # -- readiness ------------------------------------------------------
    def _is_ready(self, rec: AgentRecord) -> bool:
        if rec.is_done:
            return False
        if rec.status is Status.WAIT:
            return self.bus.pending(rec.agent.name) > 0
        return self.tick >= rec.wake_tick

    def _has_future_work(self) -> bool:
        """True if anyone could still become ready on a later tick."""
        for rec in self._records.values():
            if rec.is_done:
                continue
            if rec.status is Status.CONTINUE and rec.wake_tick > self.tick:
                return True  # sleeping, will wake
        return False

    # -- the run loop ---------------------------------------------------
    async def run(self, *, max_ticks: Optional[int] = None) -> "RunReport":
        self._run_active = True
        self._stopped = False
        report = RunReport()
        try:
            while not self._stopped:
                if max_ticks is not None and self.tick >= max_ticks:
                    break

                await self._start_new_agents()

                ready = [r for r in self._records.values() if self._is_ready(r)]
                chosen = self.scheduler.select(ready, self.tick)

                if not chosen:
                    if self._has_future_work():
                        self.tick += 1
                        if self.tick_interval:
                            await asyncio.sleep(self.tick_interval)
                        continue
                    break  # quiescent: nobody can make progress

                await self._run_steps(chosen, report)
                report.ticks = self.tick + 1
                self.tick += 1
                if self.tick_interval:
                    await asyncio.sleep(self.tick_interval)
        finally:
            await self._teardown_all()
            self._run_active = False

        report.messages = self.bus.delivered
        report.blackboard = self.blackboard.snapshot()
        self._snapshot_run(report)
        return report

    def _snapshot_run(self, report: "RunReport") -> None:
        """Commit a manifest of this run into Oak — versioned run history."""
        if self.workspace is None or not self.snapshot:
            return
        manifest = {
            "ticks": report.ticks,
            "steps": report.steps,
            "messages": report.messages,
            "errors": report.errors,
            "agents": [r.agent.name for r in self._records.values()],
            "blackboard": report.blackboard,
        }
        path = "loomloop-run.json"
        try:
            with open(os.path.join(self.workspace.root, path), "w") as fh:
                json.dump(manifest, fh, indent=2, default=str)
            self.workspace.commit(
                paths=[path],
                description=(f"run: {report.steps} steps over {report.ticks} ticks "
                             f"({report.errors} errors)"),
            )
        except Exception as exc:  # snapshotting must never sink the run
            self.log("loom", f"oak snapshot ERROR: {exc!r}")

    async def _start_new_agents(self) -> None:
        # promote agents queued via ctx.spawn()/add() during a tick
        for rec in self._pending_add:
            self._records[rec.agent.name] = rec
        self._pending_add.clear()
        for rec in self._records.values():
            if not rec.started:
                rec.started = True
                self._open_session_branch(rec)
                await rec.agent.setup(Context(self, rec))

    def _open_session_branch(self, rec: AgentRecord) -> None:
        """Give a freshly-started agent its own Oak branch (branch-per-session)."""
        if self.workspace is None or not self.branch_per_session:
            return
        rec.branch = f"session/{rec.agent.name}"
        try:
            self.workspace.branch(rec.branch, description=f"session: {rec.agent.name}")
        except Exception as exc:  # an Oak hiccup shouldn't kill the loom
            self.log(rec.agent.name, f"oak branch ERROR: {exc!r}")

    async def _run_steps(self, chosen: List[AgentRecord], report: "RunReport") -> None:
        async def run_one(rec: AgentRecord) -> None:
            ctx = Context(self, rec)
            try:
                result = await rec.agent.step(ctx)
            except Exception as exc:  # an agent crashing shouldn't kill the loom
                self.log(rec.agent.name, f"ERROR: {exc!r}")
                report.errors += 1
                rec.status = Status.DONE
                return
            rec.steps += 1
            report.steps += 1
            self._apply(rec, result)

        await asyncio.gather(*(run_one(r) for r in chosen))

    def _apply(self, rec: AgentRecord, result: Step) -> None:
        rec.status = result.status
        if result.status is Status.CONTINUE:
            rec.wake_tick = self.tick + 1 + max(0, result.delay)

    async def _teardown_all(self) -> None:
        for rec in self._records.values():
            if rec.started:
                try:
                    await rec.agent.teardown(Context(self, rec))
                except Exception as exc:  # pragma: no cover - defensive
                    self.log(rec.agent.name, f"teardown ERROR: {exc!r}")

    # -- introspection --------------------------------------------------
    @property
    def agents(self) -> List[NanoLoop]:
        return [r.agent for r in self._records.values()]

    def status(self) -> Dict[str, Status]:
        return {name: r.status for name, r in self._records.items()}


@dataclass
class RunReport:
    """A summary of what happened during :meth:`Loom.run`."""

    ticks: int = 0
    steps: int = 0
    messages: int = 0
    errors: int = 0
    blackboard: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (f"RunReport(ticks={self.ticks}, steps={self.steps}, "
                f"messages={self.messages}, errors={self.errors})")
