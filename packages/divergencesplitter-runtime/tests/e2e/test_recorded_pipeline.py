from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest
from divergencesplitter import (
    Action,
    All,
    ClipRegion,
    Detected,
    Elapsed,
    FallingEdge,
    Hold,
    LiveSplitConnection,
    MeanBrightnessDetector,
    OutputSize,
    RisingEdge,
    Rule,
    Scenario,
    Then,
    VideoFileSource,
)
from divergencesplitter_runtime import ApplicationRuntime, TimerPhase

from .support import (
    BlockingDetectedCondition,
    BridgeScript,
    RecordingDiagnostics,
    ScriptedBridgeAdapter,
    snapshot,
)

BRIGHT = 240
DARK = 10
THRESHOLD = 128.0
FRAME_SIZE = (16, 16)


@pytest.fixture(autouse=True)
def clear_adapter_scripts() -> Iterator[None]:
    ScriptedBridgeAdapter.scripts = {}
    yield
    ScriptedBridgeAdapter.scripts = {}


def write_recording(
    path: Path,
    segments: tuple[tuple[int, int], ...],
    *,
    fps: float,
) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore
    writer = cv2.VideoWriter(str(path), fourcc, fps, FRAME_SIZE)
    assert writer.isOpened(), "could not create the E2E recording"
    try:
        for brightness, frame_count in segments:
            image = np.full((*FRAME_SIZE, 3), brightness, dtype=np.uint8)
            for _ in range(frame_count):
                writer.write(image)
    finally:
        writer.release()


def write_image_recording(
    path: Path,
    image: np.ndarray,
    *,
    frame_count: int,
    fps: float,
) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore
    writer = cv2.VideoWriter(str(path), fourcc, fps, FRAME_SIZE)
    assert writer.isOpened(), "could not create the E2E recording"
    try:
        for _ in range(frame_count):
            writer.write(image)
    finally:
        writer.release()


def start_runtime(
    runtime: ApplicationRuntime,
) -> tuple[threading.Thread, list[BaseException]]:
    errors: list[BaseException] = []

    def run() -> None:
        try:
            runtime.run()
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    thread = threading.Thread(target=run, name="application-e2e")
    thread.start()
    return thread, errors


def assert_runtime_stopped(
    thread: threading.Thread,
    errors: list[BaseException],
    diagnostics: RecordingDiagnostics,
    script: BridgeScript,
    *,
    timeout_seconds: float,
) -> None:
    thread.join(timeout_seconds)
    assert not thread.is_alive()
    assert errors == []
    assert diagnostics.scenario_errors == []
    assert diagnostics.normalization_errors == []
    assert diagnostics.source_closed_event.is_set()
    assert diagnostics.capture_stopped.is_set()
    assert diagnostics.worker_stopped_event.is_set()
    assert script.closed.is_set()


def impossible_reset_condition() -> Detected:
    return Detected(MeanBrightnessDetector(), minimum_score=300)


def test_recording_is_normalized_before_scenario_evaluation(tmp_path: Path) -> None:
    video = tmp_path / "normalized.avi"
    image = np.full((*FRAME_SIZE, 3), DARK, dtype=np.uint8)
    image[:, :4] = BRIGHT
    write_image_recording(video, image, frame_count=12, fps=20)
    connection = LiveSplitConnection("normalized-rpc", "normalized-event")
    scenario = Scenario(
        connection=connection,
        reset_conditions=(impossible_reset_condition(),),
        splits=(
            (Rule(Detected(MeanBrightnessDetector(), THRESHOLD), Action("split")),),
        ),
    )
    script = BridgeScript(snapshot())
    diagnostics = RecordingDiagnostics()
    ScriptedBridgeAdapter.scripts = {connection: script}
    runtime = ApplicationRuntime(
        (scenario,),
        VideoFileSource(
            str(video),
            clip_region=ClipRegion(x=0, y=0, width=4, height=16),
            output_size=OutputSize(width=8, height=8),
        ),
        diagnostics=diagnostics,
    )

    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        ScriptedBridgeAdapter,
    ):
        thread, errors = start_runtime(runtime)
        assert script.wait_for_actions(1, 2)
        assert_runtime_stopped(
            thread,
            errors,
            diagnostics,
            script,
            timeout_seconds=3,
        )

    assert [action.operation for action, _ in script.actions] == ["split"]


def test_normalization_failure_stops_the_recording_pipeline(tmp_path: Path) -> None:
    video = tmp_path / "normalization-failure.avi"
    write_recording(video, ((BRIGHT, 12),), fps=20)
    connection = LiveSplitConnection("failure-rpc", "failure-event")
    scenario = Scenario(
        connection=connection,
        reset_conditions=(impossible_reset_condition(),),
        splits=(
            (Rule(Detected(MeanBrightnessDetector(), THRESHOLD), Action("split")),),
        ),
    )
    script = BridgeScript(snapshot())
    diagnostics = RecordingDiagnostics()
    ScriptedBridgeAdapter.scripts = {connection: script}
    runtime = ApplicationRuntime(
        (scenario,),
        VideoFileSource(
            str(video),
            clip_region=ClipRegion(x=0, y=0, width=17, height=17),
        ),
        diagnostics=diagnostics,
    )

    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        ScriptedBridgeAdapter,
    ):
        thread, errors = start_runtime(runtime)
        thread.join(3)

    assert not thread.is_alive()
    assert errors == []
    assert len(diagnostics.normalization_errors) == 1
    assert diagnostics.scenario_errors == []
    assert script.actions == []
    assert diagnostics.source_closed_event.is_set()
    assert diagnostics.capture_stopped.is_set()
    assert diagnostics.worker_stopped_event.is_set()
    assert script.closed.is_set()


def test_recording_reaches_finish_and_refires_after_external_undo(
    tmp_path: Path,
) -> None:
    video = tmp_path / "finish-and-undo.avi"
    write_recording(
        video,
        (
            (DARK, 8),
            (BRIGHT, 8),
            (DARK, 8),
            (BRIGHT, 12),
            (DARK, 8),
            (BRIGHT, 8),
            (DARK, 8),
            (BRIGHT, 8),
        ),
        fps=20,
    )
    detector = MeanBrightnessDetector()
    sequence = Then(
        RisingEdge(Detected(detector, THRESHOLD)),
        FallingEdge(Detected(detector, THRESHOLD)),
        within_nanoseconds=2_000_000_000,
    )
    first_split = All(
        sequence,
        Hold(Detected(detector, THRESHOLD), duration_nanoseconds=150_000_000),
        Elapsed(duration_nanoseconds=200_000_000),
    )
    second_split = RisingEdge(Detected(detector, THRESHOLD))
    connection = LiveSplitConnection("e2e-rpc", "e2e-event")
    scenario = Scenario(
        connection=connection,
        reset_conditions=(impossible_reset_condition(),),
        splits=(
            (Rule(first_split, Action("split")),),
            (Rule(second_split, Action("split")),),
            None,
        ),
    )
    script = BridgeScript(snapshot(split_count=2))
    diagnostics = RecordingDiagnostics()
    ScriptedBridgeAdapter.scripts = {connection: script}
    runtime = ApplicationRuntime(
        (scenario,),
        VideoFileSource(str(video)),
        diagnostics=diagnostics,
    )

    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        ScriptedBridgeAdapter,
    ):
        thread, errors = start_runtime(runtime)
        assert script.ended.wait(5)
        script.external_undo()
        assert script.wait_for_actions(3, 3)
        assert_runtime_stopped(
            thread,
            errors,
            diagnostics,
            script,
            timeout_seconds=3,
        )

    assert [action.operation for action, _ in script.actions] == [
        "split",
        "split",
        "split",
    ]
    assert [expected.split_index for _, expected in script.actions] == [0, 1, 1]
    assert script.snapshot_mismatches == []
    assert script.current_snapshot.phase is TimerPhase.ENDED
    assert script.created_on is not None
    assert script.closed_on == script.created_on
    assert set(script.action_threads) == {script.created_on}


@pytest.mark.parametrize("failure", ["gap", "connection_loss"])
def test_bridge_resynchronization_stops_evaluation_until_complete(
    tmp_path: Path,
    failure: str,
) -> None:
    video = tmp_path / f"{failure}.avi"
    write_recording(video, ((DARK, 20), (BRIGHT, 30)), fps=20)
    connection = LiveSplitConnection("gap-rpc", "gap-event")
    scenario = Scenario(
        connection=connection,
        reset_conditions=(impossible_reset_condition(),),
        splits=(
            (
                Rule(
                    Detected(MeanBrightnessDetector(), THRESHOLD),
                    Action("split"),
                ),
            ),
        ),
    )
    script = BridgeScript(snapshot())
    script.block_resync()
    diagnostics = RecordingDiagnostics()
    ScriptedBridgeAdapter.scripts = {connection: script}
    runtime = ApplicationRuntime(
        (scenario,),
        VideoFileSource(str(video)),
        diagnostics=diagnostics,
    )

    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        ScriptedBridgeAdapter,
    ):
        thread, errors = start_runtime(runtime)
        assert diagnostics.first_frame_started.wait(2)
        if failure == "gap":
            script.inject_gap()
        else:
            script.inject_connection_loss()
        assert script.resync_entered.wait(2)
        assert diagnostics.bright_frame_started.wait(2)
        assert script.actions == []
        script.release_resync()
        assert script.wait_for_actions(1, 2)
        assert_runtime_stopped(
            thread,
            errors,
            diagnostics,
            script,
            timeout_seconds=3,
        )

    assert script.snapshot_mismatches == []
    assert len(diagnostics.connection_errors) == (failure == "connection_loss")


def test_slow_processing_overwrites_buffer_and_returns_to_latest_frame(
    tmp_path: Path,
) -> None:
    video = tmp_path / "frame-drop.avi"
    write_recording(video, ((DARK, 5), (BRIGHT, 55)), fps=60)
    blocking = BlockingDetectedCondition(THRESHOLD)
    connection = LiveSplitConnection("drop-rpc", "drop-event")
    scenario = Scenario(
        connection=connection,
        reset_conditions=(impossible_reset_condition(),),
        splits=((Rule(blocking, Action("split")),),),
    )
    script = BridgeScript(snapshot())
    diagnostics = RecordingDiagnostics()
    ScriptedBridgeAdapter.scripts = {connection: script}
    runtime = ApplicationRuntime(
        (scenario,),
        VideoFileSource(str(video)),
        diagnostics=diagnostics,
    )

    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        ScriptedBridgeAdapter,
    ):
        thread, errors = start_runtime(runtime)
        assert blocking.entered.wait(2)
        assert diagnostics.frame_overwritten.wait(2)
        blocking.release.set()
        assert script.wait_for_actions(1, 2)
        assert_runtime_stopped(
            thread,
            errors,
            diagnostics,
            script,
            timeout_seconds=3,
        )

    assert script.snapshot_mismatches == []
    assert blocking.observed_brightness[-1] >= THRESHOLD


def test_missing_bridge_transition_allows_refire_only_after_scenario_timeout(
    tmp_path: Path,
) -> None:
    video = tmp_path / "transition-timeout.avi"
    write_recording(
        video,
        ((DARK, 4), (BRIGHT, 4), (DARK, 36), (BRIGHT, 8)),
        fps=20,
    )
    connection = LiveSplitConnection("timeout-rpc", "timeout-event")
    scenario = Scenario(
        connection=connection,
        reset_conditions=(impossible_reset_condition(),),
        splits=(
            (
                Rule(
                    RisingEdge(Detected(MeanBrightnessDetector(), THRESHOLD)),
                    Action("split"),
                ),
            ),
        ),
    )
    script = BridgeScript(snapshot(), apply_actions=False)
    diagnostics = RecordingDiagnostics()
    ScriptedBridgeAdapter.scripts = {connection: script}
    runtime = ApplicationRuntime(
        (scenario,),
        VideoFileSource(str(video)),
        diagnostics=diagnostics,
    )

    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        ScriptedBridgeAdapter,
    ):
        thread, errors = start_runtime(runtime)
        assert script.wait_for_actions(2, 4)
        assert_runtime_stopped(
            thread,
            errors,
            diagnostics,
            script,
            timeout_seconds=3,
        )

    assert [action.operation for action, _ in script.actions] == ["split", "split"]
    assert [expected for _, expected in script.actions] == [snapshot(), snapshot()]


def test_explicit_stop_releases_video_and_all_runtime_threads(tmp_path: Path) -> None:
    video = tmp_path / "explicit-stop.avi"
    write_recording(video, ((DARK, 120),), fps=30)
    connection = LiveSplitConnection("stop-rpc", "stop-event")
    scenario = Scenario(
        connection=connection,
        reset_conditions=(impossible_reset_condition(),),
        splits=(None,),
    )
    script = BridgeScript(snapshot())
    diagnostics = RecordingDiagnostics()
    ScriptedBridgeAdapter.scripts = {connection: script}
    runtime = ApplicationRuntime(
        (scenario,),
        VideoFileSource(str(video)),
        diagnostics=diagnostics,
    )

    with patch(
        "divergencesplitter_runtime.livesplit.worker.LiveSplitBridgeAdapter",
        ScriptedBridgeAdapter,
    ):
        thread, errors = start_runtime(runtime)
        assert diagnostics.first_frame_started.wait(2)
        runtime.request_stop()
        assert_runtime_stopped(
            thread,
            errors,
            diagnostics,
            script,
            timeout_seconds=2,
        )
