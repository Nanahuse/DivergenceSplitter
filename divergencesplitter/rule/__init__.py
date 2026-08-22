"""Rule and Condition contracts for evaluating a scenario's splits.

``Condition`` is the node contract of a condition tree, ``Rule`` binds a root
condition to an ``Action``, and ``Action`` is the immutable value returned to
the upper processing layer when a rule fires.
"""

from divergencesplitter.rule.action import Action
from divergencesplitter.rule.interface import Condition
from divergencesplitter.rule.rule import Rule

__all__ = [
    "Action",
    "Condition",
    "Rule",
]
