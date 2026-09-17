from __future__ import annotations

from typing import cast

from divergencesplitter import ConditionStatus, Detected, MeanBrightnessDetector
from divergencesplitter_runtime.observability import ConditionObservation
from divergencesplitter_ui.monitor.coordinator import (
    MonitorUpdateCoordinator,
)
from divergencesplitter_ui.session import SessionController, SessionState


class FakeClock:
    def __init__(self) -> None:
        self.now = 0

    def now_ns(self) -> int:
        return self.now


class FakeDiagnostics:
    def __init__(self, observations: tuple[ConditionObservation, ...] = ()) -> None:
        self.take_calls = 0
        self.metrics_calls = 0
        self._pending = observations
        self._tree = object()
        self._statuses = (object(),)
        self._run_infos = (object(),)

    def take_condition_observations(self) -> tuple[ConditionObservation, ...]:
        self.take_calls += 1
        pending, self._pending = self._pending, ()
        return pending

    def detector_tree(self) -> object:
        return self._tree

    def instance_statuses(self) -> tuple:
        return self._statuses

    def instance_run_infos(self) -> tuple:
        return self._run_infos

    def metrics_snapshot(self) -> object:
        self.metrics_calls += 1
        return self._metrics

    _metrics = object()


class FakeController:
    def __init__(self, diagnostics: FakeDiagnostics | None = None) -> None:
        self.state = SessionState.IDLE
        self.diagnostics = diagnostics


def make_coordinator(
    controller: FakeController,
    *,
    clock: FakeClock | None = None,
) -> MonitorUpdateCoordinator:
    return MonitorUpdateCoordinator(
        cast(SessionController, controller),
        clock=clock,
    )


def observation() -> ConditionObservation:
    condition = Detected(MeanBrightnessDetector(), 0.9)
    return ConditionObservation(condition, ConditionStatus.TRUE, 0.5, 0.9, active=True)


class TestNoDiagnostics:
    def test_snapshot_is_empty_before_a_session_binds(self) -> None:
        coordinator = make_coordinator(FakeController())

        snapshot = coordinator.snapshot()

        assert snapshot.state is SessionState.IDLE
        assert snapshot.tree is None
        assert snapshot.instance_statuses == ()
        assert snapshot.run_infos == ()
        assert snapshot.observations == ()
        assert snapshot.metrics is None


class TestObservationConsumption:
    def test_snapshot_consumes_observations_once_per_cycle(self) -> None:
        diagnostics = FakeDiagnostics((observation(),))
        coordinator = make_coordinator(FakeController(diagnostics))

        coordinator.snapshot()
        coordinator.snapshot()

        assert diagnostics.take_calls == 2

    def test_latest_observations_are_retained_across_empty_polls(self) -> None:
        observations = (observation(),)
        diagnostics = FakeDiagnostics(observations)
        controller = FakeController(diagnostics)
        controller.state = SessionState.RUNNING
        coordinator = make_coordinator(controller)

        first = coordinator.snapshot()
        second = coordinator.snapshot()

        assert first.observations == observations
        assert second.observations == observations

    def test_terminal_state_clears_retained_observations(self) -> None:
        diagnostics = FakeDiagnostics((observation(),))
        controller = FakeController(diagnostics)
        controller.state = SessionState.RUNNING
        coordinator = make_coordinator(controller)
        assert coordinator.snapshot().observations != ()

        controller.state = SessionState.STOPPED
        snapshot = coordinator.snapshot()

        assert snapshot.observations == ()
        assert snapshot.tree is not None

    def test_empty_first_snapshot_stays_empty(self) -> None:
        coordinator = make_coordinator(FakeController(FakeDiagnostics()))

        assert coordinator.snapshot().observations == ()


class TestMetricsCadence:
    def test_metrics_are_read_once_per_interval(self) -> None:
        clock = FakeClock()
        diagnostics = FakeDiagnostics()
        coordinator = make_coordinator(FakeController(diagnostics), clock=clock)

        coordinator.snapshot()
        assert diagnostics.metrics_calls == 1

        clock.now = 500_000_000
        coordinator.snapshot()
        assert diagnostics.metrics_calls == 1

        clock.now = 1_000_000_000
        coordinator.snapshot()
        assert diagnostics.metrics_calls == 2

        clock.now = 1_500_000_000
        coordinator.snapshot()
        assert diagnostics.metrics_calls == 2


class TestRebinding:
    def test_new_diagnostics_clear_retained_observations(self) -> None:
        first = FakeDiagnostics((observation(),))
        controller = FakeController(first)
        controller.state = SessionState.RUNNING
        coordinator = make_coordinator(controller)
        assert coordinator.snapshot().observations != ()

        controller.diagnostics = FakeDiagnostics()
        rebound = coordinator.snapshot()

        assert rebound.observations == ()

    def test_losing_diagnostics_clears_metrics(self) -> None:
        diagnostics = FakeDiagnostics()
        controller = FakeController(diagnostics)
        coordinator = make_coordinator(controller)
        assert coordinator.snapshot().metrics is not None

        controller.diagnostics = None

        assert coordinator.snapshot().metrics is None

    def test_session_state_is_reported(self) -> None:
        controller = FakeController(FakeDiagnostics())
        controller.state = SessionState.RUNNING
        coordinator = make_coordinator(controller)

        assert coordinator.snapshot().state is SessionState.RUNNING
