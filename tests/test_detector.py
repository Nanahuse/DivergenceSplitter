import unittest
from typing import cast

import cv2
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


def _resized_reference(image, size):
    resized = cv2.resize(image, size, interpolation=cv2.INTER_LINEAR)
    return tuple(tuple(int(value) for value in row) for row in resized)


class DetectorSizeTest(unittest.TestCase):
    def test_size_none_preserves_existing_behavior(self):
        context = make_context(DARK)
        result = evaluate(context, MeanBrightnessDetector())
        self.assertEqual(result.score, 0.0)
        self.assertIn("frame-mean", context.preprocessing_cache)
        self.assertNotIn(("frame-resize", None), context.preprocessing_cache)

    def test_diff_size_none_preserves_existing_behavior(self):
        context = make_context(REFERENCE_IMAGE)
        result = evaluate(context, FrameDifferenceDetector(reference=REFERENCE))
        self.assertEqual(result.score, 0.0)
        self.assertIn(("frame-mean-abs-diff", REFERENCE), context.preprocessing_cache)
        self.assertNotIn(("frame-resize", None), context.preprocessing_cache)

    def test_mean_resizes_with_inter_linear_pixels(self):
        image = np.arange(6 * 8, dtype=np.uint8).reshape(6, 8)
        size = (4, 3)
        context = make_context(image)
        result = evaluate(context, MeanBrightnessDetector(size=size))
        expected = cv2.resize(image, size, interpolation=cv2.INTER_LINEAR)
        self.assertIn(("frame-resize", size), context.preprocessing_cache)
        np.testing.assert_array_equal(
            context.preprocessing_cache[("frame-resize", size)], expected
        )
        self.assertEqual(result.score, float(np.mean(expected)))

    def test_diff_matches_resized_inter_linear_score(self):
        image = np.zeros((6, 8), dtype=np.uint8)
        size = (4, 3)
        reference = tuple((10,) * 4 for _ in range(3))
        result = evaluate(
            make_context(image), FrameDifferenceDetector(reference=reference, size=size)
        )
        self.assertEqual(result.score, 10.0)

    def test_diff_compares_against_resized_reference(self):
        image = np.arange(6 * 8, dtype=np.uint8).reshape(6, 8)
        size = (4, 3)
        reference = _resized_reference(image, size)
        result = evaluate(
            make_context(image), FrameDifferenceDetector(reference=reference, size=size)
        )
        self.assertEqual(result.score, 0.0)

    def test_size_is_retained(self):
        self.assertEqual(MeanBrightnessDetector(size=(4, 5)).size, (4, 5))
        self.assertEqual(
            FrameDifferenceDetector(reference=REFERENCE, size=(4, 5)).size, (4, 5)
        )
        self.assertIsNone(MeanBrightnessDetector().size)
        self.assertIsNone(FrameDifferenceDetector(reference=REFERENCE).size)

    def test_size_participates_in_equality_and_hash(self):
        self.assertEqual(
            MeanBrightnessDetector(size=(4, 4)), MeanBrightnessDetector(size=(4, 4))
        )
        self.assertNotEqual(
            MeanBrightnessDetector(size=(4, 4)), MeanBrightnessDetector()
        )
        self.assertNotEqual(
            MeanBrightnessDetector(size=(4, 4)), MeanBrightnessDetector(size=(4, 5))
        )
        self.assertEqual(
            hash(MeanBrightnessDetector(size=(4, 4))),
            hash(MeanBrightnessDetector(size=(4, 4))),
        )
        self.assertEqual(
            FrameDifferenceDetector(reference=REFERENCE, size=(4, 4)),
            FrameDifferenceDetector(reference=REFERENCE, size=(4, 4)),
        )
        self.assertNotEqual(
            FrameDifferenceDetector(reference=REFERENCE, size=(4, 4)),
            FrameDifferenceDetector(reference=REFERENCE, size=(4, 5)),
        )
        self.assertNotEqual(
            FrameDifferenceDetector(reference=REFERENCE, size=(4, 4)),
            FrameDifferenceDetector(reference=REFERENCE),
        )

    def test_non_positive_size_rejected(self):
        for size in [(0, 2), (2, 0), (-1, 2), (2, -1)]:
            with self.assertRaises(ValueError):
                MeanBrightnessDetector(size=size)
            with self.assertRaises(ValueError):
                FrameDifferenceDetector(reference=REFERENCE, size=size)

    def test_same_size_resize_shared_across_detectors(self):
        image = np.arange(6 * 8, dtype=np.uint8).reshape(6, 8)
        size = (4, 3)
        reference = _resized_reference(image, size)
        context = make_context(image)
        evaluate(context, MeanBrightnessDetector(size=size))
        evaluate(context, FrameDifferenceDetector(reference=reference, size=size))
        self.assertIn(("frame-resize", size), context.preprocessing_cache)
        resize_keys = [
            key
            for key in context.preprocessing_cache
            if isinstance(key, tuple) and key[0] == "frame-resize"
        ]
        self.assertEqual(len(resize_keys), 1)

    def test_different_sizes_do_not_share_resize(self):
        image = np.arange(6 * 8, dtype=np.uint8).reshape(6, 8)
        context = make_context(image)
        evaluate(context, MeanBrightnessDetector(size=(4, 3)))
        evaluate(context, MeanBrightnessDetector(size=(8, 2)))
        self.assertIn(("frame-resize", (4, 3)), context.preprocessing_cache)
        self.assertIn(("frame-resize", (8, 2)), context.preprocessing_cache)
        self.assertEqual(
            context.preprocessing_cache[("frame-resize", (4, 3))].shape, (3, 4)
        )
        self.assertEqual(
            context.preprocessing_cache[("frame-resize", (8, 2))].shape, (2, 8)
        )

    def test_derived_keys_include_size_and_do_not_collide(self):
        image = np.arange(6 * 8, dtype=np.uint8).reshape(6, 8)
        context = make_context(image)
        first = evaluate(context, MeanBrightnessDetector(size=(4, 3)))
        second = evaluate(context, MeanBrightnessDetector(size=(8, 2)))
        expected_first = float(
            np.mean(cv2.resize(image, (4, 3), interpolation=cv2.INTER_LINEAR))
        )
        expected_second = float(
            np.mean(cv2.resize(image, (8, 2), interpolation=cv2.INTER_LINEAR))
        )
        self.assertEqual(first.score, expected_first)
        self.assertEqual(second.score, expected_second)
        self.assertIn(("frame-mean", (4, 3)), context.preprocessing_cache)
        self.assertIn(("frame-mean", (8, 2)), context.preprocessing_cache)
        self.assertNotIn("frame-mean", context.preprocessing_cache)

    def test_diff_derived_key_includes_size(self):
        image = np.zeros((6, 8), dtype=np.uint8)
        size = (4, 3)
        reference = tuple((10,) * 4 for _ in range(3))
        context = make_context(image)
        evaluate(context, FrameDifferenceDetector(reference=reference, size=size))
        self.assertIn(
            ("frame-mean-abs-diff", size, reference), context.preprocessing_cache
        )
        self.assertNotIn(
            ("frame-mean-abs-diff", reference), context.preprocessing_cache
        )

    def test_resized_diff_shape_mismatch_raises_and_is_not_cached(self):
        image = np.zeros((6, 8), dtype=np.uint8)
        context = make_context(image)
        detector = FrameDifferenceDetector(reference=REFERENCE, size=(4, 3))
        with self.assertRaises(ValueError):
            evaluate(context, detector)
        self.assertEqual(context.detection_cache, {})
        self.assertNotIn(
            ("frame-mean-abs-diff", (4, 3), REFERENCE), context.preprocessing_cache
        )
