import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from divergencesplitter import (
    LiveSplitConnection,
    LiveSplitSnapshot,
    Scenario,
    TimerPhase,
    load_scenario_module,
    validate_scenarios,
    validate_split_count,
)


class PassiveCondition:
    def evaluate(self, context: object, *, is_short_circuited: bool = False) -> bool:
        return False

    def reset(self) -> None:
        return None


def make_scenario(
    rpc_endpoint: str = "rpc",
    event_endpoint: str = "event",
    *,
    reset_conditions: tuple[PassiveCondition, ...] | None = None,
    slots: int = 0,
) -> Scenario:
    return Scenario(
        connection=LiveSplitConnection(rpc_endpoint, event_endpoint),
        reset_conditions=(PassiveCondition(),)
        if reset_conditions is None
        else reset_conditions,
        splits=(None,) * slots,
    )


def make_snapshot(
    split_count: int,
    *,
    phase: TimerPhase = TimerPhase.RUNNING,
) -> LiveSplitSnapshot:
    return LiveSplitSnapshot(
        session_id=1,
        state_revision=0,
        event_sequence=0,
        phase=phase,
        split_index=-1 if phase is TimerPhase.NOT_RUNNING else 0,
        split_count=split_count,
    )


class ScenarioModuleLoadingTest(unittest.TestCase):
    def test_loads_preconstructed_exports_without_preparing_source(self) -> None:
        source = """
from divergencesplitter import LiveSplitConnection, Scenario

class Condition:
    def evaluate(self, context, *, is_short_circuited=False):
        return False
    def reset(self):
        pass

class Source:
    prepared = False
    def prepare(self):
        self.prepared = True

scenarios = (
    Scenario(
        connection=LiveSplitConnection('rpc', 'event'),
        reset_conditions=(Condition(),),
        splits=(None,),
    ),
)
frame_source = Source()
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario_module.py"
            path.write_text(source, encoding="utf-8")
            scenarios, frame_source = load_scenario_module(path)

        self.assertEqual(scenarios[0].connection.rpc_endpoint, "rpc")
        self.assertFalse(cast("Any", frame_source).prepared)

    def test_import_exception_is_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario_module.py"
            path.write_text("raise RuntimeError('broken')", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "broken"):
                load_scenario_module(path)

    def test_missing_exports_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario_module.py"
            path.write_text("value = 1", encoding="utf-8")
            with self.assertRaises(ExceptionGroup) as raised:
                load_scenario_module(path)
        self.assertEqual(len(raised.exception.exceptions), 2)


class ConfigurationValidationTest(unittest.TestCase):
    def test_independent_static_errors_are_aggregated(self) -> None:
        scenarios = (
            make_scenario("", "", reset_conditions=()),
            make_scenario("", ""),
        )
        with self.assertRaises(ExceptionGroup) as raised:
            validate_scenarios(scenarios)
        messages = tuple(str(error) for error in raised.exception.exceptions)
        self.assertEqual(len(messages), 7)
        self.assertTrue(any("no reset conditions" in message for message in messages))
        self.assertTrue(any("shares rpc_endpoint" in message for message in messages))
        self.assertTrue(any("shares event_endpoint" in message for message in messages))

    def test_connection_is_unique_when_either_endpoint_differs(self) -> None:
        with self.assertRaises(ExceptionGroup):
            validate_scenarios(
                (make_scenario("rpc", "one"), make_scenario("rpc", "two"))
            )
        with self.assertRaises(ExceptionGroup):
            validate_scenarios(
                (make_scenario("one", "event"), make_scenario("two", "event"))
            )

    def test_split_slots_allow_split_count_plus_one(self) -> None:
        validate_split_count(make_scenario(slots=3), make_snapshot(2))
        with self.assertRaises(ValueError):
            validate_split_count(make_scenario(slots=4), make_snapshot(2))

    def test_unloaded_run_defers_split_count_validation(self) -> None:
        validate_split_count(
            make_scenario(slots=20),
            make_snapshot(0, phase=TimerPhase.NOT_RUNNING),
        )


if __name__ == "__main__":
    unittest.main()
