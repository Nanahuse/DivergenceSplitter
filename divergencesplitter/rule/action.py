from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    scenario_id: str
    target_id: str
    operation: str

    def __post_init__(self) -> None:
        if self.operation not in {"split", "skip", "undo", "reset", "pause", "resume"}:
            raise ValueError(f"unsupported action operation: {self.operation!r}")
