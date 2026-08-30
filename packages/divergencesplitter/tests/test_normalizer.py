import cv2
import numpy as np
import pytest
from divergencesplitter.clock import MonotonicTime
from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.normalizer import (
    ClipRegion,
    FrameClipError,
    FrameNormalizationError,
    FrameNormalizer,
    FrameResizeError,
    OutputSize,
)

SIZE = (16, 16)
CAPTURED_AT = MonotonicTime(123)


def make_pattern_image(width=16, height=16):
    stripe = np.array(
        [[row // 2 * 30 for _ in range(width)] for row in range(height)],
        dtype=np.uint8,
    )
    return np.stack([stripe, stripe, stripe], axis=-1)


def make_frame(image=None) -> Frame:
    if image is None:
        image = make_pattern_image()
    return Frame(image=image, captured_at=CAPTURED_AT)


class TestConstruction:
    @pytest.mark.parametrize(
        "values",
        [
            {"x": -1, "y": 0, "width": 2, "height": 2},
            {"x": 0, "y": -1, "width": 2, "height": 2},
            {"x": 0, "y": 0, "width": 0, "height": 2},
            {"x": 0, "y": 0, "width": -1, "height": 2},
            {"x": 0, "y": 0, "width": 2, "height": 0},
            {"x": 0, "y": 0, "width": 2, "height": -1},
        ],
    )
    def test_clip_region_rejects_negative_or_non_positive(self, values):
        with pytest.raises(ValueError):
            ClipRegion(**values)

    @pytest.mark.parametrize(
        "values",
        [
            {"width": 0, "height": 2},
            {"width": 2, "height": 0},
            {"width": -1, "height": 2},
            {"width": 2, "height": -1},
        ],
    )
    def test_output_size_rejects_non_positive(self, values):
        with pytest.raises(ValueError):
            OutputSize(**values)


class TestNoTransform:
    def test_no_settings_returns_same_frame(self):
        normalizer = FrameNormalizer()
        frame = make_frame()
        assert normalizer.normalize(frame) is frame


class TestClip:
    def test_clip_returns_clipped_shape(self):
        region = ClipRegion(x=2, y=3, width=6, height=5)
        normalizer = FrameNormalizer(clip_region=region)
        result = normalizer.normalize(make_frame())
        assert isinstance(result, Frame)
        assert result.image.shape == (region.height, region.width, 3)
        assert result.captured_at == CAPTURED_AT

    def test_clip_matches_manual_slice_of_full_frame(self):
        region = ClipRegion(x=2, y=3, width=6, height=5)
        normalizer = FrameNormalizer(clip_region=region)
        image = make_pattern_image()
        result = normalizer.normalize(make_frame(image))
        assert isinstance(result, Frame)
        expected = image[
            region.y : region.y + region.height,
            region.x : region.x + region.width,
        ]
        np.testing.assert_array_equal(result.image, expected)

    def test_clipped_frame_owns_its_data(self):
        normalizer = FrameNormalizer(
            clip_region=ClipRegion(x=0, y=0, width=8, height=8)
        )
        result = normalizer.normalize(make_frame())
        assert isinstance(result, Frame)
        assert result.image.flags.owndata
        assert result.image.base is None

    def test_horizontal_overflow_returns_clip_error(self):
        normalizer = FrameNormalizer(
            clip_region=ClipRegion(x=1, y=0, width=16, height=16)
        )
        result = normalizer.normalize(make_frame())
        assert isinstance(result, FrameClipError)
        assert isinstance(result, FrameNormalizationError)

    def test_vertical_overflow_returns_clip_error(self):
        normalizer = FrameNormalizer(
            clip_region=ClipRegion(x=0, y=1, width=16, height=16)
        )
        result = normalizer.normalize(make_frame())
        assert isinstance(result, FrameClipError)
        assert isinstance(result, FrameNormalizationError)


class TestResize:
    def test_resize_matches_cv2_inter_linear(self):
        size = OutputSize(width=12, height=10)
        normalizer = FrameNormalizer(output_size=size)
        image = make_pattern_image()
        result = normalizer.normalize(make_frame(image))
        assert isinstance(result, Frame)
        expected = cv2.resize(
            image, (size.width, size.height), interpolation=cv2.INTER_LINEAR
        )
        np.testing.assert_array_equal(result.image, expected)

    def test_clip_and_resize_match_cv2_inter_linear_on_manual_clip(self):
        region = ClipRegion(x=2, y=3, width=6, height=5)
        size = OutputSize(width=12, height=10)
        normalizer = FrameNormalizer(clip_region=region, output_size=size)
        image = make_pattern_image()
        result = normalizer.normalize(make_frame(image))
        assert isinstance(result, Frame)
        assert result.captured_at == CAPTURED_AT
        manual_clip = image[
            region.y : region.y + region.height,
            region.x : region.x + region.width,
        ]
        expected = cv2.resize(
            manual_clip, (size.width, size.height), interpolation=cv2.INTER_LINEAR
        )
        np.testing.assert_array_equal(result.image, expected)

    def test_resized_frame_owns_its_data(self):
        normalizer = FrameNormalizer(output_size=OutputSize(width=12, height=10))
        result = normalizer.normalize(make_frame())
        assert isinstance(result, Frame)
        assert result.image.flags.owndata
        assert result.image.base is None

    def test_clipped_and_resized_frame_owns_its_data(self):
        normalizer = FrameNormalizer(
            clip_region=ClipRegion(x=0, y=0, width=8, height=8),
            output_size=OutputSize(width=12, height=10),
        )
        result = normalizer.normalize(make_frame())
        assert isinstance(result, Frame)
        assert result.image.flags.owndata
        assert result.image.base is None

    def test_shapes_are_constant_across_frames(self):
        region = ClipRegion(x=2, y=3, width=6, height=5)
        size = OutputSize(width=12, height=10)
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
                result = normalizer.normalize(make_frame())
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
        normalizer = FrameNormalizer(output_size=OutputSize(width=12, height=10))
        result = normalizer.normalize(make_frame())
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
        result = normalizer.normalize(make_frame())
        assert isinstance(result, Frame)
        assert calls["count"] == 0


class TestResizeError:
    def test_resize_failure_returned_as_value(self, monkeypatch):
        def raise_resize_error(*args, **kwargs):
            raise cv2.error("resize failed")

        monkeypatch.setattr(cv2, "resize", raise_resize_error)
        normalizer = FrameNormalizer(output_size=OutputSize(width=12, height=10))
        result = normalizer.normalize(make_frame())
        assert isinstance(result, FrameResizeError)
        assert isinstance(result, FrameNormalizationError)
