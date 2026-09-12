from typing import Protocol

from divergencesplitter.frame.models import FrameContext
from divergencesplitter.rule.action import Action


class ScenarioRule(Protocol):
    """Runtime contract for one rule-like scenario split entry."""

    def evaluate(self, context: FrameContext) -> Action | None: ...

    def reset(self) -> None: ...
