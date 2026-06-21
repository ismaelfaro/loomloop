"""The unit of communication between nanoloops."""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Optional

_ids = itertools.count(1)


@dataclass(frozen=True)
class Message:
    """A single message exchanged over the :class:`MessageBus`.

    A message is addressed either to a *topic* (fan-out to every subscriber) or
    to a single *recipient* (direct delivery). ``payload`` is arbitrary — keep it
    serializable if you ever want to persist or ship a run across the wire.
    """

    topic: str
    payload: Any
    sender: str = "?"
    recipient: Optional[str] = None
    tick: int = -1
    id: int = field(default_factory=lambda: next(_ids))
    ts: float = field(default_factory=time.time)

    def reply(self, payload: Any, *, topic: Optional[str] = None) -> "Message":
        """Build a message addressed back to this message's sender."""
        return Message(
            topic=topic or self.topic,
            payload=payload,
            recipient=self.sender,
        )
