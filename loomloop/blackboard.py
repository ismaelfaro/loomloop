"""A shared key/value workspace that every nanoloop can read and write.

The blackboard is the classic coordination pattern for cooperating agents: a
common surface where one agent posts a partial result and another picks it up.
Every write bumps a global ``version`` so agents can cheaply detect change
("has anything I care about moved since I last looked?") without polling values.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple


class Blackboard:
    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}
        self._version = 0
        self._history: List[Tuple[int, str, str, Any]] = []  # (version, who, key, value)
        self._lock = threading.Lock()

    @property
    def version(self) -> int:
        return self._version

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def set(self, key: str, value: Any, *, who: str = "?") -> int:
        """Write a value, recording who did it. Returns the new version."""
        with self._lock:
            self._version += 1
            self._data[key] = value
            self._history.append((self._version, who, key, value))
            return self._version

    def update(self, key: str, fn: Callable[[Any], Any], *, default: Any = None, who: str = "?") -> Any:
        """Atomically transform a value: ``bb.update("count", lambda c: c + 1)``."""
        with self._lock:
            new = fn(self._data.get(key, default))
            self._version += 1
            self._data[key] = new
            self._history.append((self._version, who, key, new))
            return new

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._data)

    def history(self, since: int = 0) -> Iterator[Tuple[int, str, str, Any]]:
        """Yield writes with ``version > since`` — the audit trail of a run."""
        for entry in self._history:
            if entry[0] > since:
                yield entry
