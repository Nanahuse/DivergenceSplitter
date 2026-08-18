import unittest

import numpy as np

from divergencesplitter.detector.common import evaluate as evaluate_detector
from divergencesplitter.models import (
    DetectionResult,
    Frame,
    FrameContext,
    LiveSplitSnapshot,
    MonotonicTime,
    TimerOperation,
    TimerPhase,
)
from divergencesplitter.rule import Rule
from divergencesplitter.scenario import Scenario, process_scenarios

EMPTY = np.zeros((1,), dtype=np.uint8)


def make_context(now_nanoseconds: int = 0) -> FrameContext:
    return FrameContext(
        frame=Frame(image=EMPTY), now=MonotonicTime(nanoseconds=now_nanoseconds)
    )


def make_snapshot(
    target_id: str = "t",
    phase: TimerPhase = TimerPhase.RUNNING,
    split_index: int = 0,
    split_count: int = 3,
    is_fresh: bool = True,
) -> LiveSplitSnapshot:
    return LiveSplitSnapshot(
        target_id=target_id,
        state_revision=0,
        session_id=0,
        event_sequence=0,
        phase=phase,
        split_index=split_index,
        split_count=split_count,
        is_fresh=is_fresh,
    )


def make_rule(
    scenario_id: str = "s",
    target_id: str = "t",
    rule_id: str = "r",
    initial_states=None,
    evaluator=None,
) -> Rule:
    if evaluator is None:
        evaluator = lambda context, evaluation: False
    return Rule(
        scenario_id=scenario_id,
        target_id=target_id,
        rule_id=rule_id,
        operation=TimerOperation.SPLIT,
        priority=0,
        initial_states=initial_states if initial_states is not None else {},
        evaluator=evaluator,
    )


def static_selector(rule_id: str = "r", scenario_id: str = "s", target_id: str = "t"):
    def selector(snapshot: LiveSplitSnapshot):
        return {
            rule_id: lambda: make_rule(
                scenario_id=scenario_id, target_id=target_id, rule_id=rule_id
            )
        }

    return selector


def advancing_rule(rule_id: str = "r", received=None) -> Rule:
    def step(state):
        if received is not None:
            received.append(state)
        return (False, state + 1)

    return make_rule(
        rule_id=rule_id,
        initial_states={"node": lambda: 0},
        evaluator=lambda context, evaluation: evaluation.transition("node", step),
    )


class ScenarioSyncTest(unittest.TestCase):
    def test_sync_generates_rule(self):
        scenario = Scenario("s", "t", static_selector("r"))
        scenario.commit_sync(scenario.sync(make_snapshot()))
        self.assertIn("r", scenario.rules)

    def test_sync_preserves_existing_rule(self):
        scenario = Scenario("s", "t", static_selector("r"))
        scenario.commit_sync(scenario.sync(make_snapshot()))
        first = scenario.rules["r"]
        scenario.commit_sync(scenario.sync(make_snapshot()))
        self.assertIs(scenario.rules["r"], first)

    def test_sync_destroys_removed_rule(self):
        def selector(snapshot: LiveSplitSnapshot):
            if snapshot.split_index == 0:
                return {"r": lambda: make_rule(rule_id="r")}
            return {}

        scenario = Scenario("s", "t", selector)
        scenario.commit_sync(scenario.sync(make_snapshot(split_index=0)))
        self.assertIn("r", scenario.rules)
        scenario.commit_sync(scenario.sync(make_snapshot(split_index=1)))
        self.assertEqual(dict(scenario.rules), {})

    def test_force_sync_regenerates_all_rules_with_fresh_state(self):
        received = []

        def factory() -> Rule:
            return advancing_rule("r", received)

        scenario = Scenario("s", "t", lambda snapshot: {"r": factory})
        scenario.commit_sync(scenario.sync(make_snapshot()))
        first = scenario.rules["r"]
        process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual(received, [0])
        scenario.commit_sync(scenario.sync(make_snapshot(), force=True))
        self.assertIsNot(scenario.rules["r"], first)
        received.clear()
        process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual(received, [0])

    def test_sync_failure_keeps_existing_set(self):
        broken = {"active": False}

        def factory() -> Rule:
            raise RuntimeError("boom")

        def selector(snapshot: LiveSplitSnapshot):
            if broken["active"]:
                return {"r": lambda: make_rule(rule_id="r"), "new": factory}
            return {"r": lambda: make_rule(rule_id="r")}

        scenario = Scenario("s", "t", selector)
        scenario.commit_sync(scenario.sync(make_snapshot()))
        first = scenario.rules["r"]
        broken["active"] = True
        with self.assertRaises(RuntimeError):
            scenario.sync(make_snapshot())
        self.assertIs(scenario.rules["r"], first)

    def test_sync_factory_failure_does_not_evaluate_old_rules(self):
        received = []
        broken = {"active": False}

        def factory() -> Rule:
            raise RuntimeError("boom")

        def selector(snapshot: LiveSplitSnapshot):
            if broken["active"]:
                return {"r": lambda: advancing_rule("r", received), "new": factory}
            return {"r": lambda: advancing_rule("r", received)}

        scenario = Scenario("s", "t", selector)
        process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual(received, [0])
        received.clear()
        broken["active"] = True
        with self.assertRaises(RuntimeError):
            process_scenarios(
                [scenario], {"t": make_snapshot(split_index=1)}, make_context()
            )
        self.assertEqual(received, [])
        broken["active"] = False
        process_scenarios(
            [scenario], {"t": make_snapshot(split_index=1)}, make_context()
        )
        self.assertEqual(received, [1])

    def test_sync_rejects_factory_identity_mismatch(self):
        scenario = Scenario(
            "s", "t", lambda snapshot: {"expected": lambda: make_rule(rule_id="other")}
        )
        with self.assertRaises(ValueError):
            scenario.sync(make_snapshot())

    def test_sync_rejects_rule_scenario_mismatch(self):
        scenario = Scenario(
            "s",
            "t",
            lambda snapshot: {"r": lambda: make_rule(scenario_id="other", rule_id="r")},
        )
        with self.assertRaises(ValueError):
            scenario.sync(make_snapshot())

    def test_sync_rejects_rule_target_mismatch(self):
        scenario = Scenario(
            "s",
            "t",
            lambda snapshot: {"r": lambda: make_rule(target_id="other", rule_id="r")},
        )
        with self.assertRaises(ValueError):
            scenario.sync(make_snapshot())

    def test_sync_rejects_snapshot_target_mismatch(self):
        scenario = Scenario("s", "t", static_selector())
        with self.assertRaises(ValueError):
            scenario.sync(make_snapshot(target_id="other"))

    def test_sync_stage_next_rules_is_read_only(self):
        scenario = Scenario("s", "t", static_selector("r"))
        stage = scenario.sync(make_snapshot())
        with self.assertRaises(TypeError):
            stage._next_rules["x"] = object()  # ty: ignore


class ScenarioSurfaceTest(unittest.TestCase):
    def test_rules_is_read_only_view(self):
        scenario = Scenario("s", "t", static_selector("r"))
        scenario.commit_sync(scenario.sync(make_snapshot()))
        with self.assertRaises(TypeError):
            scenario.rules["r"] = object()  # ty: ignore

    def test_resync_required_is_read_only(self):
        scenario = Scenario("s", "t", static_selector("r"))
        with self.assertRaises(AttributeError):
            object.__setattr__(scenario, "resync_required", True)

    def test_foreign_sync_stage_rejected(self):
        s1 = Scenario("s1", "t1", static_selector("r", "s1", "t1"))
        s2 = Scenario("s2", "t2", static_selector("r", "s2", "t2"))
        stage = s1.sync(make_snapshot(target_id="t1"))
        with self.assertRaises(ValueError):
            s2.commit_sync(stage)

    def test_stale_sync_stage_rejected(self):
        scenario = Scenario("s", "t", static_selector("r"))
        first = scenario.sync(make_snapshot())
        scenario.sync(make_snapshot())
        with self.assertRaises(ValueError):
            scenario.commit_sync(first)


class ProcessScenariosTest(unittest.TestCase):
    def test_success_frame_commits_all_rules(self):
        received = []
        scenario = Scenario(
            "s", "t", lambda snapshot: {"a": lambda: advancing_rule("a", received)}
        )
        process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual(received, [0, 1])

    def test_evaluation_failure_rolls_back_all_rules(self):
        received = []
        failing = {"on": True}

        def rule_a() -> Rule:
            return advancing_rule("a", received)

        def rule_b() -> Rule:
            def evaluator(context, evaluation):
                if failing["on"]:
                    raise RuntimeError("boom")
                return False

            return make_rule(rule_id="b", evaluator=evaluator)

        scenario = Scenario("s", "t", lambda snapshot: {"a": rule_a, "b": rule_b})
        with self.assertRaises(RuntimeError):
            process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual(received, [0])
        failing["on"] = False
        received.clear()
        process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual(received, [0])

    def test_multiple_candidates_collected_in_one_frame(self):
        scenario = Scenario(
            "s",
            "t",
            lambda snapshot: {
                "a": lambda: make_rule(rule_id="a", evaluator=lambda c, e: True),
                "b": lambda: make_rule(rule_id="b", evaluator=lambda c, e: True),
            },
        )
        result = process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual({candidate.rule_id for candidate in result}, {"a", "b"})
        self.assertTrue(all(candidate.target_id == "t" for candidate in result))

    def test_sync_failure_aborts_all_scenarios(self):
        broken = {"active": False}

        def factory() -> Rule:
            raise RuntimeError("boom")

        def selector(snapshot: LiveSplitSnapshot):
            if broken["active"]:
                return {"r": lambda: make_rule(rule_id="r"), "new": factory}
            return {
                "r": lambda: make_rule(scenario_id="s2", target_id="t2", rule_id="r")
            }

        s1 = Scenario("s1", "t1", static_selector("r", "s1", "t1"))
        s2 = Scenario("s2", "t2", selector)
        snap1 = make_snapshot(target_id="t1")
        snap2 = make_snapshot(target_id="t2")
        process_scenarios([s1, s2], {"t1": snap1, "t2": snap2}, make_context())
        first = s1.rules["r"]
        broken["active"] = True
        with self.assertRaises(RuntimeError):
            process_scenarios([s1, s2], {"t1": snap1, "t2": snap2}, make_context())
        self.assertIs(s1.rules["r"], first)

    def test_all_rules_share_same_context(self):
        seen = []

        def evaluator(context, evaluation):
            seen.append(context)
            return False

        scenario = Scenario(
            "s",
            "t",
            lambda snapshot: {
                "a": lambda: make_rule(rule_id="a", evaluator=evaluator),
                "b": lambda: make_rule(rule_id="b", evaluator=evaluator),
            },
        )
        context = make_context()
        process_scenarios([scenario], {"t": make_snapshot()}, context)
        self.assertEqual(seen, [context, context])
        self.assertIs(seen[0], context)
        self.assertIs(seen[1], context)

    def test_multiple_scenarios_share_same_context(self):
        seen = []

        def evaluator(context, evaluation):
            seen.append(context)
            return False

        s1 = Scenario(
            "s1",
            "t1",
            lambda snapshot: {
                "a": lambda: make_rule(
                    scenario_id="s1", target_id="t1", rule_id="a", evaluator=evaluator
                )
            },
        )
        s2 = Scenario(
            "s2",
            "t2",
            lambda snapshot: {
                "a": lambda: make_rule(
                    scenario_id="s2", target_id="t2", rule_id="a", evaluator=evaluator
                )
            },
        )
        context = make_context()
        snapshots = {
            "t1": make_snapshot(target_id="t1"),
            "t2": make_snapshot(target_id="t2"),
        }
        process_scenarios([s1, s2], snapshots, context)
        self.assertEqual(seen, [context, context])

    def test_process_rejects_missing_snapshot(self):
        scenario = Scenario("s", "t", static_selector())
        with self.assertRaises(KeyError):
            process_scenarios([scenario], {}, make_context())

    def test_discarded_candidate_does_not_roll_back_state(self):
        received = []

        def step(state):
            received.append(state)
            return (True, state + 1)

        def evaluator(context, evaluation):
            return evaluation.transition("node", step)

        scenario = Scenario(
            "s",
            "t",
            lambda snapshot: {
                "r": lambda: make_rule(
                    rule_id="r",
                    initial_states={"node": lambda: 0},
                    evaluator=evaluator,
                )
            },
        )
        first = process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual([candidate.rule_id for candidate in first], ["r"])
        second = process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual([candidate.rule_id for candidate in second], ["r"])
        self.assertEqual(received, [0, 1])

    def test_duplicate_scenario_id_rejected_before_progress(self):
        calls = []

        def factory(rule_id: str, scenario_id: str, target_id: str):
            def evaluator(context, evaluation):
                calls.append(rule_id)
                return False

            return lambda: make_rule(
                scenario_id=scenario_id,
                target_id=target_id,
                rule_id=rule_id,
                evaluator=evaluator,
            )

        s1 = Scenario("dup", "t1", lambda snapshot: {"r": factory("r", "dup", "t1")})
        s2 = Scenario("dup", "t2", lambda snapshot: {"r": factory("r", "dup", "t2")})
        snap1 = make_snapshot(target_id="t1")
        snap2 = make_snapshot(target_id="t2")
        s1.commit_sync(s1.sync(snap1))
        s2.commit_sync(s2.sync(snap2))
        process_scenarios([s1], {"t1": snap1}, make_context())
        process_scenarios([s2], {"t2": snap2}, make_context())
        self.assertEqual(calls, ["r", "r"])
        calls.clear()
        with self.assertRaises(ValueError):
            process_scenarios([s1, s2], {"t1": snap1, "t2": snap2}, make_context())
        self.assertEqual(calls, [])
        self.assertFalse(s1.resync_required)
        self.assertFalse(s2.resync_required)

    def test_duplicate_target_id_rejected_before_progress(self):
        calls = []

        def factory(rule_id: str, scenario_id: str, target_id: str):
            def evaluator(context, evaluation):
                calls.append(rule_id)
                return False

            return lambda: make_rule(
                scenario_id=scenario_id,
                target_id=target_id,
                rule_id=rule_id,
                evaluator=evaluator,
            )

        s1 = Scenario("s1", "t", lambda snapshot: {"r": factory("r", "s1", "t")})
        s2 = Scenario("s2", "t", lambda snapshot: {"r": factory("r", "s2", "t")})
        snap = make_snapshot(target_id="t")
        s1.commit_sync(s1.sync(snap))
        s2.commit_sync(s2.sync(snap))
        process_scenarios([s1], {"t": snap}, make_context())
        process_scenarios([s2], {"t": snap}, make_context())
        self.assertEqual(calls, ["r", "r"])
        calls.clear()
        with self.assertRaises(ValueError):
            process_scenarios([s1, s2], {"t": snap}, make_context())
        self.assertEqual(calls, [])
        self.assertFalse(s1.resync_required)
        self.assertFalse(s2.resync_required)


class FreshnessTest(unittest.TestCase):
    def test_stale_snapshot_stops_evaluation(self):
        received = []
        scenario = Scenario(
            "s", "t", lambda snapshot: {"r": lambda: advancing_rule("r", received)}
        )
        process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual(received, [0])
        received.clear()
        result = process_scenarios(
            [scenario], {"t": make_snapshot(is_fresh=False)}, make_context()
        )
        self.assertEqual(result, ())
        self.assertEqual(received, [])
        self.assertTrue(scenario.resync_required)

    def test_fresh_recovery_regenerates_rules(self):
        received = []

        def factory() -> Rule:
            return advancing_rule("r", received)

        scenario = Scenario("s", "t", lambda snapshot: {"r": factory})
        process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual(received, [0])
        first = scenario.rules["r"]
        process_scenarios(
            [scenario], {"t": make_snapshot(is_fresh=False)}, make_context()
        )
        self.assertTrue(scenario.resync_required)
        received.clear()
        process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual(received, [0])
        self.assertIsNot(scenario.rules["r"], first)
        self.assertFalse(scenario.resync_required)


class SnapshotFollowTest(unittest.TestCase):
    def test_progress_swaps_rule_set(self):
        def selector(snapshot: LiveSplitSnapshot):
            if snapshot.phase == TimerPhase.ENDED:
                return {}
            if snapshot.split_index == 0:
                return {"p0": lambda: make_rule(rule_id="p0")}
            if snapshot.split_index == 1:
                return {"p1": lambda: make_rule(rule_id="p1")}
            return {}

        scenario = Scenario("s", "t", selector)
        scenario.commit_sync(scenario.sync(make_snapshot(split_index=0)))
        self.assertIn("p0", scenario.rules)
        scenario.commit_sync(scenario.sync(make_snapshot(split_index=1)))
        self.assertIn("p1", scenario.rules)
        self.assertNotIn("p0", scenario.rules)

    def test_finish_removes_progress_rules(self):
        def selector(snapshot: LiveSplitSnapshot):
            if snapshot.phase == TimerPhase.ENDED:
                return {}
            if snapshot.split_index == 0:
                return {"p0": lambda: make_rule(rule_id="p0")}
            return {}

        scenario = Scenario("s", "t", selector)
        scenario.commit_sync(scenario.sync(make_snapshot(split_index=0)))
        self.assertIn("p0", scenario.rules)
        scenario.commit_sync(
            scenario.sync(make_snapshot(split_index=0, phase=TimerPhase.ENDED))
        )
        self.assertEqual(dict(scenario.rules), {})

    def test_finish_then_undo_regenerates_fresh_rule(self):
        received = []

        def factory() -> Rule:
            return advancing_rule("p0", received)

        def selector(snapshot: LiveSplitSnapshot):
            if snapshot.phase == TimerPhase.ENDED:
                return {}
            if snapshot.split_index == 0:
                return {"p0": factory}
            return {}

        scenario = Scenario("s", "t", selector)
        process_scenarios(
            [scenario], {"t": make_snapshot(split_index=0)}, make_context()
        )
        self.assertEqual(received, [0])
        process_scenarios(
            [scenario],
            {"t": make_snapshot(split_index=0, phase=TimerPhase.ENDED)},
            make_context(),
        )
        self.assertEqual(dict(scenario.rules), {})
        received.clear()
        process_scenarios(
            [scenario], {"t": make_snapshot(split_index=0)}, make_context()
        )
        self.assertEqual(received, [0])

    def test_reset_rule_present_in_all_states(self):
        def selector(snapshot: LiveSplitSnapshot):
            rules = {}
            if snapshot.phase != TimerPhase.ENDED and snapshot.split_index == 0:
                rules["p0"] = lambda: make_rule(rule_id="p0")
            rules["reset"] = lambda: make_rule(rule_id="reset")
            return rules

        scenario = Scenario("s", "t", selector)
        scenario.commit_sync(scenario.sync(make_snapshot(split_index=0)))
        self.assertIn("reset", scenario.rules)
        self.assertIn("p0", scenario.rules)
        scenario.commit_sync(
            scenario.sync(make_snapshot(split_index=0, phase=TimerPhase.ENDED))
        )
        self.assertIn("reset", scenario.rules)
        self.assertNotIn("p0", scenario.rules)


class CountingDetector:
    def __init__(self) -> None:
        self.evaluations = 0

    def detect(self, context: FrameContext) -> DetectionResult:
        self.evaluations += 1
        return DetectionResult(score=1.0)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CountingDetector)

    def __hash__(self) -> int:
        return hash("CountingDetector")


class DetectorCacheTest(unittest.TestCase):
    def test_equivalent_detector_evaluated_once_per_frame_across_rules(self):
        detector = CountingDetector()
        equivalent = CountingDetector()

        def evaluator(context, evaluation):
            evaluate_detector(context, detector)
            evaluate_detector(context, equivalent)
            return False

        scenario = Scenario(
            "s",
            "t",
            lambda snapshot: {
                "a": lambda: make_rule(rule_id="a", evaluator=evaluator),
                "b": lambda: make_rule(rule_id="b", evaluator=evaluator),
            },
        )
        process_scenarios([scenario], {"t": make_snapshot()}, make_context())
        self.assertEqual(detector.evaluations, 1)
        self.assertEqual(equivalent.evaluations, 0)


if __name__ == "__main__":
    unittest.main()
