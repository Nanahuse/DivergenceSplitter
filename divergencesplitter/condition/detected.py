from divergencesplitter.condition._base import ConditionBase
from divergencesplitter.detector import ImageDetector, evaluate
from divergencesplitter.models import FrameContext


class Detected(ConditionBase):
    def __init__(self, detector: ImageDetector, minimum_score: float) -> None:
        self._detector = detector
        self._minimum_score = minimum_score

    def _evaluate(
        self, context: FrameContext, *, is_short_circuited: bool
    ) -> bool | None:
        if is_short_circuited:
            return None
        return evaluate(context, self._detector).score >= self._minimum_score

    def reset(self) -> None:
        pass
