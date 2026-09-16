from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterator
from typing import cast

import flet as ft
from divergencesplitter import (
    Action,
    ConditionStatus,
    Detected,
    LiveSplitConnection,
    MeanBrightnessDetector,
    Rule,
    Scenario,
)
from divergencesplitter_runtime.instance_runtime import (
    InstanceRuntimeState,
    InstanceStatus,
)
from divergencesplitter_runtime.instances import ScenarioInstance
from divergencesplitter_runtime.observability import (
    ConditionObservation,
    DetectorTreeSnapshot,
    build_detector_tree,
)
from divergencesplitter_ui.flet_application import AppView, FletApplication
from divergencesplitter_ui.monitor.coordinator import MonitorUpdateCoordinator
from divergencesplitter_ui.monitor.page import Monitor
from divergencesplitter_ui.performance import (
    FLAGS,
    PerformanceFlags,
    PerformanceMetrics,
)
from divergencesplitter_ui.session import SessionController, SessionState


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class _Clock:
    def __init__(self) -> None:
        self.now = 0

    def __call__(self) -> int:
        return self.now


def make_logger() -> tuple[logging.Logger, _RecordingHandler]:
    logger = logging.getLogger(f"test.performance.{uuid.uuid4().hex}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = _RecordingHandler()
    logger.addHandler(handler)
    return logger, handler


class TestAggregation:
    def test_records_count_average_and_maximum(self) -> None:
        logger, _ = make_logger()
        metrics = PerformanceMetrics(logger=logger, clock=_Clock())

        metrics.record("section", 100)
        metrics.record("section", 300)
        metrics.record("section", 200)

        stats = metrics.snapshot()["section"]
        assert stats.count == 3
        assert stats.total_ns == 600
        assert stats.average_ns == 200
        assert stats.max_ns == 300

    def test_flush_emits_structured_record_and_resets_the_window(self) -> None:
        logger, handler = make_logger()
        metrics = PerformanceMetrics(logger=logger, clock=_Clock())
        metrics.record("section", 100)

        metrics.flush_if_due(now_ns=1_000_000_000)

        assert len(handler.records) == 1
        record = handler.records[0]
        assert record.getMessage() == "ui.performance"
        fields = record.__dict__
        assert fields["section"] == "section"
        assert fields["count"] == 1
        assert fields["avg_ms"] == 0.0
        assert fields["max_ms"] == 0.0
        assert metrics.snapshot() == {}

    def test_flush_waits_for_the_interval(self) -> None:
        logger, handler = make_logger()
        metrics = PerformanceMetrics(logger=logger, clock=_Clock())

        metrics.record("a", 10)
        metrics.flush_if_due(now_ns=100)
        metrics.record("a", 10)
        metrics.flush_if_due(now_ns=200)

        assert len(handler.records) == 1

    def test_flush_without_samples_is_safe(self) -> None:
        logger, handler = make_logger()
        metrics = PerformanceMetrics(logger=logger, clock=_Clock())

        metrics.flush_if_due(now_ns=1)

        assert handler.records == []
        assert metrics.snapshot() == {}

    def test_disabled_logger_keeps_no_samples(self) -> None:
        logger, handler = make_logger()
        logger.setLevel(logging.WARNING)
        metrics = PerformanceMetrics(logger=logger, clock=_Clock())

        metrics.record("section", 100)
        metrics.flush_if_due(now_ns=1)

        assert metrics.snapshot() == {}
        assert handler.records == []

    def test_measure_records_the_enclosed_block(self) -> None:
        logger, _ = make_logger()
        clock = _Clock()
        metrics = PerformanceMetrics(logger=logger, clock=clock)

        def advance() -> None:
            clock.now += 250

        with metrics.measure("section"):
            advance()

        assert metrics.snapshot()["section"].total_ns == 250


class TestFlags:
    def test_defaults_are_all_off(self) -> None:
        assert PerformanceFlags.from_environment({}) == PerformanceFlags()
        assert FLAGS.disable_input_preview is False
        assert FLAGS.disable_page_update is False
        assert FLAGS.disable_diagnostics is False

    def test_environment_switches_are_read(self) -> None:
        flags = PerformanceFlags.from_environment(
            {
                "DIVERGENCESPLITTER_PERF_DISABLE_PREVIEW": "1",
                "DIVERGENCESPLITTER_PERF_DISABLE_PAGE_UPDATE": "true",
                "DIVERGENCESPLITTER_PERF_DISABLE_DIAGNOSTICS": "YES",
            }
        )

        assert flags.disable_input_preview is True
        assert flags.disable_page_update is True
        assert flags.disable_diagnostics is True

    def test_falsey_values_leave_sections_enabled(self) -> None:
        flags = PerformanceFlags.from_environment(
            {
                "DIVERGENCESPLITTER_PERF_DISABLE_PREVIEW": "0",
                "DIVERGENCESPLITTER_PERF_DISABLE_PAGE_UPDATE": "",
            }
        )

        assert flags.disable_input_preview is False
        assert flags.disable_page_update is False


class _FakeDiagnostics:
    def __init__(
        self,
        tree: DetectorTreeSnapshot,
        observations: tuple[ConditionObservation, ...],
    ) -> None:
        self._tree = tree
        self._observations = observations

    def take_condition_observations(self) -> tuple[ConditionObservation, ...]:
        return self._observations

    def detector_tree(self) -> DetectorTreeSnapshot:
        return self._tree

    def instance_statuses(self) -> tuple[InstanceStatus, ...]:
        return (InstanceStatus(0, InstanceRuntimeState.READY),)

    def instance_run_infos(self) -> tuple:
        return ()

    def metrics_snapshot(self) -> None:
        return None


class _FakeController:
    def __init__(self, diagnostics: _FakeDiagnostics) -> None:
        self.state = SessionState.RUNNING
        self.diagnostics = diagnostics


def make_monitor(
    *, flags: PerformanceFlags
) -> tuple[Monitor, MonitorUpdateCoordinator]:
    condition = Detected(MeanBrightnessDetector(), 0.9)
    instance = ScenarioInstance(
        LiveSplitConnection("tcp://rpc:0", "tcp://event:0"),
        Scenario(
            start_condition=condition,
            reset_condition=None,
            incomplete_condition=None,
            splits=((Rule(condition, Action("split")),),),
        ),
    )
    tree = build_detector_tree((instance,))
    observation = ConditionObservation(
        condition=condition,
        status=ConditionStatus.TRUE,
        latest_score=0.5,
        max_score=0.9,
        active=True,
        progress_current=0.5,
        progress_target=condition.minimum_score,
        progress_unit="score",
    )
    diagnostics = _FakeDiagnostics(tree, (observation,))
    coordinator = MonitorUpdateCoordinator(
        cast(SessionController, _FakeController(diagnostics))
    )
    return Monitor(flags=flags), coordinator


def iter_controls(control: ft.Control) -> Iterator[ft.Control]:
    yield control
    for child in getattr(control, "controls", None) or ():
        yield from iter_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from iter_controls(content)
    title = getattr(control, "title", None)
    if isinstance(title, ft.Control):
        yield from iter_controls(title)


def collect_text(control: ft.Control) -> list[str]:
    return [
        item.value
        for item in iter_controls(control)
        if isinstance(item, ft.Text) and isinstance(item.value, str)
    ]


class TestDiagnosticsFlag:
    def test_diagnostics_are_materialized_by_default(self) -> None:
        monitor, coordinator = make_monitor(flags=PerformanceFlags())

        monitor.apply(coordinator.snapshot())

        assert any(
            "Connection" in text for text in collect_text(monitor.diagnostics.control)
        )

    def test_disabling_diagnostics_skips_the_control_tree(self) -> None:
        monitor, coordinator = make_monitor(
            flags=PerformanceFlags(disable_diagnostics=True)
        )

        monitor.apply(coordinator.snapshot())

        assert not any(
            "Connection" in text for text in collect_text(monitor.diagnostics.control)
        )


class _FakeSnapshot:
    pass


class _RecordingCoordinator:
    def snapshot(self) -> _FakeSnapshot:
        return _FakeSnapshot()


class _RecordingMonitor:
    def __init__(self) -> None:
        self.apply_calls = 0

    def apply(self, snapshot: _FakeSnapshot) -> bool:
        self.apply_calls += 1
        return True


class _RecordingPage:
    def __init__(self) -> None:
        self.update_calls = 0

    def update(self) -> None:
        self.update_calls += 1


class _RecordingPreview:
    def __init__(self) -> None:
        self.render_calls = 0

    async def render_latest(self, diagnostics: object) -> bool:
        self.render_calls += 1
        return False


class _PreviewMonitor:
    def __init__(self, preview: _RecordingPreview) -> None:
        self.input_preview = preview


class _StubController:
    def __init__(self) -> None:
        self.state = SessionState.IDLE
        self.diagnostics = None
        self.result = None


def make_application(
    *,
    flags: PerformanceFlags,
) -> tuple[FletApplication, _RecordingMonitor, _RecordingPage]:
    application = FletApplication(
        cast(SessionController, _StubController()),
        performance_flags=flags,
    )
    monitor = _RecordingMonitor()
    page = _RecordingPage()
    application._monitor = cast(Monitor, monitor)
    application._coordinator = cast(MonitorUpdateCoordinator, _RecordingCoordinator())
    application._page = cast(ft.Page, page)
    return application, monitor, page


class TestPageUpdateFlag:
    def test_page_update_runs_by_default(self) -> None:
        application, _, page = make_application(flags=PerformanceFlags())

        asyncio.run(application._apply_monitor())

        assert page.update_calls == 1

    def test_disabling_page_update_skips_the_repaint(self) -> None:
        application, _, page = make_application(
            flags=PerformanceFlags(disable_page_update=True)
        )

        asyncio.run(application._apply_monitor())

        assert page.update_calls == 0


class TestPreviewFlag:
    def test_preview_renders_by_default(self) -> None:
        application, _, _ = make_application(flags=PerformanceFlags())
        preview = _RecordingPreview()
        application._monitor = cast(Monitor, _PreviewMonitor(preview))
        application._active_view = AppView.MONITOR

        asyncio.run(application._render_input_preview_once())

        assert preview.render_calls == 1

    def test_disabling_preview_skips_render_latest(self) -> None:
        application, _, _ = make_application(
            flags=PerformanceFlags(disable_input_preview=True)
        )
        preview = _RecordingPreview()
        application._monitor = cast(Monitor, _PreviewMonitor(preview))
        application._active_view = AppView.MONITOR

        asyncio.run(application._render_input_preview_once())

        assert preview.render_calls == 0
