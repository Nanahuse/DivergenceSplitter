import unittest

import numpy as np

from divergencesplitter.condition.score_threshold import ScoreThresholdCondition
from divergencesplitter.detector.common import evaluate
from divergencesplitter.detector.mean_brightness import MeanBrightnessDetector
from divergencesplitter.models import DetectionResult, Frame, FrameContext

BRIGHT = np.full((2, 3), 255, dtype=np.uint8)


def make_context(image, now=1.0):
    return FrameContext(frame=Frame(image=image), now=now)


class ScoreThresholdConditionTest(unittest.TestCase):
    def test_minimum_score_boundary(self):
        condition = ScoreThresholdCondition(minimum_score=10.0)
        self.assertTrue(condition.evaluate(DetectionResult(score=10.0)))
        self.assertTrue(condition.evaluate(DetectionResult(score=10.5)))
        self.assertFalse(condition.evaluate(DetectionResult(score=9.999)))

    def test_same_detector_result_reused_by_multiple_conditions(self):
        result = evaluate(make_context(BRIGHT), MeanBrightnessDetector())
        below = ScoreThresholdCondition(minimum_score=100.0)
        at = ScoreThresholdCondition(minimum_score=255.0)
        above = ScoreThresholdCondition(minimum_score=256.0)
        self.assertTrue(below.evaluate(result))
        self.assertTrue(at.evaluate(result))
        self.assertFalse(above.evaluate(result))
