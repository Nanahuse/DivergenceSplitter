from divergencesplitter.condition._base import ConditionBase
from divergencesplitter.condition.interface import Condition
from divergencesplitter.detector import ImageDetector, evaluate
from divergencesplitter.frame.models import FrameContext


class Detected(ConditionBase):
    def __init__(self, detector: ImageDetector, minimum_score: float) -> None:
        self._detector = detector
        self._minimum_score = minimum_score

    @property
    def detector(self) -> ImageDetector:
        return self._detector

    @property
    def minimum_score(self) -> float:
        return self._minimum_score

    @property
    def children(self) -> tuple[Condition, ...]:
        return ()

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        if is_short_circuited:
            return None
        return evaluate(context, self._detector).score >= self._minimum_score

    def reset(self) -> None:
        pass
