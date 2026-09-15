import numpy as np
import pytest
from divergencesplitter_ui.frame_preview import (
    MAX_PREVIEW_HEIGHT,
    MAX_PREVIEW_WIDTH,
    PreviewSize,
    fit_preview,
    prepare_preview,
    preview_size,
)


def test_fit_preview_preserves_aspect_ratio() -> None:
    assert fit_preview(1920, 1080, 700, 500) == PreviewSize(700, 394, 700 / 1920)


def test_fit_preview_handles_empty_region() -> None:
    assert fit_preview(1920, 1080, 0, 500) == PreviewSize(0, 0, 0.0)


@pytest.mark.parametrize("frame_size", [(1920, 1080), (1280, 720), (640, 360)])
def test_fit_preview_16_by_9_fills_fixed_preview(frame_size: tuple[int, int]) -> None:
    assert fit_preview(*frame_size, 480, 270) == PreviewSize(
        480, 270, 480 / frame_size[0]
    )


def test_fit_preview_4_by_3_fits_inside_fixed_preview() -> None:
    result = fit_preview(640, 480, 480, 270)

    assert result == PreviewSize(360, 270, 270 / 480)


class TestPreviewSize:
    @pytest.mark.parametrize(
        ("frame_size", "expected"),
        [
            ((1920, 1080), (384, 216)),
            ((640, 480), (288, 216)),
            ((2520, 1080), (504, 216)),
        ],
    )
    def test_expected_flet_preview_sizes(
        self, frame_size: tuple[int, int], expected: tuple[int, int]
    ) -> None:
        result = preview_size(*frame_size)

        assert (result.width, result.height) == expected

    def test_preserves_aspect_ratio(self) -> None:
        result = preview_size(1920, 1080)

        assert result.width / result.height == pytest.approx(1920 / 1080)

    def test_smaller_than_maximum_is_not_upscaled(self) -> None:
        assert preview_size(160, 120) == PreviewSize(160, 120, 1.0)

    def test_stays_within_both_maximums_for_extreme_wide_frame(self) -> None:
        result = preview_size(4000, 100)

        assert result.width <= MAX_PREVIEW_WIDTH
        assert result.height <= MAX_PREVIEW_HEIGHT

    def test_empty_dimension_yields_zero_size(self) -> None:
        assert preview_size(0, 1080) == PreviewSize(0, 0, 0.0)


class TestPreparePreview:
    def test_downscales_to_contiguous_uint8_rgb(self) -> None:
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        preview = prepare_preview(frame)

        assert preview.shape == (216, 384, 3)
        assert preview.dtype == np.uint8
        assert preview.flags["C_CONTIGUOUS"]

    def test_converts_bgr_to_rgb(self) -> None:
        frame = np.zeros((1, 1, 3), dtype=np.uint8)
        frame[0, 0] = (10, 20, 30)  # OpenCV BGR order

        preview = prepare_preview(frame)

        assert tuple(preview[0, 0]) == (30, 20, 10)

    def test_grayscale_expands_to_three_channels(self) -> None:
        frame = np.full((2, 2), 128, dtype=np.uint8)

        preview = prepare_preview(frame)

        assert preview.shape == (2, 2, 3)
        assert np.all(preview == 128)

    def test_source_frame_is_not_modified(self) -> None:
        frame = np.random.default_rng(0).integers(
            0, 256, size=(100, 200, 3), dtype=np.uint8
        )
        snapshot = frame.copy()

        prepare_preview(frame)

        assert np.array_equal(frame, snapshot)
