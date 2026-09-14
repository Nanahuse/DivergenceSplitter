"""Processing-thread owner of one independent scenario execution session."""

import logging
from dataclasses import dataclass
from enum import Enum, auto

from divergencesplitter.scenario.models import Scenario

from divergencesplitter_runtime.configuration.validation import validate_split_count
from divergencesplitter_runtime.livesplit.models import LiveSplitUpdateKind
from divergencesplitter_runtime.livesplit.worker import BridgeWorker, BridgeWorkerState
from divergencesplitter_runtime.scenario import ScenarioRuntime


class InstanceRuntimeState(Enum):
    CONNECTING = auto()
    READY = auto()
    FAILED = auto()
    STOPPED = auto()


@dataclass(frozen=True)
class InstanceStatus:
    """Immutable, indexed lifecycle snapshot for Diagnostics and UI."""

    scenario_index: int
    state: InstanceRuntimeState
    error: str | None = None


class InstanceRuntime:
    """Create and discard ScenarioRuntime only on the Processing thread."""

    def __init__(
        self,
        scenario: Scenario,
        worker: BridgeWorker,
        *,
        logger: logging.Logger | logging.LoggerAdapter | None = None,
    ) -> None:
        self.scenario = scenario
        self.worker = worker
        self._logger = logger or logging.getLogger(__name__)
        self.scenario_runtime: ScenarioRuntime | None = None
        self._state = InstanceRuntimeState.CONNECTING
        self.generation = 0
        self.error: Exception | None = None
        self._initialized_once = False
        self._log("instance.connecting")

    @property
    def state(self) -> InstanceRuntimeState:
        if self._state in (InstanceRuntimeState.FAILED, InstanceRuntimeState.STOPPED):
            return self._state
        state, generation = self.worker.connection_state
        if state is BridgeWorkerState.FAILED:
            return InstanceRuntimeState.FAILED
        if state is BridgeWorkerState.STOPPED:
            return InstanceRuntimeState.STOPPED
        if generation != self.generation or state is BridgeWorkerState.CONNECTING:
            return InstanceRuntimeState.CONNECTING
        return self._state

    def status(self, scenario_index: int) -> InstanceStatus:
        state = self.state
        error = self.error or self.worker.failure
        return InstanceStatus(scenario_index, state, str(error) if error else None)

    def process_updates(self) -> None:
        if self._state in (InstanceRuntimeState.FAILED, InstanceRuntimeState.STOPPED):
            return
        state, generation, updates = self.worker.drain_connection_updates()
        if generation != self.generation:
            self.scenario_runtime = None
            self.generation = generation
            self._state = InstanceRuntimeState.CONNECTING
            self._log("instance.connection_lost")
            self._log("instance.connecting")
        if state in (BridgeWorkerState.FAILED, BridgeWorkerState.STOPPED):
            self.scenario_runtime = None
            self._state = InstanceRuntimeState[state.name]
            self._log(f"instance.{state.name.lower()}")
            return
        for update in updates:
            if update.kind is LiveSplitUpdateKind.INITIAL:
                self._state = InstanceRuntimeState.CONNECTING
                self.scenario_runtime = None
                try:
                    validate_split_count(self.scenario, update.snapshot)
                except ValueError as error:
                    self.error = error
                    self._state = InstanceRuntimeState.FAILED
                    self._log("instance.validation_failed", error=str(error))
                    self.worker.request_stop()
                    return
                runtime = ScenarioRuntime(self.scenario, logger=self._logger)
                runtime.apply_livesplit_update(update)
                self.scenario_runtime = runtime
                self._state = InstanceRuntimeState.READY
                if self._initialized_once:
                    self._log("instance.reinitialized")
                self._initialized_once = True
                self._log("instance.ready")
            elif self.scenario_runtime is not None:
                self.scenario_runtime.apply_livesplit_update(update)

    def stop(self) -> None:
        """Called after Processing has joined, so it cannot race evaluation."""
        self.scenario_runtime = None
        self._state = InstanceRuntimeState.STOPPED

    def _log(self, event: str, **fields: object) -> None:
        try:
            self._logger.info(event, extra={"event": event, **fields})
        except Exception:  # noqa: BLE001, S110
            pass
