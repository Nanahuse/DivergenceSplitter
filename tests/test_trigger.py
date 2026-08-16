import unittest
from dataclasses import dataclass

import numpy as np

from divergencesplitter.models import DetectionResult, Frame, FrameContext
from divergencesplitter.trigger.score_threshold import ScoreThresholdTrigger


def make_context(now=1.0):
    return FrameContext(frame=Frame(image=np.zeros((2, 2), dtype=np.uint8)), now=now)


@dataclass(frozen=True)
class FixedScoreDetector:
    score: float

    def detect(self, context: FrameContext) -> DetectionResult:
        return DetectionResult(score=self.score)


class CountingDetector:
    def __init__(self) -> None:
        self.evaluations = 0

    def detect(self, context: FrameContext) -> DetectionResult:
        self.evaluations += 1
        return DetectionResult(score=100.0)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CountingDetector)

    def __hash__(self) -> int:
        return hash("CountingDetector")


class ScoreThresholdTriggerTest(unittest.TestCase):
    def test_minimum_score_boundary(self):
        at = ScoreThresholdTrigger(FixedScoreDetector(10.0), minimum_score=10.0)
        above = ScoreThresholdTrigger(FixedScoreDetector(10.5), minimum_score=10.0)
        below = ScoreThresholdTrigger(FixedScoreDetector(9.999), minimum_score=10.0)
        self.assertTrue(at.evaluate(make_context()))
        self.assertTrue(above.evaluate(make_context()))
        self.assertFalse(below.evaluate(make_context()))

    def test_multiple_thresholds_reuse_single_detector_result(self):
        detector = FixedScoreDetector(255.0)
        below = ScoreThresholdTrigger(detector, minimum_score=100.0)
        at = ScoreThresholdTrigger(detector, minimum_score=255.0)
        above = ScoreThresholdTrigger(detector, minimum_score=256.0)
        context = make_context()
        self.assertTrue(below.evaluate(context))
        self.assertTrue(at.evaluate(context))
        self.assertFalse(above.evaluate(context))

    def test_equivalent_detector_evaluated_once(self):
        context = make_context()
        first = CountingDetector()
        equivalent = CountingDetector()
        below = ScoreThresholdTrigger(first, minimum_score=50.0)
        above = ScoreThresholdTrigger(equivalent, minimum_score=150.0)
        self.assertTrue(below.evaluate(context))
        self.assertFalse(above.evaluate(context))
        self.assertEqual(first.evaluations, 1)
        self.assertEqual(equivalent.evaluations, 0)


if __name__ == "__main__":
    unittest.main()
