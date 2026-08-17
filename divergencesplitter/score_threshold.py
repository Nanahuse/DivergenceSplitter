"""ScoreThreshold: observation to bool conversion."""

from dataclasses import dataclass

from divergencesplitter.models import DetectionResult


@dataclass(frozen=True)
class ScoreThreshold:
    """Satisfied when ``result.score`` is at least ``minimum_score``."""

    minimum_score: float

    def apply(self, result: DetectionResult) -> bool:
        return result.score >= self.minimum_score
