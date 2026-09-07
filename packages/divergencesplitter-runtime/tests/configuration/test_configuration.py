import tempfile
import unittest
from pathlib import Path

from divergencesplitter import (
    LiveSplitConnection,
    Scenario,
)
from divergencesplitter_runtime import (
    LiveSplitSnapshot,
    ScenarioInstance,
    TimerPhase,
    load_scenario_module,
    validate_instances,
    validate_scenario,
    validate_split_count,
)
from divergencesplitter_runtime.configuration.scenario_module import (
    ScenarioModuleExecutionError,
    ScenarioModuleValidationError,
)


class PassiveCondition:
    @property
    def children(self) -> tuple:
        return ()

    def evaluate(self, context: object, *, is_short_circuited: bool = False) -> bool:
        return False

    def reset(self) -> None:
        return None


def make_scenario(
    *,
    reset_conditions: tuple[PassiveCondition, ...] | None = None,
    slots: int = 0,
) -> Scenario:
    return Scenario(
        reset_conditions=(PassiveCondition(),)
        if reset_conditions is None
        else reset_conditions,
        splits=(None,) * slots,
    )


def make_instance(
    rpc_endpoint: str = "rpc",
    event_endpoint: str = "event",
    *,
    reset_conditions: tuple[PassiveCondition, ...] | None = None,
    slots: int = 0,
) -> ScenarioInstance:
    return ScenarioInstance(
        connection=LiveSplitConnection(rpc_endpoint, event_endpoint),
        scenario=make_scenario(reset_conditions=reset_conditions, slots=slots),
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
    def test_loads_a_single_preconstructed_scenario(self) -> None:
        source = """
from divergencesplitter import Scenario

class Condition:
    def evaluate(self, context, *, is_short_circuited=False):
        return False
    def reset(self):
        pass

scenario = Scenario(
    reset_conditions=(Condition(),),
    splits=(None,),
)
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario_module.py"
            path.write_text(source, encoding="utf-8")
            scenario = load_scenario_module(path)

        self.assertEqual(len(scenario.splits), 1)

    def test_import_exception_is_reported_as_module_execution_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario_module.py"
            path.write_text("raise RuntimeError('broken')", encoding="utf-8")
            with self.assertRaises(ScenarioModuleExecutionError) as raised:
                load_scenario_module(path)
        self.assertIsInstance(raised.exception.error, RuntimeError)
        self.assertEqual(str(raised.exception.error), "broken")

    def test_module_system_exit_is_reported_as_execution_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario_module.py"
            path.write_text("raise SystemExit(7)", encoding="utf-8")
            with self.assertRaises(ScenarioModuleExecutionError) as raised:
                load_scenario_module(path)
        self.assertIsInstance(raised.exception.error, SystemExit)

    def test_keyboard_interrupt_is_not_wrapped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario_module.py"
            path.write_text("raise KeyboardInterrupt", encoding="utf-8")
            with self.assertRaises(KeyboardInterrupt):
                load_scenario_module(path)

    def test_missing_exports_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario_module.py"
            path.write_text("value = 1", encoding="utf-8")
            with self.assertRaises(ScenarioModuleValidationError) as raised:
                load_scenario_module(path)
        self.assertEqual(len(raised.exception.exceptions), 1)

    def test_export_type_errors_are_aggregated(self) -> None:
        source = """
scenario = object()
frame_source = object()
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario_module.py"
            path.write_text(source, encoding="utf-8")
            with self.assertRaises(ScenarioModuleValidationError) as raised:
                load_scenario_module(path)
        self.assertEqual(len(raised.exception.exceptions), 2)
        self.assertTrue(
            any(isinstance(error, TypeError) for error in raised.exception.exceptions)
        )
        self.assertTrue(
            any(isinstance(error, ValueError) for error in raised.exception.exceptions)
        )

    def test_frame_source_export_is_rejected(self) -> None:
        source = """
from divergencesplitter import Scenario

class Condition:
    def evaluate(self, context, *, is_short_circuited=False):
        return False
    def reset(self):
        pass

scenario = Scenario(
    reset_conditions=(Condition(),),
    splits=(None,),
)
frame_source = object()
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario_module.py"
            path.write_text(source, encoding="utf-8")
            with self.assertRaises(ScenarioModuleValidationError) as raised:
                load_scenario_module(path)
        self.assertIn(
            "must not export 'frame_source'",
            str(raised.exception.exceptions[0]),
        )

    def test_connection_export_is_rejected(self) -> None:
        source = """
from divergencesplitter import Scenario

class Condition:
    def evaluate(self, context, *, is_short_circuited=False):
        return False
    def reset(self):
        pass

scenario = Scenario(
    reset_conditions=(Condition(),),
    splits=(None,),
)
connection = object()
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario_module.py"
            path.write_text(source, encoding="utf-8")
            with self.assertRaises(ScenarioModuleValidationError) as raised:
                load_scenario_module(path)
        self.assertIn(
            "must not export 'connection'",
            str(raised.exception.exceptions[0]),
        )


class ConfigurationValidationTest(unittest.TestCase):
    def test_scenario_requires_reset_conditions(self) -> None:
        with self.assertRaises(ExceptionGroup) as raised:
            validate_scenario(make_scenario(reset_conditions=()))
        messages = tuple(str(error) for error in raised.exception.exceptions)
        self.assertEqual(len(messages), 1)
        self.assertTrue(any("no reset conditions" in message for message in messages))

    def test_independent_static_errors_are_aggregated(self) -> None:
        instances = (
            make_instance("", "", reset_conditions=()),
            make_instance("", ""),
        )
        with self.assertRaises(ExceptionGroup) as raised:
            validate_instances(
                tuple(
                    (instance.connection, instance.scenario) for instance in instances
                )
            )
        messages = tuple(str(error) for error in raised.exception.exceptions)
        self.assertEqual(len(messages), 7)
        self.assertTrue(any("no reset conditions" in message for message in messages))
        self.assertTrue(any("shares rpc_endpoint" in message for message in messages))
        self.assertTrue(any("shares event_endpoint" in message for message in messages))

    def test_connection_is_unique_when_either_endpoint_differs(self) -> None:
        with self.assertRaises(ExceptionGroup):
            validate_instances(
                (
                    (make_instance("rpc", "one").connection, make_scenario()),
                    (make_instance("rpc", "two").connection, make_scenario()),
                )
            )
        with self.assertRaises(ExceptionGroup):
            validate_instances(
                (
                    (make_instance("one", "event").connection, make_scenario()),
                    (make_instance("two", "event").connection, make_scenario()),
                )
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
