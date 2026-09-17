from __future__ import annotations

import threading
import time

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
        self.ready = threading.Event()
        self.closed = threading.Event()

    def prepare(self):
        self.ready.set()

    def read(self):
        if self.closed.is_set():
            return None
        return Frame(np.zeros((2, 3, 3), dtype=np.uint8), MonotonicTime(1))

    def close(self) -> None:
        self.closed.set()


def test_camera_preview_opens_without_scenario(monkeypatch, tmp_path) -> None:
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
    assert source.ready.wait(1.0)
    deadline = time.monotonic() + 1.0
    frame = None
    while frame is None and time.monotonic() < deadline:
        frame = preview.take_latest()
    preview.stop()

    assert frame is not None
    assert frame.image.shape == (2, 3, 3)
    assert preview.error is None


def test_ndi_preview_continues_after_timeout_and_closes_on_worker(
    monkeypatch, tmp_path
) -> None:
    class Api:
        reads = 0
        reader = None
        closer = None

        def open_receiver(self, source_name):
            return object()

        def receive_video(self, receiver, timeout_ms):
            self.reader = threading.current_thread()
            self.reads += 1
            if self.reads == 1:
                return None
            return NdiVideoFrame(np.zeros((2, 3, 3), dtype=np.uint8))

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
        deadline = time.monotonic() + 2
        frame = None
        while frame is None and time.monotonic() < deadline:
            frame = preview.take_latest()
            time.sleep(0.01)
        assert frame is not None
        assert frame.image.shape == (2, 3, 3)
        assert preview.error is None
    finally:
        preview.stop()
    assert api.closer is api.reader
    assert api.closer is not threading.current_thread()
