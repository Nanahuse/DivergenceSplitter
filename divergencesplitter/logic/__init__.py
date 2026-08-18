"""Boolean logic operations built on top of detector observations.

Operations are immutable, hashable value objects. Stateless operations
(``All``, ``Any``, ``Not``) expose ``apply``. Stateful operations expose
``initial_state`` and ``step``, keeping per-operation time-series history in a
dedicated frozen state dataclass rather than on the definition itself.
"""

from divergencesplitter.logic.all_ import All
from divergencesplitter.logic.any_ import Any
from divergencesplitter.logic.falling_edge import FallingEdge, FallingEdgeState
from divergencesplitter.logic.hold import Hold, HoldState
from divergencesplitter.logic.not_ import Not
from divergencesplitter.logic.rising_edge import RisingEdge, RisingEdgeState
from divergencesplitter.logic.then import Then, ThenState

__all__ = [
    "All",
    "Any",
    "FallingEdge",
    "FallingEdgeState",
    "Hold",
    "HoldState",
    "Not",
    "RisingEdge",
    "RisingEdgeState",
    "Then",
    "ThenState",
]
