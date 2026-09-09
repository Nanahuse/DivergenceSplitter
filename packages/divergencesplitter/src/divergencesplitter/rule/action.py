from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    operation: str

    def __post_init__(self) -> None:
        if self.operation not in {
            "start",
            "split",
            "skip",
            "undo",
            "reset",
            "pause",
            "resume",
        }:
            raise ValueError(f"unsupported action operation: {self.operation!r}")
