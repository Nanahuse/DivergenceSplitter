"""Thread-safe, single-flight caches shared by one frame's evaluations.

A single frame is evaluated by several scenario contexts. The preprocessing and
detection caches below live on that frame's ``SharedFrameEvaluation`` so
equivalent computations run once even when contexts are used concurrently.

Only cache bookkeeping (lookup, in-flight entry creation, result storage,
failure publication, and waiter notification) is guarded by a lock. The actual
``compute`` callable runs outside the lock, so different keys are never
serialized and nested computations cannot deadlock.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import cast

_UNSET = object()


class RecursiveFrameComputationError(RuntimeError):
    """A thread re-entered a frame cache key it is already computing."""


class _InFlight:
    """One key's shared computation state and its waiter notification event."""

    __slots__ = ("computing", "error", "event", "owner_ident", "value")

    def __init__(self, owner_ident: int) -> None:
        self.event = threading.Event()
        self.computing = True
        self.owner_ident = owner_ident
        self.value: object = _UNSET
        self.error: BaseException | None = None

    @classmethod
    def already_computed(cls, value: object) -> _InFlight:
        entry = cls(owner_ident=-1)
        entry.value = value
        entry.computing = False
        entry.event.set()
        return entry


class _SingleFlightCache:
    """Run at most one computation per key without serializing other keys."""

    __slots__ = ("_entries", "_lock")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[object, _InFlight] = {}

    def get(self, key: object, compute: Callable[[], object]) -> object:
        ident = threading.get_ident()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _InFlight(ident)
                self._entries[key] = entry
                owner = True
            elif entry.computing:
                if entry.owner_ident == ident:
                    raise RecursiveFrameComputationError(
                        f"recursive frame computation for {key!r}"
                    )
                owner = False
            else:
                return entry.value
        if not owner:
            entry.event.wait()
            if entry.error is not None:
                raise entry.error
            return entry.value
        try:
            value = compute()
        except BaseException as error:
            # Remove the failed entry before waking waiters so a later request
            # recomputes instead of observing the failure as a cached success.
            with self._lock:
                self._entries.pop(key, None)
                entry.error = error
                entry.event.set()
            raise
        with self._lock:
            entry.value = value
            entry.computing = False
            entry.event.set()
        return value

    def store_if_absent(self, key: object, value: object) -> None:
        with self._lock:
            if key not in self._entries:
                self._entries[key] = _InFlight.already_computed(value)

    def peek(self, key: object) -> object:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.computing:
                return _UNSET
            return entry.value

    def contains(self, key: object) -> bool:
        return self.peek(key) is not _UNSET

    def snapshot(self) -> tuple[tuple[object, object], ...]:
        with self._lock:
            return tuple(
                (key, entry.value)
                for key, entry in self._entries.items()
                if not entry.computing
            )

    def count(self) -> int:
        with self._lock:
            return len(self._entries)


class SharedFrameCache:
    """Preprocessing and detection caches shared by one frame's contexts."""

    __slots__ = ("_detection", "_preprocessing")

    def __init__(self) -> None:
        self._preprocessing = _SingleFlightCache()
        self._detection = _SingleFlightCache()

    def preprocessing[T](self, key: object, compute: Callable[[], T]) -> T:
        """Return the cached value for ``key``, computing it once on first use."""
        return cast(T, self._preprocessing.get(key, compute))

    def store_preprocessing(self, key: object, value: object) -> None:
        """Seed ``key`` when it is not present or in flight, without overwriting."""
        self._preprocessing.store_if_absent(key, value)

    def detection[T](self, key: object, compute: Callable[[], T]) -> T:
        """Return the cached value for ``key``, computing it once on first use."""
        return cast(T, self._detection.get(key, compute))

    def cached_detection(self, key: object) -> object | None:
        """Return a completed detection value, or ``None`` when absent."""
        value = self._detection.peek(key)
        return None if value is _UNSET else value

    def has_detection(self, key: object) -> bool:
        """Return whether ``key`` already has a completed cached value."""
        return self._detection.contains(key)

    def detection_items(self) -> tuple[tuple[object, object], ...]:
        """Return a read-only snapshot of completed detection entries."""
        return self._detection.snapshot()

    def detection_count(self) -> int:
        return self._detection.count()

    def preprocessing_count(self) -> int:
        return self._preprocessing.count()
