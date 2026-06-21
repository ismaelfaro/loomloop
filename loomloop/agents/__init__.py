"""Ready-made nanoloops.

``FunctionLoop`` and ``RelayLoop`` are pure-stdlib and always available.
``LLMLoop`` is imported lazily because it depends on the optional ``anthropic``
package — import it directly from :mod:`loomloop.agents.llm` when you need it.
"""

from .function import FunctionLoop, RelayLoop

__all__ = ["FunctionLoop", "RelayLoop"]
