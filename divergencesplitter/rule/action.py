"""Immutable value returned to the upper processing layer when a Rule fires.

``Action`` only identifies the operation to apply; creating one does not mean
the operation succeeded, and executing it is the responsibility of the layer
above Rules.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    """Identify a LiveSplit operation on a scenario's target.

    ``scenario_id`` and ``target_id`` address the scenario and its LiveSplit
    target, and ``operation`` selects the operation kind (for example Split,
    Undo, or Reset). The value is immutable and carries no execution result.
    """

    scenario_id: str
    target_id: str
    operation: str
