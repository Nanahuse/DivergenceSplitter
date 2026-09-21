"""ApplicationRuntime-level behavior not exercised by the e2e pipeline."""

from __future__ import annotations

from types import TracebackType
from typing import Self
from unittest.mock import MagicMock

import pytest
from divergencesplitter import Action, LiveSplitConnection, Rule, Scenario
from divergencesplitter.frame.models import Frame, FrameContext
from divergencesplitter.frame.normalizer import FrameNormalizer
from divergencesplitter.frame.source import (
    ErrorAction,
    FrameSourceError,
    FrameSourceState,
)
from divergencesplitter_runtime import ApplicationRuntime, ScenarioInstance


class _NeverCondition:
    @property
    def children(self) -> tuple:
        return ()

    def evaluate(
        self, context: FrameContext, *, is_short_circuited: bool = False
    ) -> bool:
        return False

    def reset(self) -> None:
        pass


class _FakeFrameSource:
    def __init__(self) -> None:
        self._normalizer = FrameNormalizer()
        self._state = FrameSourceState.NOT_READY

    @property
    def state(self) -> FrameSourceState:
        return self._state

    @property
    def normalizer(self) -> FrameNormalizer:
        return self._normalizer

    def prepare(self) -> FrameSourceError | None:
        self._state = FrameSourceState.READY
        return None

    def read(self) -> Frame | FrameSourceError:
        raise AssertionError("read is not used by this test")

    def handle_error(self, error: FrameSourceError) -> ErrorAction:
        raise AssertionError("handle_error is not used by this test")

    def close(self) -> None:
        self._state = FrameSourceState.NOT_READY

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _scenario() -> Scenario:
    condition = _NeverCondition()
    return Scenario(
        start_condition=condition,
        reset_condition=None,
        incomplete_condition=None,
        splits=((Rule(condition, Action("split")),),),
    )


def _runtime() -> ApplicationRuntime:
    return ApplicationRuntime(
        (
            ScenarioInstance(LiveSplitConnection("rpc-0", "event-0"), _scenario()),
            ScenarioInstance(LiveSplitConnection("rpc-1", "event-1"), _scenario()),
        ),
        _FakeFrameSource(),
        diagnostics=MagicMock(),
    )


def test_request_reset_all_fans_out_to_every_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    requested: list[int] = []
    for instance in runtime.instances:
        monkeypatch.setattr(
            instance,
            "request_reset",
            lambda i=instance: requested.append(i.scenario_index),
        )

    runtime.request_reset_all()

    assert requested == [0, 1]
