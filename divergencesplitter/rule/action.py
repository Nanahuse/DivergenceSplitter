from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    scenario_id: str
    target_id: str
    operation: str
