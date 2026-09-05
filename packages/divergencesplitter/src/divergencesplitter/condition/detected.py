from divergencesplitter.condition._base import ConditionBase
from divergencesplitter.condition.interface import Condition
from divergencesplitter.detector import ImageDetector, evaluate
from divergencesplitter.frame.models import FrameContext


class Detected(ConditionBase):
    def __init__(self, detector: ImageDetector, minimum_score: float) -> None:
        self._detector = detector
        self._minimum_score = minimum_score
        self._latest_score: float | None = None
        self._max_score: float | None = None

    @property
    def detector(self) -> ImageDetector:
        return self._detector

    @property
    def minimum_score(self) -> float:
        return self._minimum_score

    @property
    def latest_score(self) -> float | None:
        """Most recent score from a normal evaluation, or ``None`` before one."""
        return self._latest_score

    @property
    def max_score(self) -> float | None:
        """Highest score observed since starting or resetting, or ``None``."""
        return self._max_score

    @property
    def children(self) -> tuple[Condition, ...]:
        return ()

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        if is_short_circuited:
            return None
        score = evaluate(context, self._detector).score
        self._latest_score = score
        if self._max_score is None or score > self._max_score:
            self._max_score = score
        return score >= self._minimum_score

    def _reset_state(self) -> None:
        self._latest_score = None
        self._max_score = None
