"""Frame data models.

Array copy and ownership rules are guaranteed by each frame source
implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from divergencesplitter.clock import MonotonicTime
from divergencesplitter.frame.cache import SharedFrameCache

ImageArray = np.ndarray


@dataclass(frozen=True)
class Frame:
    """A captured image and its monotonic acquisition time."""

    image: ImageArray
    captured_at: MonotonicTime


@dataclass(frozen=True, eq=False)
class SharedFrameEvaluation:
    """Frame facts and caches shared by every scenario context of one frame."""

    frame: Frame
    now: MonotonicTime
    cache: SharedFrameCache = field(default_factory=SharedFrameCache)


class FrameContext:
    """Per-scenario evaluation state built over a shared frame evaluation.

    ``context.frame`` and ``context.now`` delegate to the shared evaluation, so
    every context created for one frame observes the same values. The
    preprocessing and detection caches are shared through ``context.cache``,
    while ``evaluated_condition_ids`` stays local to each context.

    ``FrameContext(frame=..., now=...)`` builds an independent shared
    evaluation for standalone use, while ``FrameContext(shared=...)`` lets
    several contexts share one frame's caches.
    """

    __slots__ = ("evaluated_condition_ids", "shared")

    def __init__(
        self,
        frame: Frame | None = None,
        now: MonotonicTime | None = None,
        *,
        shared: SharedFrameEvaluation | None = None,
        evaluated_condition_ids: set[int] | None = None,
    ) -> None:
        if shared is None:
            if frame is None or now is None:
                raise TypeError(
                    "FrameContext requires frame and now, or a shared evaluation"
                )
            shared = SharedFrameEvaluation(frame=frame, now=now)
        self.shared = shared
        self.evaluated_condition_ids = (
            set() if evaluated_condition_ids is None else evaluated_condition_ids
        )

    @property
    def frame(self) -> Frame:
        return self.shared.frame

    @property
    def now(self) -> MonotonicTime:
        return self.shared.now

    @property
    def cache(self) -> SharedFrameCache:
        return self.shared.cache
