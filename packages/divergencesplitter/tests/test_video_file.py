import time
from typing import get_protocol_members

import cv2
import numpy as np
import pytest
from divergencesplitter.clock import MonotonicTime, TimeProvider
from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.normalizer import (
    ClipRegion,
    FrameNormalizer,
    OutputSize,
)
from divergencesplitter.frame.source import (
    ErrorAction,
    FrameSource,
    FrameSourceState,
)
from divergencesplitter.frame.video_file import (
    VideoFileDecodeError,
    VideoFileEndOfFileError,
    VideoFileError,
    VideoFileOpenError,
    VideoFileReadBeforeReadyError,
    VideoFileSource,
)

SIZE = (16, 16)


class FixedTimeProvider(TimeProvider):
    def __init__(self, nanoseconds: int) -> None:
        self._now = MonotonicTime(nanoseconds)
        self.calls = 0

    def now(self) -> MonotonicTime:
        self.calls += 1
        return self._now


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


def read_frame(source: VideoFileSource) -> Frame:
    result = source.read()
    assert isinstance(result, Frame)
    return result


def read_error(source: VideoFileSource) -> VideoFileError:
    result = source.read()
    assert isinstance(result, VideoFileError)
    return result


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
        time_provider = FixedTimeProvider(123)
        source = VideoFileSource(str(video), time_provider=time_provider)
        source.prepare()
        result = read_frame(source)
        assert result.image.shape == (*SIZE, 3)
        assert int(result.image[0, 0, 0]) == 0
        assert result.captured_at == MonotonicTime(123)
        assert time_provider.calls == 1

    def test_read_before_ready_is_source_error(self, tmp_path):
        source = VideoFileSource(str(tmp_path / "movie.avi"))
        assert isinstance(read_error(source), VideoFileReadBeforeReadyError)

    def test_read_after_close_is_source_error(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video))
        source.prepare()
        source.close()
        assert isinstance(read_error(source), VideoFileReadBeforeReadyError)

    def test_frames_follow_recording_order(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=3)
        source = VideoFileSource(str(video))
        source.prepare()
        values = []
        for _ in range(3):
            result = read_frame(source)
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
        read_frame(source)
        assert isinstance(read_error(source), VideoFileEndOfFileError)
        assert source.state is FrameSourceState.READY

    def test_eof_repeats_on_further_reads(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=1)
        source = VideoFileSource(str(video))
        source.prepare()
        read_frame(source)
        assert isinstance(read_error(source), VideoFileEndOfFileError)
        assert isinstance(read_error(source), VideoFileEndOfFileError)


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
        assert "normalizer" in members
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
            read_frame(source)
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
            read_frame(source)
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


class TestNormalizer:
    def test_normalizer_holds_configured_settings(self):
        region = ClipRegion(x=2, y=3, width=6, height=5)
        size = OutputSize(width=12, height=10)
        source = VideoFileSource("unused.avi", clip_region=region, output_size=size)
        normalizer = source.normalizer
        assert isinstance(normalizer, FrameNormalizer)
        assert normalizer.clip_region == region
        assert normalizer.output_size == size

    def test_default_normalizer_has_no_settings(self):
        source = VideoFileSource("unused.avi")
        assert source.normalizer.clip_region is None
        assert source.normalizer.output_size is None

    def test_normalizer_normalizes_raw_frame_read_from_source(self, tmp_path):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=2)
        source = VideoFileSource(
            str(video), clip_region=ClipRegion(x=2, y=3, width=6, height=5)
        )
        source.prepare()
        raw = read_frame(source)
        assert raw.image.shape == (*SIZE, 3)
        result = source.normalizer.normalize(raw)
        assert isinstance(result, Frame)
        assert result.image.shape == (5, 6, 3)

    def test_read_stays_raw_and_normalize_resizes_once(self, tmp_path, monkeypatch):
        video = tmp_path / "movie.avi"
        make_video(video, frame_count=4)
        calls = {"count": 0}
        real_resize = cv2.resize

        def counting_resize(*args, **kwargs):
            calls["count"] += 1
            return real_resize(*args, **kwargs)

        monkeypatch.setattr(cv2, "resize", counting_resize)
        source = VideoFileSource(
            str(video), output_size=OutputSize(width=12, height=10)
        )
        source.prepare()
        raws = []
        for _ in range(3):
            raws.append(read_frame(source))
        assert calls["count"] == 0
        normalized = source.normalizer.normalize(raws[1])
        assert isinstance(normalized, Frame)
        assert calls["count"] == 1
