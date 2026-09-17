from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import flet as ft
import numpy as np
import pytest
from divergencesplitter_ui.frame_preview import (
    MAX_PREVIEW_HEIGHT,
    MAX_PREVIEW_WIDTH,
    PreviewSize,
    prepare_preview,
    preview_size,
)
from divergencesplitter_ui.monitor.input_preview import (
    PREVIEW_FPS,
    PREVIEW_INTERVAL_SECONDS,
    InputPreviewPanel,
)
from divergencesplitter_ui.presentation import ObservableDiagnostics


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
    def test_downscales_to_contiguous_uint8_rgba(self) -> None:
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        preview = prepare_preview(frame)

        assert preview.shape == (216, 384, 4)
        assert preview.dtype == np.uint8
        assert preview.flags["C_CONTIGUOUS"]

    def test_converts_bgr_to_rgba(self) -> None:
        frame = np.zeros((1, 1, 3), dtype=np.uint8)
        frame[0, 0] = (10, 20, 30)  # OpenCV BGR order

        preview = prepare_preview(frame)

        assert tuple(preview[0, 0]) == (30, 20, 10, 255)

    def test_three_channel_alpha_is_opaque(self) -> None:
        frame = np.full((4, 4, 3), 7, dtype=np.uint8)

        preview = prepare_preview(frame)

        assert np.all(preview[:, :, 3] == 255)
        assert np.all(preview[:, :, :3] == 7)

    def test_grayscale_expands_to_four_channels(self) -> None:
        frame = np.full((2, 2), 128, dtype=np.uint8)

        preview = prepare_preview(frame)

        assert preview.shape == (2, 2, 4)
        assert np.all(preview[:, :, :3] == 128)
        assert np.all(preview[:, :, 3] == 255)

    def test_singleton_channel_grayscale_expands_to_four_channels(self) -> None:
        frame = np.full((2, 2, 1), 64, dtype=np.uint8)

        preview = prepare_preview(frame)

        assert preview.shape == (2, 2, 4)
        assert np.all(preview[:, :, :3] == 64)
        assert np.all(preview[:, :, 3] == 255)

    def test_bgra_keeps_alpha_and_swaps_to_rgba(self) -> None:
        frame = np.zeros((1, 1, 4), dtype=np.uint8)
        frame[0, 0] = (10, 20, 30, 40)  # OpenCV BGRA order

        preview = prepare_preview(frame)

        assert tuple(preview[0, 0]) == (30, 20, 10, 40)

    def test_small_frame_is_not_upscaled_but_still_rgba(self) -> None:
        frame = np.zeros((2, 3, 3), dtype=np.uint8)

        preview = prepare_preview(frame)

        assert preview.shape == (2, 3, 4)

    def test_source_frame_is_not_modified(self) -> None:
        frame = np.random.default_rng(0).integers(
            0, 256, size=(100, 200, 3), dtype=np.uint8
        )
        snapshot = frame.copy()

        prepare_preview(frame)

        assert np.array_equal(frame, snapshot)


class TestPreviewCadence:
    def test_monitor_preview_runs_at_15_hz(self) -> None:
        assert PREVIEW_FPS == 15.0
        assert PREVIEW_INTERVAL_SECONDS == pytest.approx(1.0 / 15.0)


class FakeRawImage:
    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []
        self.premultiplied: list[bool] = []

    async def render(self, image: np.ndarray, *, premultiplied: bool = False) -> None:
        self.frames.append(image)
        self.premultiplied.append(premultiplied)


class FakeDiagnostics:
    def __init__(self, image: np.ndarray | None) -> None:
        self._image = image

    def take_latest_processed_frame(self):
        if self._image is None:
            return None
        return SimpleNamespace(image=self._image)


class TestInputPreviewRender:
    def test_renders_contiguous_rgba_as_premultiplied(self) -> None:
        panel = InputPreviewPanel()
        fake = FakeRawImage()
        panel._image = cast(ft.RawImage, fake)
        frame = np.full((4, 6, 3), 33, dtype=np.uint8)

        rendered = asyncio.run(
            panel.render_latest(cast(ObservableDiagnostics, FakeDiagnostics(frame)))
        )

        assert rendered is True
        assert len(fake.frames) == 1
        image = fake.frames[0]
        assert image.shape == (4, 6, 4)
        assert image.dtype == np.uint8
        assert image.flags["C_CONTIGUOUS"]
        assert fake.premultiplied == [True]

    def test_no_frame_does_not_render(self) -> None:
        panel = InputPreviewPanel()
        fake = FakeRawImage()
        panel._image = cast(ft.RawImage, fake)

        rendered = asyncio.run(
            panel.render_latest(cast(ObservableDiagnostics, FakeDiagnostics(None)))
        )

        assert rendered is False
        assert fake.frames == []
