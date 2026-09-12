"""Scenario configuration models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from divergencesplitter.condition.interface import Condition
    from divergencesplitter.rule.interface import ScenarioRule


@dataclass(frozen=True)
class Scenario:
    """A pre-constructed scenario: what to judge and which actions to fire."""

    start_condition: Condition
    reset_condition: Condition | None
    incomplete_condition: Condition | None
    splits: tuple[tuple[ScenarioRule, ...] | None, ...]
