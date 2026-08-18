"""Boolean logic operations built on top of detector observations.

Stateless operations (``All``, ``Any``, ``Not``) expose ``apply``. Stateful
operations (``RisingEdge``, ``FallingEdge``, ``Hold``, ``Then``) keep their
per-instance history internally and expose ``step``.
"""

from divergencesplitter.logic.all_ import All
from divergencesplitter.logic.any_ import Any
from divergencesplitter.logic.falling_edge import FallingEdge
from divergencesplitter.logic.hold import Hold
from divergencesplitter.logic.not_ import Not
from divergencesplitter.logic.rising_edge import RisingEdge
from divergencesplitter.logic.then import Then

__all__ = [
    "All",
    "Any",
    "FallingEdge",
    "Hold",
    "Not",
    "RisingEdge",
    "Then",
]
