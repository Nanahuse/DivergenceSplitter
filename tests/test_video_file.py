import time
from typing import get_protocol_members

import cv2
import numpy as np
import pytest

from divergencesplitter.frame_source import (
    ErrorAction,
    FrameSource,
    FrameSourceState,
)
from divergencesplitter.models import Frame
from divergencesplitter.video_file import (
    VideoFileClipError,
    VideoFileDecodeError,
    VideoFileEndOfFileError,
    VideoFileError,
    VideoFileOpenError,
    VideoFileReadBeforeReadyError,
    VideoFileResizeError,
    VideoFileSource,
)

SIZE = (16, 16)


def _fourcc(code: str) -> int:
    return cv2.VideoWriter_fourcc(*code)  # type: ignore


def make_video(path, frame_count, fps=30.0, width=16, height=16):
    writer = cv2.VideoWriter(str(path), _fourcc("MJPG"), fps, (width, height))
    assert writer.isOpened(), "could not create the test video with the MJPG codec"
    try:
        for index in range(frame_count):
            image = np.full((height, width, 3), index * 85 % 255, dtype=np.uint8)
            writer.write(image)
    finally:
        writer.release()


def make_pattern_video(path, frame_count, width=16, height=16):
    writer = cv2.VideoWriter(str(path), _fourcc("MJPG"), 30.0, (width, height))
    assert writer.isOpened(), "could not create the test video with the MJPG codec"
    try:
        stripe = np.array(
            [[row // 2 * 30 for _ in range(width)] for row in range(height)],
            dtype=np.uint8,
        )
        for _ in range(frame_count):
            image = np.stack([stripe, stripe, stripe], axis=-1)
            writer.write(image)
    finally:
        writer.release()


class TestState:
    def test_initial_state_is_not_ready(self, tmp_path):
        source = VideoFileSource(str(tmp_path / "movie.avi"))
        assert source.state is FrameSourceState.NOT_READY

    def test_prepare_success_moves_to_ready(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=2)
        source = VideoFileSource(str(video))
        assert source.prepare() is None
        assert source.state is FrameSourceState.READY

    def test_prepare_failure_returns_to_not_ready(self, tmp_path):
        source = VideoFileSource(str(tmp_path / "missing.avi"))
        assert isinstance(source.prepare(), VideoFileOpenError)
        assert source.state is FrameSourceState.NOT_READY

    def test_prepare_is_idempotent_when_ready(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=2)
        source = VideoFileSource(str(video))
        assert source.prepare() is None
        assert source.prepare() is None
        assert source.state is FrameSourceState.READY

    def test_retry_after_failed_prepare(self, tmp_path):
        missing = tmp_path / "missing.avi"
        source = VideoFileSource(str(missing))
        assert isinstance(source.prepare(), VideoFileOpenError)
        make_video(missing, frame_count=1)
        assert source.prepare() is None
        assert source.state is FrameSourceState.READY


class TestRead:
    def test_read_returns_frame_after_prepare(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=2)
        source = VideoFileSource(str(video))
        source.prepare()
        result = source.read()
        assert isinstance(result, Frame)
        assert result.image.shape == (*SIZE, 3)
        assert int(result.image[0, 0, 0]) == 0

    def test_read_before_ready_is_source_error(self, tmp_path):
        source = VideoFileSource(str(tmp_path / "movie.avi"))
        assert isinstance(source.read(), VideoFileReadBeforeReadyError)

    def test_read_after_close_is_source_error(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video))
        source.prepare()
        source.close()
        assert isinstance(source.read(), VideoFileReadBeforeReadyError)

    def test_frames_follow_recording_order(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=3)
        source = VideoFileSource(str(video))
        source.prepare()
        values = []
        for _ in range(3):
            result = source.read()
            assert isinstance(result, Frame)
            values.append(int(result.image[0, 0, 0]))
        assert values[0] < values[1] < values[2]


class TestError:
    def test_handle_error_returns_stop_for_all_video_errors(self):
        source = VideoFileSource("unused.avi")
        errors = (
            VideoFileOpenError("open"),
            VideoFileEndOfFileError("eof"),
            VideoFileDecodeError("decode"),
            VideoFileReadBeforeReadyError("not ready"),
            VideoFileClipError("clip"),
            VideoFileResizeError("resize"),
        )
        for error in errors:
            assert source.handle_error(error) is ErrorAction.STOP


class TestEof:
    def test_eof_returned_after_last_frame(self, tmp_path):
        video = tmp_path / "movie.avi"
        frame_count = 3
        make_video(video, frame_count=frame_count)
        source = VideoFileSource(str(video))
        source.prepare()
        frames = 0
        while True:
            result = source.read()
            if isinstance(result, VideoFileError):
                assert isinstance(result, VideoFileEndOfFileError)
                break
            assert isinstance(result, Frame)
            frames += 1
        assert frames == frame_count

    def test_eof_does_not_change_common_state(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video))
        source.prepare()
        assert isinstance(source.read(), Frame)
        assert isinstance(source.read(), VideoFileEndOfFileError)
        assert source.state is FrameSourceState.READY

    def test_eof_repeats_on_further_reads(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video))
        source.prepare()
        assert isinstance(source.read(), Frame)
        assert isinstance(source.read(), VideoFileEndOfFileError)
        assert isinstance(source.read(), VideoFileEndOfFileError)


class TestContextManager:
    def test_enter_does_not_prepare(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video))
        with source:
            assert source.state is FrameSourceState.NOT_READY

    def test_exit_closes_on_normal_exit(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video))
        source.prepare()
        with source:
            assert source.state is FrameSourceState.READY
        assert source.state is FrameSourceState.NOT_READY

    def test_exit_closes_on_exception(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video))
        source.prepare()
        with pytest.raises(RuntimeError), source:
            raise RuntimeError("boom")
        assert source.state is FrameSourceState.NOT_READY

    def test_close_is_idempotent(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video))
        source.prepare()
        source.close()
        source.close()
        assert source.state is FrameSourceState.NOT_READY
        assert source.read() is not None


class TestProtocol:
    def test_video_file_source_satisfies_frame_source(self):
        members = get_protocol_members(FrameSource)
        assert "state" in members
        source = VideoFileSource("unused.avi")
        for member in members:
            assert hasattr(source, member), member


class TestPacing:
    def test_read_paces_at_recorded_fps(self, tmp_path):
        fps = 60.0
        frame_count = 6
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=frame_count, fps=fps)
        source = VideoFileSource(str(video))
        source.prepare()
        start = time.monotonic()
        for _ in range(frame_count):
            result = source.read()
            assert isinstance(result, Frame)
        elapsed = time.monotonic() - start
        expected = (frame_count - 1) / fps
        assert elapsed >= expected, "frames were delivered faster than real time"
        assert elapsed < (2 * frame_count + 1) / fps, "frames were delivered too slowly"

    def test_pacing_is_relative_to_recorded_fps(self, tmp_path):
        fps = 30.0
        frame_count = 4
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=frame_count, fps=fps)
        source = VideoFileSource(str(video))
        source.prepare()
        start = time.monotonic()
        for _ in range(frame_count):
            result = source.read()
            assert isinstance(result, Frame)
        elapsed = time.monotonic() - start
        assert elapsed >= (frame_count - 1) / fps


class TestDecodeError:
    def test_truncated_file_reports_decode_error(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=20)
        raw = video.read_bytes()
        truncated = tmp_path / "truncated.avi"
        truncated.write_bytes(raw[: int(len(raw) * 0.7)])
        source = VideoFileSource(str(truncated))
        prepare_error = source.prepare()
        if prepare_error is not None:
            pytest.skip("truncated file could not be opened by the backend")
        decoded = 0
        while True:
            result = source.read()
            if isinstance(result, VideoFileError):
                assert isinstance(result, VideoFileDecodeError)
                break
            assert isinstance(result, Frame)
            decoded += 1
        assert 0 < decoded < 20


class TestClipRegion:
    def test_clip_region_returns_clipped_shape(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_pattern_video(video, frame_count=2)
        region = (2, 3, 6, 5)
        source = VideoFileSource(str(video), clip_region=region)
        source.prepare()
        result = source.read()
        assert isinstance(result, Frame)
        _, _, width, height = region
        assert result.image.shape == (height, width, 3)

    def test_clip_matches_manual_slice_of_full_frame(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_pattern_video(video, frame_count=2)
        region = (2, 3, 6, 5)
        clipped = VideoFileSource(str(video), clip_region=region)
        full = VideoFileSource(str(video))
        clipped.prepare()
        full.prepare()
        clipped_result = clipped.read()
        full_result = full.read()
        assert isinstance(clipped_result, Frame)
        assert isinstance(full_result, Frame)
        x, y, width, height = region
        expected = full_result.image[y : y + height, x : x + width]
        np.testing.assert_array_equal(clipped_result.image, expected)

    def test_clipped_frame_owns_its_data(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_pattern_video(video, frame_count=1)
        source = VideoFileSource(str(video), clip_region=(0, 0, 8, 8))
        source.prepare()
        result = source.read()
        assert isinstance(result, Frame)
        assert result.image.flags.owndata
        assert result.image.base is None

    def test_default_clip_region_returns_full_frame(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video))
        source.prepare()
        result = source.read()
        assert isinstance(result, Frame)
        assert result.image.shape == (*SIZE, 3)

    def test_horizontal_overflow_returns_clip_error(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video), clip_region=(1, 0, 16, 16))
        source.prepare()
        result = source.read()
        assert isinstance(result, VideoFileClipError)
        assert isinstance(result, VideoFileError)

    def test_vertical_overflow_returns_clip_error(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video), clip_region=(0, 1, 16, 16))
        source.prepare()
        result = source.read()
        assert isinstance(result, VideoFileClipError)
        assert isinstance(result, VideoFileError)

    def test_overflow_does_not_raise(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video), clip_region=(1, 0, 16, 16))
        source.prepare()
        result = source.read()
        assert isinstance(result, VideoFileError)


class TestClipRegionConstruction:
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
            VideoFileSource("unused.avi", clip_region=region)


class TestOutputSizeConstruction:
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
            VideoFileSource("unused.avi", output_size=size)


class TestResize:
    def test_resize_matches_cv2_inter_linear_on_full_frame(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_pattern_video(video, frame_count=2)
        size = (12, 10)
        resized = VideoFileSource(str(video), output_size=size)
        full = VideoFileSource(str(video))
        resized.prepare()
        full.prepare()
        resized_result = resized.read()
        full_result = full.read()
        assert isinstance(resized_result, Frame)
        assert isinstance(full_result, Frame)
        expected = cv2.resize(full_result.image, size, interpolation=cv2.INTER_LINEAR)
        np.testing.assert_array_equal(resized_result.image, expected)

    def test_clip_and_resize_match_cv2_inter_linear_on_manual_clip(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_pattern_video(video, frame_count=2)
        region = (2, 3, 6, 5)
        size = (12, 10)
        transformed = VideoFileSource(str(video), clip_region=region, output_size=size)
        full = VideoFileSource(str(video))
        transformed.prepare()
        full.prepare()
        transformed_result = transformed.read()
        full_result = full.read()
        assert isinstance(transformed_result, Frame)
        assert isinstance(full_result, Frame)
        x, y, width, height = region
        manual_clip = full_result.image[y : y + height, x : x + width]
        expected = cv2.resize(manual_clip, size, interpolation=cv2.INTER_LINEAR)
        np.testing.assert_array_equal(transformed_result.image, expected)

    def test_four_combinations_have_expected_shapes(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=3)
        region = (2, 3, 6, 5)
        size = (12, 10)
        cases = [
            (None, None, (*SIZE, 3)),
            (region, None, (5, 6, 3)),
            (None, size, (10, 12, 3)),
            (region, size, (10, 12, 3)),
        ]
        for clip_region, output_size, expected_shape in cases:
            source = VideoFileSource(
                str(video), clip_region=clip_region, output_size=output_size
            )
            source.prepare()
            shapes = []
            for _ in range(3):
                result = source.read()
                assert isinstance(result, Frame)
                shapes.append(result.image.shape)
                assert result.image.shape[-1] == 3
            assert len(set(shapes)) == 1
            assert shapes[0] == expected_shape

    def test_multiple_reads_keep_output_shape_constant(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=3)
        source = VideoFileSource(
            str(video), clip_region=(1, 1, 8, 8), output_size=(12, 10)
        )
        source.prepare()
        shapes = []
        for _ in range(3):
            result = source.read()
            assert isinstance(result, Frame)
            shapes.append(result.image.shape)
        assert len(set(shapes)) == 1
        assert shapes[0] == (10, 12, 3)

    def test_resized_frame_owns_its_data(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_pattern_video(video, frame_count=1)
        source = VideoFileSource(str(video), output_size=(12, 10))
        source.prepare()
        result = source.read()
        assert isinstance(result, Frame)
        assert result.image.flags.owndata
        assert result.image.base is None

    def test_clipped_and_resized_frame_owns_its_data(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_pattern_video(video, frame_count=1)
        source = VideoFileSource(
            str(video), clip_region=(0, 0, 8, 8), output_size=(12, 10)
        )
        source.prepare()
        result = source.read()
        assert isinstance(result, Frame)
        assert result.image.flags.owndata
        assert result.image.base is None


class TestResizeError:
    def test_resize_failure_returned_as_value_and_stop(self, tmp_path, monkeypatch):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)

        def raise_resize_error(*args, **kwargs):
            raise cv2.error("resize failed")

        monkeypatch.setattr(cv2, "resize", raise_resize_error)
        source = VideoFileSource(str(video), output_size=(12, 10))
        source.prepare()
        result = source.read()
        assert isinstance(result, VideoFileResizeError)
        assert isinstance(result, VideoFileError)
        assert source.handle_error(result) is ErrorAction.STOP
