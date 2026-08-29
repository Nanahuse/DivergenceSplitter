"""Scenario configuration models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from divergencesplitter.livesplit.models import LiveSplitConnection

if TYPE_CHECKING:
    from divergencesplitter.condition.interface import Condition
    from divergencesplitter.rule.rule import Rule


@dataclass(frozen=True)
class Scenario:
    """A pre-constructed scenario and its LiveSplit destination."""

    connection: LiveSplitConnection
    reset_conditions: tuple[Condition, ...]
    splits: tuple[tuple[Rule, ...] | None, ...]
