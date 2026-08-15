"""ScoreThresholdCondition implementation."""

from dataclasses import dataclass

from divergencesplitter.models import DetectionResult


@dataclass(frozen=True)
class ScoreThresholdCondition:
    """Satisfied when the detection score is at least ``minimum_score``."""

    minimum_score: float

    def evaluate(self, result: DetectionResult) -> bool:
        return result.score >= self.minimum_score
