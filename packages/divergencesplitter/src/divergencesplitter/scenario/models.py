"""Scenario configuration models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from divergencesplitter.condition.interface import Condition
    from divergencesplitter.rule.rule import Rule


@dataclass(frozen=True)
class Scenario:
    """A pre-constructed scenario: what to judge and which actions to fire."""

    reset_conditions: tuple[Condition, ...]
    splits: tuple[tuple[Rule, ...] | None, ...]
