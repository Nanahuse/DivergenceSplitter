"""Rule binding a root Condition to the Action returned when it fires."""

from dataclasses import dataclass

from divergencesplitter.models import FrameContext
from divergencesplitter.rule.action import Action
from divergencesplitter.rule.interface import Condition


@dataclass
class Rule:
    """Return ``action`` only when ``condition`` evaluates to ``True``.

    The root condition is always evaluated without short-circuiting, so it must
    return a strict ``bool``. Any other value (``None``, ``int``, numpy bool,
    ...) is a contract violation and raises :class:`TypeError` immediately,
    without rolling back state. Rules never execute actions; they only return
    them. ``reset`` propagates to the root condition so the whole condition
    tree reinitializes.
    """

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
