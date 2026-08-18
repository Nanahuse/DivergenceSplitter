import cv2
import numpy as np
import pytest

from divergencesplitter.frame_normalizer import (
    FrameClipError,
    FrameNormalizationError,
    FrameNormalizer,
    FrameResizeError,
)
from divergencesplitter.models import Frame

SIZE = (16, 16)


def make_pattern_image(width=16, height=16):
    stripe = np.array(
        [[row // 2 * 30 for _ in range(width)] for row in range(height)],
        dtype=np.uint8,
    )
    return np.stack([stripe, stripe, stripe], axis=-1)


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
            FrameNormalizer(clip_region=region)

    @pytest.mark.parametrize(
        "size",
        [
            (0, 2),
            (2, 0),
            (-1, 2),
            (2, -1),
        ],
    )
    def test_output_size_rejects_non_positive(self, size):
        with pytest.raises(ValueError):
            FrameNormalizer(output_size=size)


class TestNoTransform:
    def test_no_settings_returns_same_frame(self):
        normalizer = FrameNormalizer()
        frame = Frame(image=make_pattern_image())
        assert normalizer.normalize(frame) is frame


class TestClip:
    def test_clip_returns_clipped_shape(self):
        region = (2, 3, 6, 5)
        normalizer = FrameNormalizer(clip_region=region)
        result = normalizer.normalize(Frame(image=make_pattern_image()))
        assert isinstance(result, Frame)
        _, _, width, height = region
        assert result.image.shape == (height, width, 3)

    def test_clip_matches_manual_slice_of_full_frame(self):
        region = (2, 3, 6, 5)
        normalizer = FrameNormalizer(clip_region=region)
        image = make_pattern_image()
        result = normalizer.normalize(Frame(image=image))
        assert isinstance(result, Frame)
        x, y, width, height = region
        expected = image[y : y + height, x : x + width]
        np.testing.assert_array_equal(result.image, expected)

    def test_clipped_frame_owns_its_data(self):
        normalizer = FrameNormalizer(clip_region=(0, 0, 8, 8))
        result = normalizer.normalize(Frame(image=make_pattern_image()))
        assert isinstance(result, Frame)
        assert result.image.flags.owndata
        assert result.image.base is None

    def test_horizontal_overflow_returns_clip_error(self):
        normalizer = FrameNormalizer(clip_region=(1, 0, 16, 16))
        result = normalizer.normalize(Frame(image=make_pattern_image()))
        assert isinstance(result, FrameClipError)
        assert isinstance(result, FrameNormalizationError)

    def test_vertical_overflow_returns_clip_error(self):
        normalizer = FrameNormalizer(clip_region=(0, 1, 16, 16))
        result = normalizer.normalize(Frame(image=make_pattern_image()))
        assert isinstance(result, FrameClipError)
        assert isinstance(result, FrameNormalizationError)


class TestResize:
    def test_resize_matches_cv2_inter_linear(self):
        size = (12, 10)
        normalizer = FrameNormalizer(output_size=size)
        image = make_pattern_image()
        result = normalizer.normalize(Frame(image=image))
        assert isinstance(result, Frame)
        expected = cv2.resize(image, size, interpolation=cv2.INTER_LINEAR)
        np.testing.assert_array_equal(result.image, expected)

    def test_clip_and_resize_match_cv2_inter_linear_on_manual_clip(self):
        region = (2, 3, 6, 5)
        size = (12, 10)
        normalizer = FrameNormalizer(clip_region=region, output_size=size)
        image = make_pattern_image()
        result = normalizer.normalize(Frame(image=image))
        assert isinstance(result, Frame)
        x, y, width, height = region
        manual_clip = image[y : y + height, x : x + width]
        expected = cv2.resize(manual_clip, size, interpolation=cv2.INTER_LINEAR)
        np.testing.assert_array_equal(result.image, expected)

    def test_resized_frame_owns_its_data(self):
        normalizer = FrameNormalizer(output_size=(12, 10))
        result = normalizer.normalize(Frame(image=make_pattern_image()))
        assert isinstance(result, Frame)
        assert result.image.flags.owndata
        assert result.image.base is None

    def test_clipped_and_resized_frame_owns_its_data(self):
        normalizer = FrameNormalizer(clip_region=(0, 0, 8, 8), output_size=(12, 10))
        result = normalizer.normalize(Frame(image=make_pattern_image()))
        assert isinstance(result, Frame)
        assert result.image.flags.owndata
        assert result.image.base is None

    def test_shapes_are_constant_across_frames(self):
        region = (2, 3, 6, 5)
        size = (12, 10)
        cases = [
            (None, None, (*SIZE, 3)),
            (region, None, (5, 6, 3)),
            (None, size, (10, 12, 3)),
            (region, size, (10, 12, 3)),
        ]
        for clip_region, output_size, expected_shape in cases:
            normalizer = FrameNormalizer(
                clip_region=clip_region, output_size=output_size
            )
            shapes = []
            for _ in range(3):
                result = normalizer.normalize(Frame(image=make_pattern_image()))
                assert isinstance(result, Frame)
                shapes.append(result.image.shape)
                assert result.image.shape[-1] == 3
            assert len(set(shapes)) == 1
            assert shapes[0] == expected_shape

    def test_normalize_calls_resize_once(self, monkeypatch):
        calls = {"count": 0}
        real_resize = cv2.resize

        def counting_resize(*args, **kwargs):
            calls["count"] += 1
            return real_resize(*args, **kwargs)

        monkeypatch.setattr(cv2, "resize", counting_resize)
        normalizer = FrameNormalizer(output_size=(12, 10))
        result = normalizer.normalize(Frame(image=make_pattern_image()))
        assert isinstance(result, Frame)
        assert calls["count"] == 1

    def test_no_transform_does_not_call_resize(self, monkeypatch):
        calls = {"count": 0}
        real_resize = cv2.resize

        def counting_resize(*args, **kwargs):
            calls["count"] += 1
            return real_resize(*args, **kwargs)

        monkeypatch.setattr(cv2, "resize", counting_resize)
        normalizer = FrameNormalizer()
        result = normalizer.normalize(Frame(image=make_pattern_image()))
        assert isinstance(result, Frame)
        assert calls["count"] == 0


class TestResizeError:
    def test_resize_failure_returned_as_value(self, monkeypatch):
        def raise_resize_error(*args, **kwargs):
            raise cv2.error("resize failed")

        monkeypatch.setattr(cv2, "resize", raise_resize_error)
        normalizer = FrameNormalizer(output_size=(12, 10))
        result = normalizer.normalize(Frame(image=make_pattern_image()))
        assert isinstance(result, FrameResizeError)
        assert isinstance(result, FrameNormalizationError)
