"""Not: logical negation of a boolean input."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Not:
    """True when the single input is ``False``."""

    def apply(self, value: bool) -> bool:
        return not value
