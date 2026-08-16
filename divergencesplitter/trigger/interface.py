"""Trigger contract."""

from typing import Protocol

from divergencesplitter.models import FrameContext


class Trigger(Protocol):
    """Current-value logical decision contract.

    Implementations evaluate a single ``FrameContext`` and return whether it
    satisfies the trigger. They must be stateless and immutable value objects,
    so the same definition can be shared across scenarios.

    History-dependent state (previous result, edge baseline, hold start time,
    and similar time series) is owned by the scenario runtime per scenario,
    not by the trigger definition.
    """

    def evaluate(self, context: FrameContext) -> bool: ...
