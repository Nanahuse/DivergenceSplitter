import logging
import re
from dataclasses import dataclass
from io import StringIO

import numpy as np
from divergencesplitter import (
    Action,
    ColorRangeConfig,
    ColorRangeDetector,
    Detected,
    DetectionResult,
    Frame,
    FrameContext,
    LiveSplitConnection,
    MeanBrightnessDetector,
    MonotonicTime,
    Rule,
    Scenario,
    VideoFileSource,
)
from divergencesplitter_runtime.capture import PublishResult
from divergencesplitter_runtime.diagnostics import OperationalDiagnostics
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
)
from divergencesplitter_runtime.scenario import ScenarioRuntime


@dataclass(frozen=True)
class SecretConfig:
    token: str


class CustomDetector:
    config = SecretConfig(token="must-not-be-logged")


class BrokenStream(StringIO):
    def write(self, value: str) -> int:
        raise OSError("stream unavailable")


class UnprintableError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("cannot format")

    def flush(self) -> None:
        raise OSError("stream unavailable")


def test_writes_human_readable_physical_one_line_with_escaped_values() -> None:
    stream = StringIO()
    diagnostics = OperationalDiagnostics(stream)

    diagnostics.usage_failed("bad\nargument")

    output = stream.getvalue()
    assert len(output.splitlines()) == 1
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z ERROR \[MainThread\] ",
        output,
    )
    assert "cli.usage_failed" in output
    assert 'usage_detail="bad\\nargument"' in output
    assert not output.lstrip().startswith("{")


def test_exception_group_records_every_leaf_on_one_line() -> None:
    stream = StringIO()
    diagnostics = OperationalDiagnostics(stream)
    error = ExceptionGroup(
        "startup failed",
        [ValueError("first\nproblem"), TypeError("second")],
    )

    diagnostics.startup_validation_failed(error)

    output = stream.getvalue()
    assert len(output.splitlines()) == 1
    assert "exception_count=2" in output
    assert 'exception.0.type="ValueError"' in output
    assert 'exception.0.message="first\\nproblem"' in output
    assert 'exception.0.traceback="ValueError: first\\nproblem\\n"' in output
    assert 'exception.1.type="TypeError"' in output
    assert 'exception.1.message="second"' in output


def test_runtime_context_identifies_scenario_without_exposing_credentials() -> None:
    stream = StringIO()
    diagnostics = OperationalDiagnostics(stream)
    connection = LiveSplitConnection(
        "tcp://rpc-user:rpc-secret@localhost:16835",
        "tcp://event-user:event-secret@localhost:16836",
    )
    scenario = Scenario(connection=connection, reset_conditions=(), splits=())
    diagnostics.bind_runtime((scenario,), VideoFileSource("recording.mp4"))

    diagnostics.worker_started(connection)

    output = stream.getvalue()
    assert "scenario_index=0" in output
    assert 'rpc_endpoint="tcp://localhost:16835"' in output
    assert 'event_endpoint="tcp://localhost:16836"' in output
    assert "rpc-user" not in output
    assert "rpc-secret" not in output
    assert "event-user" not in output
    assert "event-secret" not in output


def test_debug_frame_log_contains_frame_and_detector_configuration() -> None:
    stream = StringIO()
    diagnostics = OperationalDiagnostics(stream, level=logging.DEBUG)
    frame = Frame(
        image=np.zeros((2, 3, 4), dtype=np.uint8),
        captured_at=MonotonicTime(100),
    )
    detector = ColorRangeDetector(ColorRangeConfig(lower=(0,), upper=(255,)))
    custom_detector = CustomDetector()
    context = FrameContext(frame=frame, now=MonotonicTime(125))
    context.detection_cache[detector] = DetectionResult(score=0.875)
    context.detection_cache[custom_detector] = DetectionResult(score=0.5)

    diagnostics.frame_received(frame, PublishResult.PUBLISHED)
    diagnostics.frame_processing_completed(context)

    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    assert "capture.frame_received" in lines[0]
    assert "captured_at_ns=100" in lines[0]
    assert "frame_shape=[2,3,4]" in lines[0]
    assert 'frame_dtype="uint8"' in lines[0]
    assert 'publish_result="PUBLISHED"' in lines[0]
    assert "processing.frame_completed" in lines[1]
    assert 'detector.0.type="ColorRangeDetector"' in lines[1]
    assert "detector.0.score=0.875" in lines[1]
    assert "lower:[0]" in lines[1]
    assert "upper:[255]" in lines[1]
    assert 'detector.1.type="CustomDetector"' in lines[1]
    assert 'detector.1.config_type="SecretConfig"' in lines[1]
    assert "must-not-be-logged" not in lines[1]


def test_debug_rule_logs_include_score_threshold_and_cache_use() -> None:
    stream = StringIO()
    diagnostics = OperationalDiagnostics(stream, level=logging.DEBUG)
    connection = LiveSplitConnection("tcp://rpc", "tcp://event")
    detector = MeanBrightnessDetector()
    rules = (
        Rule(Detected(detector, 300.0), Action("split")),
        Rule(Detected(detector, 400.0), Action("split")),
    )
    scenario = Scenario(connection=connection, reset_conditions=(), splits=(rules,))
    diagnostics.bind_runtime((scenario,), VideoFileSource("recording.mp4"))
    runtime = ScenarioRuntime(scenario, logger=diagnostics.scenario_logger(0))
    runtime.apply_livesplit_update(
        LiveSplitUpdate(
            LiveSplitUpdateKind.INITIAL,
            LiveSplitSnapshot(1, 0, 0, TimerPhase.RUNNING, 0, 1),
        )
    )
    context = FrameContext(
        frame=Frame(np.zeros((1, 1), dtype=np.uint8), MonotonicTime(10)),
        now=MonotonicTime(20),
    )

    assert runtime.evaluate(context) is None

    rule_lines = [
        line
        for line in stream.getvalue().splitlines()
        if "scenario_runtime.rule_evaluated" in line
    ]
    assert len(rule_lines) == 2
    assert 'detector_type="MeanBrightnessDetector"' in rule_lines[0]
    assert "detector_minimum_score=300.0" in rule_lines[0]
    assert "detector_score=0.0" in rule_lines[0]
    assert "detector_cache_hit=false" in rule_lines[0]
    assert "detector_minimum_score=400.0" in rule_lines[1]
    assert "detector_cache_hit=true" in rule_lines[1]


def test_snapshot_mismatch_names_each_different_precondition() -> None:
    stream = StringIO()
    diagnostics = OperationalDiagnostics(stream)
    connection = LiveSplitConnection("tcp://rpc", "tcp://event")
    expected = LiveSplitSnapshot(1, 2, 3, TimerPhase.RUNNING, 0, 2)
    actual = LiveSplitSnapshot(1, 4, 5, TimerPhase.RUNNING, 1, 2)

    diagnostics.snapshot_mismatched(connection, Action("split"), expected, actual)

    output = stream.getvalue()
    assert 'mismatched_fields=["state_revision","split_index"]' in output
    assert "expected.state_revision=2" in output
    assert "actual.state_revision=4" in output
    assert "expected.split_index=0" in output
    assert "actual.split_index=1" in output


def test_unprintable_exception_does_not_escape_or_break_one_line_output() -> None:
    stream = StringIO()
    diagnostics = OperationalDiagnostics(stream)

    diagnostics.runtime_failed(UnprintableError())

    output = stream.getvalue()
    assert len(output.splitlines()) == 1
    assert 'exception_message="<UnprintableError could not be formatted>"' in output
    assert 'exception_traceback="test_diagnostics.UnprintableError:' in output
    assert "<exception str() failed>" in output


def test_exception_text_does_not_expose_endpoint_credentials() -> None:
    stream = StringIO()
    diagnostics = OperationalDiagnostics(stream)

    diagnostics.runtime_failed(
        RuntimeError("connection to tcp://name:secret@localhost:16835 failed")
    )

    output = stream.getvalue()
    assert "name" not in output
    assert "secret" not in output
    assert "tcp://localhost:16835" in output


def test_log_level_filters_debug_events() -> None:
    stream = StringIO()
    diagnostics = OperationalDiagnostics(stream)
    frame = Frame(
        image=np.zeros((1, 1), dtype=np.uint8),
        captured_at=MonotonicTime(1),
    )

    diagnostics.frame_received(frame, PublishResult.PUBLISHED)
    diagnostics.completed()

    assert "capture.frame_received" not in stream.getvalue()
    assert "cli.completed" in stream.getvalue()


def test_stream_failure_does_not_escape_diagnostics() -> None:
    diagnostics = OperationalDiagnostics(BrokenStream())

    diagnostics.runtime_failed(RuntimeError("boom"))
