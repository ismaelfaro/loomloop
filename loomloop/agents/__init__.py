"""Ready-made nanoloops.

All of these are pure-stdlib. ``BrainLoop`` is model-agnostic — it only needs a
:class:`loomloop.backend.Backend`; a specific provider SDK (e.g. ``anthropic``
via :class:`loomloop.backend.ClaudeBackend`) is only imported when you choose
that backend.
"""

from .function import FunctionLoop, RelayLoop, nanoloop
from .brain import BrainLoop, LLMLoop
from .oak_agent import OakBranchLoop

__all__ = ["FunctionLoop", "RelayLoop", "nanoloop", "BrainLoop", "LLMLoop",
           "OakBranchLoop"]
