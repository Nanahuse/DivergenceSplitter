from divergencesplitter.frame.models import FrameContext
from divergencesplitter.rule.action import Action
from divergencesplitter.rule.rule import Rule


class RuleSequence:
    """Evaluate a non-empty sequence of rules, one action per frame."""

    def __init__(self, *rules: Rule) -> None:
        if not rules:
            raise ValueError("RuleSequence requires at least one rule")
        if any(not isinstance(rule, Rule) for rule in rules):
            raise TypeError("RuleSequence accepts Rule instances only")
        self._rules = rules
        self._index = 0

    @property
    def rules(self) -> tuple[Rule, ...]:
        return self._rules

    @property
    def active_rule(self) -> Rule | None:
        if self._index >= len(self._rules):
            return None
        return self._rules[self._index]

    @property
    def active_rule_index(self) -> int | None:
        return None if self.active_rule is None else self._index

    def evaluate(self, context: FrameContext) -> Action | None:
        rule = self.active_rule
        if rule is None:
            return None
        action = rule.evaluate(context)
        if action is None:
            return None
        self._index += 1
        return action

    def reset(self) -> None:
        self._index = 0
        for rule in self._rules:
            rule.reset()
