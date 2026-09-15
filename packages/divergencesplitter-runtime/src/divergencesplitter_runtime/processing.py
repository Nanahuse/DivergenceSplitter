"""Processing loop that coordinates frames, scenarios, and Bridge workers."""

import threading
from typing import Protocol

from divergencesplitter.clock import MonotonicTime, TimeProvider
from divergencesplitter.frame.models import (
    Frame,
    FrameContext,
    SharedFrameEvaluation,
)
from divergencesplitter.frame.normalizer import (
    FrameNormalizationError,
    FrameNormalizer,
)

from divergencesplitter_runtime.capture import LatestFrameBuffer
from divergencesplitter_runtime.instance_runtime import (
    InstanceRuntime,
    InstanceRuntimeState,
)
from divergencesplitter_runtime.livesplit.models import LiveSplitRunInfo

DEFAULT_FRAME_WAIT_SECONDS = 0.05


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

    def instance_run_changed(
        self,
        scenario_index: int,
        run_info: LiveSplitRunInfo | None,
    ) -> None: ...


class ProcessingRuntime:
    """Apply Bridge updates and evaluate all scenarios against each latest frame."""

    def __init__(
        self,
        instances: tuple[InstanceRuntime, ...],
        frame_buffer: LatestFrameBuffer,
        normalizer: FrameNormalizer,
        *,
        diagnostics: ProcessingDiagnostics,
        time_provider: TimeProvider | None = None,
    ) -> None:
        self._instances = instances
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
            frame = self._frame_buffer.take(DEFAULT_FRAME_WAIT_SECONDS)
            if self._stop_requested.is_set():
                return
            # Drain Bridge updates even when the source produces no frame, so a
            # connected instance can validate its scenario and publish its
            # lifecycle status and Run info while capture is idle.
            self._apply_bridge_updates()
            if frame is None:
                continue
            now = self._time_provider.now()
            self._diagnostics.frame_processing_started(frame, now)
            normalized = self._normalizer.normalize(frame)
            if isinstance(normalized, FrameNormalizationError):
                self._diagnostics.frame_normalization_failed(normalized)
                self.request_stop()
                return
            shared = SharedFrameEvaluation(frame=normalized, now=now)
            evaluated_condition_ids = self._evaluate_scenarios(shared)
            context = FrameContext(
                shared=shared,
                evaluated_condition_ids=evaluated_condition_ids,
            )
            self._diagnostics.frame_processing_completed(context)

    def _apply_bridge_updates(self) -> None:
        for scenario_index, instance in enumerate(self._instances):
            previous = instance.run_info
            instance.process_updates()
            current = instance.run_info
            if current != previous:
                self._diagnostics.instance_run_changed(scenario_index, current)

    def _evaluate_scenarios(self, shared: SharedFrameEvaluation) -> set[int]:
        evaluated_condition_ids: set[int] = set()
        for scenario_index, instance in enumerate(self._instances):
            scenario = instance.scenario_runtime
            worker = instance.worker
            if (
                instance.state is not InstanceRuntimeState.READY
                or scenario is None
                or not worker.is_available
            ):
                continue
            # Each scenario gets its own context, but all contexts of a frame
            # share the preprocessing and detection caches.
            context = FrameContext(shared=shared)
            try:
                action = scenario.evaluate(context)
            except Exception as error:  # noqa: BLE001
                self._diagnostics.scenario_evaluation_failed(scenario_index, error)
                continue
            finally:
                evaluated_condition_ids |= context.evaluated_condition_ids
            snapshot = scenario.current_snapshot
            if action is not None and snapshot is not None:
                worker.submit_action(action, snapshot, generation=instance.generation)
        return evaluated_condition_ids
