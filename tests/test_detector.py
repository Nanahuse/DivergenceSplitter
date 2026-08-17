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
from divergencesplitter.models import (
    DetectionResult,
    Frame,
    FrameContext,
    MonotonicTime,
)

DARK = np.zeros((2, 3), dtype=np.uint8)
BRIGHT = np.full((2, 3), 255, dtype=np.uint8)
REFERENCE = ((0, 0), (0, 0))
REFERENCE_IMAGE = np.asarray(REFERENCE)
EPOCH = MonotonicTime(nanoseconds=0)


def make_context(image, now=EPOCH):
    return FrameContext(frame=Frame(image=image), now=now)


class MeanBrightnessDetectorTest(unittest.TestCase):
    def test_known_images(self):
        detector = MeanBrightnessDetector()
        dark = evaluate(make_context(DARK), detector)
        self.assertEqual(dark.score, 0.0)
        bright = evaluate(make_context(BRIGHT), detector)
        self.assertEqual(bright.score, 255.0)

    def test_multidimensional_image(self):
        detector = MeanBrightnessDetector()
        dark_color = evaluate(
            make_context(np.zeros((2, 2, 3), dtype=np.uint8)), detector
        )
        self.assertEqual(dark_color.score, 0.0)
        bright_color = evaluate(
            make_context(np.full((2, 2, 3), 255, dtype=np.uint8)), detector
        )
        self.assertEqual(bright_color.score, 255.0)


class FrameDifferenceDetectorTest(unittest.TestCase):
    def test_known_images(self):
        detector = FrameDifferenceDetector(reference=REFERENCE)
        same = evaluate(make_context(REFERENCE_IMAGE), detector)
        self.assertEqual(same.score, 0.0)
        changed = evaluate(
            make_context(np.array([[10, 10], [10, 10]], dtype=np.uint8)), detector
        )
        self.assertEqual(changed.score, 10.0)


class CountingDetector:
    def __init__(self) -> None:
        self.evaluations = 0

    def detect(self, context: FrameContext) -> DetectionResult:
        self.evaluations += 1
        return DetectionResult(score=frame_mean(context))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CountingDetector)

    def __hash__(self) -> int:
        return hash("CountingDetector")


class FailingDetector:
    def __init__(self, fail: bool) -> None:
        self.fail = fail

    def detect(self, context: FrameContext) -> DetectionResult:
        if self.fail:
            raise ValueError("boom")
        return DetectionResult(score=0.0)

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
        detector = CountingDetector()
        equivalent = CountingDetector()
        result = evaluate(context, detector)
        cached = evaluate(context, equivalent)
        self.assertEqual(detector.evaluations, 1)
        self.assertEqual(equivalent.evaluations, 0)
        self.assertEqual(result, cached)
        self.assertIs(result, cached)

    def test_next_frame_reevaluates(self):
        detector = CountingDetector()
        evaluate(make_context(DARK, now=EPOCH), detector)
        self.assertEqual(detector.evaluations, 1)
        evaluate(
            make_context(BRIGHT, now=MonotonicTime(nanoseconds=1_000_000_000)),
            detector,
        )
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
        detector = FrameDifferenceDetector(reference=REFERENCE)
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
        evaluate(context, MeanBrightnessDetector())
        evaluate(context, CountingDetector())
        self.assertEqual(frame_mean(context), 255.0)
        self.assertEqual(context.preprocessing_cache["frame-mean"], 255.0)

    def test_detector_diff_is_cached_for_reuse(self):
        context = make_context(np.array([[3, 3], [3, 3]], dtype=np.uint8))
        evaluate(context, FrameDifferenceDetector(reference=REFERENCE))
        self.assertEqual(frame_mean_abs_diff(context, REFERENCE), 3.0)
        self.assertEqual(
            context.preprocessing_cache[("frame-mean-abs-diff", REFERENCE)], 3.0
        )

    def test_different_references_do_not_share(self):
        other_reference = ((1, 1), (1, 1))
        context = make_context(np.array([[3, 3], [3, 3]], dtype=np.uint8))
        evaluate(context, FrameDifferenceDetector(reference=REFERENCE))
        evaluate(context, FrameDifferenceDetector(reference=other_reference))
        self.assertIn(("frame-mean-abs-diff", REFERENCE), context.preprocessing_cache)
        self.assertIn(
            ("frame-mean-abs-diff", other_reference), context.preprocessing_cache
        )
