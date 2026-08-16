"""ScoreThresholdTrigger implementation."""

from dataclasses import dataclass

from divergencesplitter.detector.common import evaluate
from divergencesplitter.detector.interface import ImageDetector
from divergencesplitter.models import FrameContext


@dataclass(frozen=True)
class ScoreThresholdTrigger:
    """Satisfied when ``detector``'s score is at least ``minimum_score``."""

    detector: ImageDetector
    minimum_score: float

    def evaluate(self, context: FrameContext) -> bool:
        result = evaluate(context, self.detector)
        return result.score >= self.minimum_score
