"""Shared value semantics for detectors backed by immutable configuration."""

from __future__ import annotations

from divergencesplitter.detector.models import ReferenceImage


class ConfiguredDetector[ConfigT]:
    """Store an immutable configuration and compare detectors by its value."""

    def __init__(self, config: ConfigT) -> None:
        self._config = config

    @property
    def config(self) -> ConfigT:
        return self._config

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return ()

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        assert isinstance(other, ConfiguredDetector)
        return self.config == other.config

    def __hash__(self) -> int:
        return hash((type(self), self.config))
