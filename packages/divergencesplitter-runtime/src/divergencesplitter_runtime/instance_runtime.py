"""Runtime objects belonging to one configured scenario instance."""

from dataclasses import dataclass

from divergencesplitter.scenario.models import Scenario

from divergencesplitter_runtime.livesplit.worker import BridgeWorker
from divergencesplitter_runtime.scenario import ScenarioRuntime


@dataclass(frozen=True)
class InstanceRuntime:
    """Pair a scenario definition with its runtime and LiveSplit worker."""

    scenario: Scenario
    scenario_runtime: ScenarioRuntime
    worker: BridgeWorker
