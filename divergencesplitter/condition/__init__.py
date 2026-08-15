"""DetectionCondition interface and condition implementations.

Conditions are stateless single-observation logical decisions: each one turns
a single ``DetectionResult`` into a boolean without caching or time series
state.
"""

from divergencesplitter.condition.interface import DetectionCondition
from divergencesplitter.condition.score_threshold import ScoreThresholdCondition

__all__ = [
    "DetectionCondition",
    "ScoreThresholdCondition",
]
