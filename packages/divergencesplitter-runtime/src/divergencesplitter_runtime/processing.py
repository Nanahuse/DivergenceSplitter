"""Processing loop that coordinates frames, scenarios, and Bridge workers."""

import threading
from typing import Protocol

from divergencesplitter.clock import MonotonicTime, TimeProvider
from divergencesplitter.frame.models import Frame, FrameContext
from divergencesplitter.frame.normalizer import (
    FrameNormalizationError,
    FrameNormalizer,
)

from divergencesplitter_runtime.capture import LatestFrameBuffer
from divergencesplitter_runtime.livesplit.worker import BridgeWorker
from divergencesplitter_runtime.scenario import ScenarioRuntime


class ProcessingDiagnostics(Protocol):
    def frame_processing_started(
        self,
        frame: Frame,
        processing_started_at: MonotonicTime,
    ) -> None: ...

    def frame_normalization_failed(
        self,
        error: FrameNormalizationError,
    ) -> None: ...

    def frame_processing_completed(self, context: FrameContext) -> None: ...

    def scenario_evaluation_failed(
        self,
        scenario_index: int,
        error: Exception,
    ) -> None: ...


class ProcessingRuntime:
    """Apply Bridge updates and evaluate all scenarios against each latest frame."""

    def __init__(
        self,
        scenarios: tuple[ScenarioRuntime, ...],
        workers: tuple[BridgeWorker, ...],
        frame_buffer: LatestFrameBuffer,
        normalizer: FrameNormalizer,
        *,
        diagnostics: ProcessingDiagnostics,
        time_provider: TimeProvider | None = None,
    ) -> None:
        if len(scenarios) != len(workers):
            raise ValueError("each scenario runtime must have one Bridge worker")
        self._scenarios = scenarios
        self._workers = workers
        self._frame_buffer = frame_buffer
        self._normalizer = normalizer
        self._diagnostics = diagnostics
        self._time_provider = time_provider or TimeProvider()
        self._stop_requested = threading.Event()

    def request_stop(self) -> None:
        self._stop_requested.set()
        self._frame_buffer.stop()

    def run(self) -> None:
        while not self._stop_requested.is_set():
            frame = self._frame_buffer.take()
            if frame is None or self._stop_requested.is_set():
                return
            self._apply_bridge_updates()
            now = self._time_provider.now()
            self._diagnostics.frame_processing_started(frame, now)
            normalized = self._normalizer.normalize(frame)
            if isinstance(normalized, FrameNormalizationError):
                self._diagnostics.frame_normalization_failed(normalized)
                self.request_stop()
                return
            context = FrameContext(frame=normalized, now=now)
            self._evaluate_scenarios(context)
            self._diagnostics.frame_processing_completed(context)

    def _apply_bridge_updates(self) -> None:
        for scenario, worker in zip(self._scenarios, self._workers, strict=True):
            for update in worker.drain_updates():
                scenario.apply_livesplit_update(update)

    def _evaluate_scenarios(self, context: FrameContext) -> None:
        for scenario_index, (scenario, worker) in enumerate(
            zip(self._scenarios, self._workers, strict=True)
        ):
            if not worker.is_available:
                continue
            try:
                action = scenario.evaluate(context)
            except Exception as error:  # noqa: BLE001
                self._diagnostics.scenario_evaluation_failed(scenario_index, error)
                continue
            snapshot = scenario.current_snapshot
            if action is not None and snapshot is not None:
                worker.submit_action(action, snapshot)
