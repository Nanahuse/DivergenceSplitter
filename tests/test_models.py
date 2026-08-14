import unittest

import numpy as np

from divergencesplitter.models import DetectionSample, Frame, FrameContext

KNOWN_IMAGE = np.zeros((2, 2), dtype=np.uint8)


class FrameTest(unittest.TestCase):
    def test_frame_holds_image_only(self):
        frame = Frame(image=KNOWN_IMAGE)
        self.assertIs(frame.image, KNOWN_IMAGE)
        self.assertFalse(hasattr(frame, "timestamp"))
        self.assertFalse(hasattr(frame, "time"))
        self.assertFalse(hasattr(frame, "sequence"))
        self.assertFalse(hasattr(frame, "now"))

    def test_frame_is_frozen(self):
        self.assertTrue(Frame.__dataclass_params__.frozen)

    def test_frame_image_is_ndarray(self):
        self.assertIsInstance(Frame(image=KNOWN_IMAGE).image, np.ndarray)

    def test_frame_has_stable_image_value(self):
        frame = Frame(image=np.zeros((2, 2), dtype=np.uint8))
        equivalent = Frame(image=np.zeros((2, 2), dtype=np.uint8))
        self.assertTrue(np.array_equal(frame.image, equivalent.image))


class DetectionSampleTest(unittest.TestCase):
    def test_sample_is_frozen(self):
        self.assertTrue(DetectionSample.__dataclass_params__.frozen)

    def test_score_is_optional(self):
        self.assertIsNone(DetectionSample(matched=False).score)


class FrameContextTest(unittest.TestCase):
    def test_caches_default_to_empty(self):
        context = FrameContext(frame=Frame(KNOWN_IMAGE), now=1.0)
        self.assertEqual(context.preprocessing_cache, {})
        self.assertEqual(context.detection_cache, {})

    def test_caches_are_not_shared_between_contexts(self):
        first = FrameContext(frame=Frame(KNOWN_IMAGE), now=1.0)
        second = FrameContext(frame=Frame(KNOWN_IMAGE), now=2.0)
        first.preprocessing_cache["x"] = 1
        first.detection_cache["y"] = DetectionSample(matched=True)
        self.assertNotIn("x", second.preprocessing_cache)
        self.assertNotIn("y", second.detection_cache)
