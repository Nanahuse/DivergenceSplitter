"""Scenario and rule definitions with source-location capture."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from divergencesplitter.condition.interface import Condition
    from divergencesplitter.rule.action import Action


def _source_location() -> tuple[str, int]:
    try:
        caller = inspect.currentframe()
        for _ in range(3):
            caller = caller.f_back if caller is not None else None
        if caller is None:
            return "<unknown>", 0
        filename = caller.f_code.co_filename
        line = caller.f_lineno
        path = Path(filename)
        if not path.is_absolute():
            return filename, line
        resolved = path.resolve()
        for parent in (resolved.parent, *resolved.parents):
            if (parent / ".git").exists():
                return resolved.relative_to(parent).as_posix(), line
        return str(path), line
    except AttributeError, OSError, RuntimeError, ValueError:
        return "<unknown>", 0


@dataclass(frozen=True)
class RuleDefinition:
    action: Action
    condition_factory: Callable[[], Condition]
    name: str | None = field(default=None, compare=False)
    source_path: str = field(init=False, compare=False)
    source_line: int = field(init=False, compare=False)

    def __post_init__(self) -> None:
        if not callable(self.condition_factory):
            raise TypeError("condition_factory must be callable")
        if self.name == "":
            object.__setattr__(self, "name", None)
        source_path, source_line = _source_location()
        object.__setattr__(self, "source_path", source_path)
        object.__setattr__(self, "source_line", source_line)


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    target_id: str
    rules: Mapping[int, tuple[RuleDefinition, ...]]

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id must not be empty")
        if not self.target_id:
            raise ValueError("target_id must not be empty")
        copied: dict[int, tuple[RuleDefinition, ...]] = {}
        for split_index, definitions in self.rules.items():
            if (
                isinstance(split_index, bool)
                or not isinstance(split_index, int)
                or split_index < 0
            ):
                raise ValueError("split keys must be non-negative integers")
            immutable_definitions = tuple(definitions)
            if not all(
                isinstance(definition, RuleDefinition)
                for definition in immutable_definitions
            ):
                raise ValueError("rules must contain RuleDefinition values")
            copied[split_index] = immutable_definitions
        object.__setattr__(self, "rules", MappingProxyType(copied))
