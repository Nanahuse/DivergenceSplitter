import unittest
from dataclasses import is_dataclass
from typing import cast
from unittest.mock import patch

import numpy as np

from divergencesplitter.clock import MonotonicTime
from divergencesplitter.detector.color_range import ColorRangeConfig, ColorRangeDetector
from divergencesplitter.detector.common import evaluate
from divergencesplitter.detector.difference_hash import (
    DifferenceHashSimilarityConfig,
    DifferenceHashSimilarityDetector,
)
from divergencesplitter.detector.mean_absolute_similarity import (
    MeanAbsoluteSimilarityConfig,
    MeanAbsoluteSimilarityDetector,
)
from divergencesplitter.detector.models import (
    ConfigImage,
    FrozenConfigImage,
    freeze_config_image,
)
from divergencesplitter.detector.phase_correlation import (
    PhaseCorrelationConfig,
    PhaseCorrelationDetector,
)
from divergencesplitter.detector.template_match import (
    TemplateMatchConfig,
    TemplateMatchDetector,
)
from divergencesplitter.frame.models import Frame, FrameContext

EPOCH = MonotonicTime(nanoseconds=0)
PATTERN = ((0, 255), (255, 0))


def make_context(image: np.ndarray) -> FrameContext:
    return FrameContext(frame=Frame(image=image, captured_at=EPOCH), now=EPOCH)


def assign_attribute(target: object, name: str, value: object) -> None:
    setattr(target, name, value)


class TemplateMatchDetectorTest(unittest.TestCase):
    def test_finds_template_at_an_offset(self) -> None:
        frame = np.zeros((5, 6), dtype=np.uint8)
        frame[2:4, 3:5] = np.asarray(PATTERN, dtype=np.uint8)
        score = evaluate(
            make_context(frame), TemplateMatchDetector(TemplateMatchConfig(PATTERN))
        ).score
        self.assertAlmostEqual(score, 1.0)

    def test_rejects_constant_template(self) -> None:
        with self.assertRaises(ValueError):
            TemplateMatchConfig(((1, 1), (1, 1)))

    def test_rejects_oversized_template(self) -> None:
        detector = TemplateMatchDetector(TemplateMatchConfig(PATTERN))
        with self.assertRaises(ValueError):
            evaluate(make_context(np.zeros((1, 2), dtype=np.uint8)), detector)

    def test_rejects_channel_mismatch(self) -> None:
        detector = TemplateMatchDetector(TemplateMatchConfig(PATTERN))
        with self.assertRaises(ValueError):
            evaluate(make_context(np.zeros((4, 4, 3), dtype=np.uint8)), detector)


class ColorRangeDetectorTest(unittest.TestCase):
    def test_bounds_are_inclusive_and_score_is_pixel_ratio(self) -> None:
        frame = np.array([[0, 10], [20, 30]], dtype=np.uint8)
        detector = ColorRangeDetector(ColorRangeConfig(lower=(10,), upper=(20,)))
        self.assertEqual(evaluate(make_context(frame), detector).score, 0.5)

    def test_three_channel_range(self) -> None:
        frame = np.array([[[10, 20, 30], [11, 21, 31]]], dtype=np.uint8)
        detector = ColorRangeDetector(
            ColorRangeConfig(lower=(10, 20, 30), upper=(10, 20, 30))
        )
        self.assertEqual(evaluate(make_context(frame), detector).score, 0.5)

    def test_rejects_invalid_bounds(self) -> None:
        with self.assertRaises(ValueError):
            ColorRangeConfig(lower=(2,), upper=(1,))
        with self.assertRaises(ValueError):
            ColorRangeConfig(lower=(0, 0), upper=(1, 1))
        with self.assertRaises(ValueError):
            ColorRangeConfig(lower=(0,), upper=(1, 1, 1))

    def test_rejects_channel_mismatch(self) -> None:
        detector = ColorRangeDetector(ColorRangeConfig(lower=(0,), upper=(255,)))
        with self.assertRaises(ValueError):
            evaluate(make_context(np.zeros((2, 2, 3), dtype=np.uint8)), detector)


class PhaseCorrelationDetectorTest(unittest.TestCase):
    def test_shifted_pattern_has_a_strong_match(self) -> None:
        reference = np.zeros((16, 16), dtype=np.float32)
        reference[3:7, 4:9] = np.arange(20, dtype=np.float32).reshape(4, 5)
        shifted = np.roll(reference, shift=(3, -2), axis=(0, 1))
        detector = PhaseCorrelationDetector(
            PhaseCorrelationConfig(freeze_config_image(reference.tolist()))
        )
        score = evaluate(make_context(shifted), detector).score
        self.assertGreater(score, 0.9)

    def test_color_images_are_converted_to_grayscale(self) -> None:
        gray = np.arange(64, dtype=np.uint8).reshape(8, 8)
        color = np.repeat(gray[:, :, None], 3, axis=2)
        color_score = evaluate(
            make_context(color),
            PhaseCorrelationDetector(
                PhaseCorrelationConfig(freeze_config_image(color.tolist()))
            ),
        ).score
        gray_score = evaluate(
            make_context(gray),
            PhaseCorrelationDetector(
                PhaseCorrelationConfig(freeze_config_image(gray.tolist()))
            ),
        ).score
        self.assertAlmostEqual(color_score, gray_score)

    def test_rejects_shape_mismatch(self) -> None:
        detector = PhaseCorrelationDetector(PhaseCorrelationConfig(PATTERN))
        with self.assertRaises(ValueError):
            evaluate(make_context(np.zeros((3, 3), dtype=np.uint8)), detector)


class DifferenceHashSimilarityDetectorTest(unittest.TestCase):
    def test_identical_and_opposite_gradients(self) -> None:
        increasing = np.tile(np.arange(9, dtype=np.uint8), (8, 1))
        decreasing = increasing[:, ::-1].copy()
        detector = DifferenceHashSimilarityDetector(
            DifferenceHashSimilarityConfig(
                freeze_config_image(increasing.tolist()),
                hash_size=8,
            )
        )
        self.assertEqual(evaluate(make_context(increasing), detector).score, 1.0)
        self.assertEqual(evaluate(make_context(decreasing), detector).score, 0.0)

    def test_rejects_invalid_hash_size(self) -> None:
        with self.assertRaises(ValueError):
            DifferenceHashSimilarityConfig(PATTERN, hash_size=0)
        with self.assertRaises(ValueError):
            DifferenceHashSimilarityConfig(PATTERN, hash_size=True)

    def test_frame_hash_is_shared_by_hash_size(self) -> None:
        frame = np.tile(np.arange(9, dtype=np.uint8), (8, 1))
        first = DifferenceHashSimilarityDetector(
            DifferenceHashSimilarityConfig(freeze_config_image(frame.tolist()))
        )
        second = DifferenceHashSimilarityDetector(
            DifferenceHashSimilarityConfig(freeze_config_image(frame[:, ::-1].tolist()))
        )
        with patch(
            "divergencesplitter.detector.common.dhash_bits",
            wraps=__import__(
                "divergencesplitter.detector.common",
                fromlist=["dhash_bits"],
            ).dhash_bits,
        ) as compute:
            context = make_context(frame)
            evaluate(context, first)
            evaluate(context, second)
        self.assertEqual(compute.call_count, 1)
        self.assertIn(("frame-dhash", 8), context.preprocessing_cache)


class ConfigImageTest(unittest.TestCase):
    def test_detector_configurations_are_data_classes(self) -> None:
        config_detector_pairs = (
            (MeanAbsoluteSimilarityConfig, MeanAbsoluteSimilarityDetector),
            (TemplateMatchConfig, TemplateMatchDetector),
            (ColorRangeConfig, ColorRangeDetector),
            (PhaseCorrelationConfig, PhaseCorrelationDetector),
            (DifferenceHashSimilarityConfig, DifferenceHashSimilarityDetector),
        )
        for config_type, detector_type in config_detector_pairs:
            with self.subTest(config_type=config_type):
                self.assertTrue(is_dataclass(config_type))
                self.assertFalse(hasattr(config_type, "detect"))
                self.assertEqual(config_type.__module__, detector_type.__module__)

    def test_detector_implementations_are_not_dataclasses(self) -> None:
        detector_types = (
            MeanAbsoluteSimilarityDetector,
            TemplateMatchDetector,
            ColorRangeDetector,
            PhaseCorrelationDetector,
            DifferenceHashSimilarityDetector,
        )
        for detector_type in detector_types:
            with self.subTest(detector_type=detector_type):
                self.assertFalse(is_dataclass(detector_type))

    def test_detector_implementations_compare_by_configuration(self) -> None:
        equivalent_pairs = (
            (
                MeanAbsoluteSimilarityDetector(MeanAbsoluteSimilarityConfig(PATTERN)),
                MeanAbsoluteSimilarityDetector(MeanAbsoluteSimilarityConfig(PATTERN)),
            ),
            (
                TemplateMatchDetector(TemplateMatchConfig(PATTERN)),
                TemplateMatchDetector(TemplateMatchConfig(PATTERN)),
            ),
            (
                ColorRangeDetector(ColorRangeConfig((0,), (255,))),
                ColorRangeDetector(ColorRangeConfig((0,), (255,))),
            ),
            (
                PhaseCorrelationDetector(PhaseCorrelationConfig(PATTERN)),
                PhaseCorrelationDetector(PhaseCorrelationConfig(PATTERN)),
            ),
            (
                DifferenceHashSimilarityDetector(
                    DifferenceHashSimilarityConfig(PATTERN)
                ),
                DifferenceHashSimilarityDetector(
                    DifferenceHashSimilarityConfig(PATTERN)
                ),
            ),
        )
        for first, second in equivalent_pairs:
            with self.subTest(detector_type=type(first)):
                self.assertEqual(first, second)
                self.assertEqual(hash(first), hash(second))
                with self.assertRaises(AttributeError):
                    assign_attribute(first, "config", None)

    def test_equivalent_configurations_share_detection_cache(self) -> None:
        reference = ((0, 0), (0, 0))
        config = MeanAbsoluteSimilarityConfig(reference)
        detector = MeanAbsoluteSimilarityDetector(config)
        equivalent = MeanAbsoluteSimilarityDetector(
            MeanAbsoluteSimilarityConfig(reference)
        )
        self.assertIs(detector.config, config)
        self.assertEqual(hash(detector), hash(equivalent))
        context = make_context(np.zeros((2, 2), dtype=np.uint8))
        first = evaluate(context, detector)
        second = evaluate(context, equivalent)
        self.assertIs(first, second)

    def test_configuration_requires_frozen_reference(self) -> None:
        with self.assertRaises(ValueError):
            MeanAbsoluteSimilarityConfig(cast(FrozenConfigImage, [[0, 0], [0, 0]]))

    def test_freezes_color_image(self) -> None:
        frozen = freeze_config_image([[[0, 1, 2], [3, 4, 5]]])
        self.assertEqual(frozen, (((0, 1, 2), (3, 4, 5)),))
        hash(frozen)

    def test_rejects_invalid_config_images(self) -> None:
        for image in ([], [[], []], [[0], [0, 1]], [[float("inf")]], [["x"]]):
            with self.subTest(image=image), self.assertRaises(ValueError):
                freeze_config_image(cast(ConfigImage, image))
