import unittest
from typing import cast

import numpy as np

from divergencesplitter.detector.common import (
    evaluate,
    frame_mean,
    frame_mean_abs_diff,
    preprocessed,
)
from divergencesplitter.detector.frame_difference import FrameDifferenceDetector
from divergencesplitter.detector.interface import ImageDetector
from divergencesplitter.detector.mean_brightness import MeanBrightnessDetector
from divergencesplitter.models import DetectionSample, Frame, FrameContext

DARK = np.zeros((2, 3), dtype=np.uint8)
BRIGHT = np.full((2, 3), 255, dtype=np.uint8)
REFERENCE = ((0, 0), (0, 0))
REFERENCE_IMAGE = np.asarray(REFERENCE)


def make_context(image, now=1.0):
    return FrameContext(frame=Frame(image=image), now=now)


class MeanBrightnessDetectorTest(unittest.TestCase):
    def test_known_images(self):
        detector = MeanBrightnessDetector(threshold=100.0)
        dark = evaluate(make_context(DARK), detector)
        self.assertFalse(dark.matched)
        self.assertEqual(dark.score, 0.0)
        bright = evaluate(make_context(BRIGHT), detector)
        self.assertTrue(bright.matched)
        self.assertEqual(bright.score, 255.0)

    def test_threshold_boundary(self):
        detector = MeanBrightnessDetector(threshold=50.0)
        boundary = make_context(np.array([[50, 50], [50, 50]], dtype=np.uint8))
        self.assertFalse(evaluate(boundary, detector).matched)
        above = make_context(np.array([[51, 51], [51, 51]], dtype=np.uint8))
        self.assertTrue(evaluate(above, detector).matched)

    def test_multidimensional_image(self):
        detector = MeanBrightnessDetector(threshold=100.0)
        dark_color = make_context(np.zeros((2, 2, 3), dtype=np.uint8))
        self.assertFalse(evaluate(dark_color, detector).matched)
        bright_color = make_context(np.full((2, 2, 3), 255, dtype=np.uint8))
        sample = evaluate(bright_color, detector)
        self.assertTrue(sample.matched)
        self.assertEqual(sample.score, 255.0)


class FrameDifferenceDetectorTest(unittest.TestCase):
    def test_known_images(self):
        detector = FrameDifferenceDetector(reference=REFERENCE, threshold=1.0)
        same = evaluate(make_context(REFERENCE_IMAGE), detector)
        self.assertFalse(same.matched)
        self.assertEqual(same.score, 0.0)
        changed = evaluate(
            make_context(np.array([[10, 10], [10, 10]], dtype=np.uint8)), detector
        )
        self.assertTrue(changed.matched)
        self.assertEqual(changed.score, 10.0)

    def test_threshold_boundary(self):
        detector = FrameDifferenceDetector(reference=REFERENCE, threshold=10.0)
        boundary = make_context(np.array([[10, 10], [10, 10]], dtype=np.uint8))
        self.assertTrue(evaluate(boundary, detector).matched)
        below = make_context(np.array([[9, 9], [9, 9]], dtype=np.uint8))
        self.assertFalse(evaluate(below, detector).matched)


class CountingDetector:
    def __init__(self, threshold: float) -> None:
        self.threshold = threshold
        self.evaluations = 0

    def detect(self, context: FrameContext) -> DetectionSample:
        self.evaluations += 1
        mean = frame_mean(context)
        return DetectionSample(matched=mean > self.threshold, score=mean)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CountingDetector):
            return NotImplemented
        return self.threshold == other.threshold

    def __hash__(self) -> int:
        return hash(("CountingDetector", self.threshold))


class FailingDetector:
    def __init__(self, fail: bool) -> None:
        self.fail = fail

    def detect(self, context: FrameContext) -> DetectionSample:
        if self.fail:
            raise ValueError("boom")
        return DetectionSample(matched=False)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FailingDetector):
            return NotImplemented
        return self.fail == other.fail

    def __hash__(self) -> int:
        return hash(("FailingDetector", self.fail))


class IncompleteDetector:
    def detect(self, context: FrameContext) -> object:
        return None


class CacheTest(unittest.TestCase):
    def test_equivalent_instances_evaluated_once(self):
        context = make_context(BRIGHT)
        detector = CountingDetector(threshold=100.0)
        equivalent = CountingDetector(threshold=100.0)
        sample = evaluate(context, detector)
        cached = evaluate(context, equivalent)
        self.assertEqual(detector.evaluations, 1)
        self.assertEqual(equivalent.evaluations, 0)
        self.assertEqual(sample, cached)
        self.assertIs(sample, cached)

    def test_next_frame_reevaluates(self):
        detector = CountingDetector(threshold=100.0)
        evaluate(make_context(DARK, now=1.0), detector)
        self.assertEqual(detector.evaluations, 1)
        evaluate(make_context(BRIGHT, now=2.0), detector)
        self.assertEqual(detector.evaluations, 2)

    def test_exception_is_not_cached(self):
        detector = FailingDetector(fail=True)
        context = make_context(DARK)
        with self.assertRaises(ValueError):
            evaluate(context, detector)
        self.assertEqual(context.detection_cache, {})
        with self.assertRaises(ValueError):
            evaluate(context, detector)
        self.assertEqual(context.detection_cache, {})

    def test_incomplete_result_is_not_cached(self):
        context = make_context(DARK)
        detector = cast(ImageDetector, IncompleteDetector())
        with self.assertRaises(TypeError):
            evaluate(context, detector)
        self.assertEqual(context.detection_cache, {})
        with self.assertRaises(TypeError):
            evaluate(context, detector)
        self.assertEqual(context.detection_cache, {})

    def test_size_mismatch_raises_and_is_not_cached(self):
        detector = FrameDifferenceDetector(reference=REFERENCE, threshold=1.0)
        context = make_context(np.zeros((2, 3), dtype=np.uint8))
        with self.assertRaises(ValueError):
            evaluate(context, detector)
        self.assertEqual(context.detection_cache, {})


class PreprocessingCacheTest(unittest.TestCase):
    def test_preprocessed_computed_once(self):
        context = make_context(DARK)
        calls = []

        def compute() -> float:
            calls.append(1)
            return 42.0

        first = preprocessed(context, "key", compute)
        second = preprocessed(context, "key", compute)
        self.assertEqual(first, 42.0)
        self.assertEqual(second, 42.0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(context.preprocessing_cache["key"], 42.0)

    def test_preprocessed_caches_none(self):
        context = make_context(DARK)
        calls = []

        def compute() -> None:
            calls.append(1)

        first = preprocessed(context, "key", compute)
        second = preprocessed(context, "key", compute)
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(calls), 1)
        self.assertIn("key", context.preprocessing_cache)

    def test_detectors_share_frame_mean_preprocessing(self):
        context = make_context(BRIGHT)
        evaluate(context, MeanBrightnessDetector(threshold=0.0))
        evaluate(context, MeanBrightnessDetector(threshold=1000.0))
        self.assertEqual(frame_mean(context), 255.0)
        self.assertEqual(context.preprocessing_cache["frame-mean"], 255.0)

    def test_detectors_share_diff_for_same_reference(self):
        context = make_context(np.array([[3, 3], [3, 3]], dtype=np.uint8))
        evaluate(context, FrameDifferenceDetector(reference=REFERENCE, threshold=0.0))
        evaluate(context, FrameDifferenceDetector(reference=REFERENCE, threshold=5.0))
        self.assertEqual(frame_mean_abs_diff(context, REFERENCE), 3.0)
        self.assertEqual(
            context.preprocessing_cache[("frame-mean-abs-diff", REFERENCE)], 3.0
        )

    def test_different_references_do_not_share(self):
        other_reference = ((1, 1), (1, 1))
        context = make_context(np.array([[3, 3], [3, 3]], dtype=np.uint8))
        evaluate(context, FrameDifferenceDetector(reference=REFERENCE, threshold=0.0))
        evaluate(
            context, FrameDifferenceDetector(reference=other_reference, threshold=0.0)
        )
        self.assertIn(("frame-mean-abs-diff", REFERENCE), context.preprocessing_cache)
        self.assertIn(
            ("frame-mean-abs-diff", other_reference), context.preprocessing_cache
        )
