"""Runtime execution unit pairing one LiveSplit connection with one scenario."""

from dataclasses import dataclass

from divergencesplitter.livesplit.models import LiveSplitConnection
from divergencesplitter.scenario.models import Scenario


@dataclass(frozen=True)
class ScenarioInstance:
    """A connection and scenario that the runtime runs as one independent unit."""

    connection: LiveSplitConnection
    scenario: Scenario
