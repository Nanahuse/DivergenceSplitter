"""Value semantics for immutable detector implementations."""

from __future__ import annotations


class ImmutableDetector:
    """Provide immutable, configuration-based equality for detectors."""

    __slots__ = ()

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        assert isinstance(other, ImmutableDetector)
        return self._configuration_key() == other._configuration_key()

    def __hash__(self) -> int:
        return hash((type(self), self._configuration_key()))

    def _configuration_key(self) -> tuple[object, ...]:
        """Return the validated values that identify an equivalent detector."""
        raise NotImplementedError
