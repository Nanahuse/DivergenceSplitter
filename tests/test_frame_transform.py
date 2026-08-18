import cv2
import numpy as np
import pytest

from divergencesplitter import FrameCropResize
from divergencesplitter.detector.common import evaluate
from divergencesplitter.detector.mean_brightness import MeanBrightnessDetector
from divergencesplitter.models import Frame, FrameContext, MonotonicTime

EPOCH = MonotonicTime(nanoseconds=0)


def grayscale():
    return np.arange(6 * 8, dtype=np.uint8).reshape(6, 8)


def color():
    source = np.zeros((6, 8, 3), dtype=np.uint8)
    source[:, :, 0] = np.arange(48).reshape(6, 8)
    source[:, :, 1] = np.arange(48).reshape(6, 8) + 100
    source[:, :, 2] = 200
    return source


class TestApply:
    def test_crop_preserves_region_pixels_when_size_matches_region(self):
        source = grayscale()
        transform = FrameCropResize(region=(2, 1, 3, 2), size=(3, 2))
        result = transform.apply(Frame(image=source))
        np.testing.assert_array_equal(result.image, source[1:3, 2:5])

    def test_crop_preserves_region_pixels_with_channels(self):
        source = color()
        transform = FrameCropResize(region=(2, 1, 3, 2), size=(3, 2))
        result = transform.apply(Frame(image=source))
        np.testing.assert_array_equal(result.image, source[1:3, 2:5])

    def test_resize_returns_requested_size(self):
        source = grayscale()
        transform = FrameCropResize(region=(0, 0, 8, 6), size=(4, 2))
        result = transform.apply(Frame(image=source))
        assert result.image.shape == (2, 4)

    def test_resize_matches_cv2_inter_linear_grayscale(self):
        source = grayscale()
        transform = FrameCropResize(region=(2, 1, 3, 2), size=(6, 4))
        result = transform.apply(Frame(image=source))
        expected = cv2.resize(source[1:3, 2:5], (6, 4), interpolation=cv2.INTER_LINEAR)
        np.testing.assert_array_equal(result.image, expected)

    def test_resize_matches_cv2_inter_linear_with_channels(self):
        source = color()
        transform = FrameCropResize(region=(0, 0, 8, 6), size=(3, 2))
        result = transform.apply(Frame(image=source))
        expected = cv2.resize(source, (3, 2), interpolation=cv2.INTER_LINEAR)
        np.testing.assert_array_equal(result.image, expected)

    def test_channels_are_preserved_after_resize(self):
        source = color()
        transform = FrameCropResize(region=(2, 1, 3, 2), size=(6, 4))
        result = transform.apply(Frame(image=source))
        assert result.image.shape == (4, 6, 3)

    def test_input_image_is_unchanged(self):
        source = grayscale()
        before = source.copy()
        transform = FrameCropResize(region=(2, 1, 3, 2), size=(6, 4))
        transform.apply(Frame(image=source))
        np.testing.assert_array_equal(source, before)

    def test_input_frame_is_unchanged(self):
        source = grayscale()
        frame = Frame(image=source)
        transform = FrameCropResize(region=(2, 1, 3, 2), size=(6, 4))
        result = transform.apply(frame)
        assert frame.image is source
        assert result.image is not source
        np.testing.assert_array_equal(frame.image, source)

    def test_result_does_not_share_memory_with_input(self):
        source = grayscale()
        transform = FrameCropResize(region=(2, 1, 3, 2), size=(6, 4))
        result = transform.apply(Frame(image=source))
        assert result.image is not source
        assert not np.shares_memory(result.image, source)


class TestConstruction:
    @pytest.mark.parametrize(
        "region",
        [
            (-1, 0, 2, 2),
            (0, -1, 2, 2),
            (0, 0, 0, 2),
            (0, 0, -1, 2),
            (0, 0, 2, 0),
            (0, 0, 2, -1),
        ],
    )
    def test_region_rejects_negative_or_non_positive(self, region):
        with pytest.raises(ValueError):
            FrameCropResize(region=region, size=(2, 2))

    @pytest.mark.parametrize("size", [(0, 2), (2, 0), (-1, 2), (2, -1)])
    def test_size_rejects_non_positive(self, size):
        with pytest.raises(ValueError):
            FrameCropResize(region=(0, 0, 2, 2), size=size)


class TestApplyErrors:
    def test_region_must_fit_within_image_width(self):
        source = np.zeros((4, 4), dtype=np.uint8)
        transform = FrameCropResize(region=(1, 0, 4, 4), size=(4, 4))
        with pytest.raises(ValueError):
            transform.apply(Frame(image=source))

    def test_region_must_fit_within_image_height(self):
        source = np.zeros((4, 4), dtype=np.uint8)
        transform = FrameCropResize(region=(0, 1, 4, 4), size=(4, 4))
        with pytest.raises(ValueError):
            transform.apply(Frame(image=source))

    def test_exact_fit_is_allowed(self):
        source = np.zeros((4, 4), dtype=np.uint8)
        transform = FrameCropResize(region=(0, 0, 4, 4), size=(4, 4))
        result = transform.apply(Frame(image=source))
        assert result.image.shape == (4, 4)

    def test_image_smaller_than_region_is_rejected(self):
        source = np.zeros((2, 3), dtype=np.uint8)
        transform = FrameCropResize(region=(0, 0, 3, 4), size=(2, 2))
        with pytest.raises(ValueError):
            transform.apply(Frame(image=source))

    def test_image_without_height_and_width_is_rejected(self):
        source = np.zeros(4, dtype=np.uint8)
        transform = FrameCropResize(region=(0, 0, 2, 2), size=(2, 2))
        with pytest.raises(ValueError):
            transform.apply(Frame(image=source))


class TestDetectorIntegration:
    def test_detector_evaluates_transformed_image(self):
        source = grayscale()
        transform = FrameCropResize(region=(2, 1, 3, 2), size=(3, 2))
        transformed = transform.apply(Frame(image=source))
        context = FrameContext(frame=transformed, now=EPOCH)
        result = evaluate(context, MeanBrightnessDetector())
        assert result.score == float(np.mean(transformed.image))
        assert result.score != float(np.mean(source))
