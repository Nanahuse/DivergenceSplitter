"""Trigger interface and trigger implementations.

Triggers are immutable value objects shared across scenarios. Each turns a
single ``FrameContext`` into a boolean decision. History-dependent state is
owned by the scenario runtime, not by the trigger definition.
"""

from divergencesplitter.trigger.interface import Trigger
from divergencesplitter.trigger.score_threshold import ScoreThresholdTrigger

__all__ = [
    "ScoreThresholdTrigger",
    "Trigger",
]
