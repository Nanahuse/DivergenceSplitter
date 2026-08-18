import unittest
from typing import cast

import cv2
import numpy as np

from divergencesplitter.detector.common import evaluate
from divergencesplitter.detector.frame_difference import FrameDifferenceDetector
from divergencesplitter.detector.mean_brightness import MeanBrightnessDetector
from divergencesplitter.frame_resize import resize_frame
from divergencesplitter.models import Frame, FrameContext, ImageArray, MonotonicTime

EPOCH = MonotonicTime(nanoseconds=0)
GRAY = np.arange(6 * 8, dtype=np.uint8).reshape(6, 8)
COLOR = np.stack([GRAY, np.roll(GRAY, 1), np.roll(GRAY, 2)], axis=-1)


class ResizeFrameTest(unittest.TestCase):
    def test_grayscale_upscale_matches_cv2_inter_linear(self):
        size = (16, 12)
        result = resize_frame(Frame(image=GRAY), size)
        expected = cv2.resize(GRAY, size, interpolation=cv2.INTER_LINEAR)
        np.testing.assert_array_equal(result.image, expected)
        self.assertEqual(result.image.shape, (12, 16))

    def test_grayscale_downscale_matches_cv2_inter_linear(self):
        size = (4, 3)
        result = resize_frame(Frame(image=GRAY), size)
        expected = cv2.resize(GRAY, size, interpolation=cv2.INTER_LINEAR)
        np.testing.assert_array_equal(result.image, expected)
        self.assertEqual(result.image.shape, (3, 4))

    def test_color_upscale_matches_cv2_inter_linear(self):
        size = (16, 12)
        result = resize_frame(Frame(image=COLOR), size)
        expected = cv2.resize(COLOR, size, interpolation=cv2.INTER_LINEAR)
        np.testing.assert_array_equal(result.image, expected)
        self.assertEqual(result.image.shape, (12, 16, 3))

    def test_color_downscale_matches_cv2_inter_linear(self):
        size = (4, 3)
        result = resize_frame(Frame(image=COLOR), size)
        expected = cv2.resize(COLOR, size, interpolation=cv2.INTER_LINEAR)
        np.testing.assert_array_equal(result.image, expected)
        self.assertEqual(result.image.shape, (3, 4, 3))

    def test_input_frame_and_image_are_unchanged(self):
        frame = Frame(image=GRAY)
        original = GRAY.copy()
        resize_frame(frame, (16, 12))
        self.assertIs(frame.image, GRAY)
        np.testing.assert_array_equal(GRAY, original)

    def test_result_owns_data_and_shares_no_memory(self):
        result = resize_frame(Frame(image=GRAY), (4, 3))
        self.assertIsNot(result.image, GRAY)
        self.assertFalse(np.shares_memory(result.image, GRAY))
        self.assertTrue(result.image.flags.owndata)
        self.assertIsNone(result.image.base)

    def test_non_positive_size_rejected(self):
        frame = Frame(image=GRAY)
        for size in [(0, 2), (2, 0), (-1, 2), (2, -1)]:
            with self.subTest(size=size), self.assertRaises(ValueError):
                resize_frame(frame, size)

    def test_invalid_image_rejected(self):
        empty_height = np.zeros((0, 6), dtype=np.uint8)
        empty_width = np.zeros((4, 0), dtype=np.uint8)
        one_dim = np.zeros((4,), dtype=np.uint8)
        for image in [empty_height, empty_width, one_dim]:
            with self.subTest(image=image), self.assertRaises(ValueError):
                resize_frame(Frame(image=image), (2, 2))

    def test_non_ndarray_image_rejected(self):
        image = cast(ImageArray, [[1, 2], [3, 4]])
        with self.assertRaises(ValueError):
            resize_frame(Frame(image=image), (2, 2))

    def test_returns_new_result_on_every_call(self):
        frame = Frame(image=GRAY)
        first = resize_frame(frame, (4, 3))
        second = resize_frame(frame, (4, 3))
        self.assertIsNot(first, second)
        self.assertIsNot(first.image, second.image)
        np.testing.assert_array_equal(first.image, second.image)


class ResizeWithDetectorTest(unittest.TestCase):
    def test_detectors_read_same_resized_frame_without_resize_cache(self):
        size = (4, 3)
        resized = resize_frame(Frame(image=GRAY), size)
        expected = cv2.resize(GRAY, size, interpolation=cv2.INTER_LINEAR)
        reference = tuple(tuple(int(v) for v in row) for row in expected)
        context = FrameContext(frame=resized, now=EPOCH)
        mean_result = evaluate(context, MeanBrightnessDetector())
        diff_result = evaluate(context, FrameDifferenceDetector(reference=reference))
        self.assertEqual(mean_result.score, float(np.mean(expected)))
        self.assertEqual(diff_result.score, 0.0)
        self.assertIs(context.frame, resized)
        self.assertEqual(
            [
                key
                for key in context.preprocessing_cache
                if isinstance(key, tuple) and key and key[0] == "frame-resize"
            ],
            [],
        )
        self.assertNotIn("frame-resize", context.preprocessing_cache)
