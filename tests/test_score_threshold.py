import unittest

from divergencesplitter.models import DetectionResult
from divergencesplitter.score_threshold import ScoreThreshold


class ScoreThresholdTest(unittest.TestCase):
    def test_below_threshold(self):
        threshold = ScoreThreshold(minimum_score=10.0)
        self.assertFalse(threshold.apply(DetectionResult(score=9.999)))

    def test_equal_to_threshold(self):
        threshold = ScoreThreshold(minimum_score=10.0)
        self.assertTrue(threshold.apply(DetectionResult(score=10.0)))

    def test_above_threshold(self):
        threshold = ScoreThreshold(minimum_score=10.0)
        self.assertTrue(threshold.apply(DetectionResult(score=10.5)))


if __name__ == "__main__":
    unittest.main()
