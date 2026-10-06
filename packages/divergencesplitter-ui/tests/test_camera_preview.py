from __future__ import annotations

import threading

import numpy as np
from divergencesplitter.clock import MonotonicTime
from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.ndi import NdiSource, NdiVideoFrame
from divergencesplitter_runtime.configuration.models import (
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    NdiSourceConfiguration,
)
from divergencesplitter_ui.camera_preview import CameraPreview


class FakeSource:
    def __init__(self) -> None:
        self.closed = threading.Event()
        self.frame_published = threading.Event()
        self.reads = 0

    def prepare(self):
        pass

    def read(self):
        self.reads += 1
        if self.reads == 1:
            return Frame(np.zeros((2, 3, 3), dtype=np.uint8), MonotonicTime(1))
        self.frame_published.set()
        self.closed.wait()
        return None

    def close(self) -> None:
        self.closed.set()


def test_camera_preview_opens_without_scenario(monkeypatch) -> None:
    source = FakeSource()
    monkeypatch.setattr(
        "divergencesplitter_ui.camera_preview.build_frame_source",
        lambda configuration: source,
    )
    preview = CameraPreview()
    configuration = CameraSourceConfiguration(
        CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "Camera", 0),
        CameraModeConfiguration(1280, 720, 30.0, "mode"),
        False,
    )

    preview.start(configuration)
    try:
        assert source.frame_published.wait(1.0)
        frame = preview.take_latest()

        assert frame is not None
        assert frame.image.shape == (2, 3, 3)
        assert preview.error is None
    finally:
        preview.stop()


def test_ndi_preview_continues_after_timeout_and_closes_on_worker(
    monkeypatch,
) -> None:
    class Api:
        reads = 0
        reader = None
        closer = None
        frame_published = threading.Event()
        release = threading.Event()

        def open_receiver(self, source_name):
            return object()

        def receive_video(self, receiver, timeout_ms):
            self.reader = threading.current_thread()
            self.reads += 1
            if self.reads == 1:
                return None
            if self.reads == 2:
                return NdiVideoFrame(np.zeros((2, 3, 3), dtype=np.uint8))
            self.frame_published.set()
            self.release.wait()
            return None

        def destroy_receiver(self, receiver):
            self.closer = threading.current_thread()

        def close(self):
            pass

    api = Api()
    source = NdiSource("Sender", api=api)
    monkeypatch.setattr(
        "divergencesplitter_ui.camera_preview.build_frame_source",
        lambda configuration: source,
    )
    preview = CameraPreview()
    preview.start(NdiSourceConfiguration("Sender"))
    try:
        assert api.frame_published.wait(2.0)
        frame = preview.take_latest()
        assert frame is not None
        assert frame.image.shape == (2, 3, 3)
        assert preview.error is None
    finally:
        api.release.set()
        preview.stop()
    assert api.closer is api.reader
    assert api.closer is not threading.current_thread()
