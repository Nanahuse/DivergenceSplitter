"""DetectionCondition contract."""

from typing import Protocol

from divergencesplitter.models import DetectionResult


class DetectionCondition(Protocol):
    """Stateless single-observation logical decision contract.

    Implementations evaluate a single ``DetectionResult`` and return whether it
    satisfies the condition. They must be stateless and immutable.
    """

    def evaluate(self, result: DetectionResult) -> bool: ...
