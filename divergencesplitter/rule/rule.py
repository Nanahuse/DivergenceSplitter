from dataclasses import dataclass

from divergencesplitter.models import FrameContext
from divergencesplitter.rule.action import Action
from divergencesplitter.rule.interface import Condition


@dataclass
class Rule:
    condition: Condition
    action: Action

    def evaluate(self, context: FrameContext) -> Action | None:
        result = self.condition.evaluate(context)
        if type(result) is not bool:
            raise TypeError(
                "root condition must return a strict bool, "
                f"got {type(result).__name__}: {result!r}"
            )
        if result:
            return self.action
        return None

    def reset(self) -> None:
        self.condition.reset()
