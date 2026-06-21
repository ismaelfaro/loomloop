"""A tiny in-process publish/subscribe message bus.

Delivery is synchronous: :meth:`publish` drops the message straight into the
recipients' inboxes. The Loom drains those inboxes when it ticks each agent, so
ordering is deterministic and easy to reason about in tests.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Deque, Dict, List, Set

from .message import Message


class MessageBus:
    def __init__(self) -> None:
        self._inboxes: Dict[str, Deque[Message]] = {}
        self._topics: Dict[str, Set[str]] = defaultdict(set)
        self.delivered = 0

    # -- registration ---------------------------------------------------
    def register(self, name: str) -> None:
        """Give ``name`` an inbox. Idempotent."""
        self._inboxes.setdefault(name, deque())

    def subscribe(self, name: str, topic: str) -> None:
        self.register(name)
        self._topics[topic].add(name)

    def unsubscribe(self, name: str, topic: str) -> None:
        self._topics.get(topic, set()).discard(name)

    def remove(self, name: str) -> None:
        """Drop an agent entirely (inbox + every subscription)."""
        self._inboxes.pop(name, None)
        for subs in self._topics.values():
            subs.discard(name)

    # -- traffic --------------------------------------------------------
    def publish(self, msg: Message) -> int:
        """Deliver ``msg`` and return the number of inboxes it reached.

        A message with a ``recipient`` is delivered only to that inbox. Otherwise
        it fans out to every subscriber of its topic, excluding the sender.
        """
        targets: List[str]
        if msg.recipient is not None:
            targets = [msg.recipient] if msg.recipient in self._inboxes else []
        else:
            targets = [s for s in self._topics.get(msg.topic, ()) if s != msg.sender]

        for name in targets:
            self._inboxes[name].append(msg)
        self.delivered += len(targets)
        return len(targets)

    # -- inbox access ---------------------------------------------------
    def inbox(self, name: str) -> Deque[Message]:
        return self._inboxes.setdefault(name, deque())

    def pending(self, name: str) -> int:
        return len(self._inboxes.get(name, ()))

    def total_pending(self) -> int:
        return sum(len(q) for q in self._inboxes.values())
