import unittest

import numpy as np

from divergencesplitter.logic import RisingEdge
from divergencesplitter.models import (
    ActionCandidate,
    Frame,
    FrameContext,
    LiveSplitSnapshot,
    MonotonicTime,
    TimerOperation,
    TimerPhase,
)
from divergencesplitter.rule import Rule

EMPTY = np.zeros((1,), dtype=np.uint8)


def make_context(now_nanoseconds: int = 0) -> FrameContext:
    return FrameContext(
        frame=Frame(image=EMPTY), now=MonotonicTime(nanoseconds=now_nanoseconds)
    )


def make_snapshot(
    target_id: str = "t",
    phase: TimerPhase = TimerPhase.RUNNING,
    split_index: int = 0,
    split_count: int = 1,
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
    scenario_id: str = "scenario",
    target_id: str = "t",
    rule_id: str = "r",
    operation: TimerOperation = TimerOperation.SPLIT,
    priority: int = 0,
    initial_states=None,
    evaluator=None,
) -> Rule:
    if evaluator is None:
        evaluator = lambda context, evaluation: False
    return Rule(
        scenario_id=scenario_id,
        target_id=target_id,
        rule_id=rule_id,
        operation=operation,
        priority=priority,
        initial_states=initial_states if initial_states is not None else {},
        evaluator=evaluator,
    )


class RuleStateTest(unittest.TestCase):
    def test_state_initialized_from_initializer(self):
        calls = []

        def initializer() -> object:
            calls.append(1)
            return 5

        observed = []

        def step(state):
            observed.append(state)
            return (False, state)

        rule = make_rule(
            initial_states={"node": initializer},
            evaluator=lambda context, evaluation: evaluation.transition("node", step),
        )
        self.assertEqual(calls, [1])
        rule.commit(rule.stage(make_context(), make_snapshot()))
        self.assertEqual(observed, [5])

    def test_stateless_rule_has_no_state(self):
        rule = make_rule()
        self.assertEqual(len(rule._state), 0)
        for _ in range(3):
            rule.commit(rule.stage(make_context(), make_snapshot()))
        self.assertEqual(len(rule._state), 0)

    def test_constructor_rejects_empty_identifiers(self):
        with self.assertRaises(ValueError):
            make_rule(scenario_id="")
        with self.assertRaises(ValueError):
            make_rule(target_id="")
        with self.assertRaises(ValueError):
            make_rule(rule_id="")

    def test_stage_without_commit_does_not_advance_state(self):
        rule = make_rule(
            initial_states={"node": lambda: 0},
            evaluator=lambda context, evaluation: evaluation.transition(
                "node", lambda state: (False, state + 1)
            ),
        )
        rule.stage(make_context(), make_snapshot())
        stage = rule.stage(make_context(), make_snapshot())
        rule.commit(stage)
        self.assertEqual(rule._state, {"node": 1})

    def test_evaluator_exception_does_not_commit(self):
        def evaluator(context, evaluation):
            raise RuntimeError("boom")

        rule = make_rule(initial_states={"node": lambda: 0}, evaluator=evaluator)
        with self.assertRaises(RuntimeError):
            rule.stage(make_context(), make_snapshot())
        self.assertEqual(rule._state, {"node": 0})


class RuleTransitionTest(unittest.TestCase):
    def test_same_node_transitions_once_per_frame(self):
        calls = []

        def step(state):
            calls.append(1)
            return (False, state + 1)

        def evaluator(context, evaluation):
            evaluation.transition("node", step)
            evaluation.transition("node", step)
            return False

        rule = make_rule(initial_states={"node": lambda: 0}, evaluator=evaluator)
        stage = rule.stage(make_context(), make_snapshot())
        rule.commit(stage)
        self.assertEqual(len(calls), 1)
        self.assertEqual(rule._state, {"node": 1})

    def test_same_node_returns_cached_bool(self):
        results = []
        calls = []

        def step(state):
            calls.append(1)
            return (True, state)

        def evaluator(context, evaluation):
            results.append(evaluation.transition("node", step))
            results.append(evaluation.transition("node", step))
            return False

        rule = make_rule(initial_states={"node": lambda: 0}, evaluator=evaluator)
        rule.commit(rule.stage(make_context(), make_snapshot()))
        self.assertEqual(len(calls), 1)
        self.assertEqual(results, [True, True])

    def test_distinct_nodes_transition_independently(self):
        calls = {"a": 0, "b": 0}

        def step_a(state):
            calls["a"] += 1
            return (False, state + 1)

        def step_b(state):
            calls["b"] += 1
            return (False, state + 1)

        def evaluator(context, evaluation):
            evaluation.transition("a", step_a)
            evaluation.transition("b", step_b)
            evaluation.transition("a", step_a)
            return False

        rule = make_rule(
            initial_states={"a": lambda: 0, "b": lambda: 10},
            evaluator=evaluator,
        )
        rule.commit(rule.stage(make_context(), make_snapshot()))
        self.assertEqual(calls, {"a": 1, "b": 1})
        self.assertEqual(rule._state, {"a": 1, "b": 11})

    def test_explicitly_shared_node_keeps_single_state(self):
        seen = []

        def step(state):
            seen.append(state)
            return (False, "advanced")

        def evaluator(context, evaluation):
            first = evaluation.transition("shared", step)
            second = evaluation.transition("shared", step)
            return first and second

        rule = make_rule(
            initial_states={"shared": lambda: "initial"}, evaluator=evaluator
        )
        rule.commit(rule.stage(make_context(), make_snapshot()))
        self.assertEqual(seen, ["initial"])
        self.assertEqual(rule._state, {"shared": "advanced"})

    def test_unknown_node_fails_fast(self):
        def evaluator(context, evaluation):
            evaluation.transition("unknown", lambda state: (False, state))
            return False

        rule = make_rule(initial_states={"known": lambda: 0}, evaluator=evaluator)
        with self.assertRaises(ValueError):
            rule.stage(make_context(), make_snapshot())

    def test_non_bool_fired_from_step_rejected(self):
        def evaluator(context, evaluation):
            evaluation.transition("node", lambda state: (1, state))
            return False

        rule = make_rule(initial_states={"node": lambda: 0}, evaluator=evaluator)
        with self.assertRaises(TypeError):
            rule.stage(make_context(), make_snapshot())
        self.assertEqual(rule._state, {"node": 0})

    def test_numpy_bool_fired_from_step_rejected(self):
        def evaluator(context, evaluation):
            evaluation.transition("node", lambda state: (np.True_, state))
            return False

        rule = make_rule(initial_states={"node": lambda: 0}, evaluator=evaluator)
        with self.assertRaises(TypeError):
            rule.stage(make_context(), make_snapshot())
        self.assertEqual(rule._state, {"node": 0})

    def test_state_progresses_across_committed_frames(self):
        rule = make_rule(
            initial_states={"node": lambda: 0},
            evaluator=lambda context, evaluation: evaluation.transition(
                "node", lambda state: (False, state + 1)
            ),
        )
        rule.commit(rule.stage(make_context(), make_snapshot()))
        rule.commit(rule.stage(make_context(), make_snapshot()))
        self.assertEqual(rule._state, {"node": 2})


class RuleStageTest(unittest.TestCase):
    def test_fired_rule_produces_candidate_with_snapshot(self):
        snapshot = make_snapshot()
        rule = make_rule(evaluator=lambda context, evaluation: True)
        stage = rule.stage(make_context(), snapshot)
        candidate = stage.candidate
        assert candidate is not None
        self.assertEqual(candidate.scenario_id, "scenario")
        self.assertEqual(candidate.target_id, "t")
        self.assertEqual(candidate.operation, TimerOperation.SPLIT)
        self.assertEqual(candidate.rule_id, "r")
        self.assertEqual(candidate.priority, 0)
        self.assertEqual(candidate.expected_snapshot, snapshot)

    def test_unfired_rule_produces_no_candidate(self):
        rule = make_rule(evaluator=lambda context, evaluation: False)
        stage = rule.stage(make_context(), make_snapshot())
        self.assertIsNone(stage.candidate)

    def test_stage_rejects_snapshot_target_mismatch(self):
        rule = make_rule(target_id="t")
        with self.assertRaises(ValueError):
            rule.stage(make_context(), make_snapshot(target_id="other"))

    def test_non_bool_evaluator_return_rejected(self):
        rule = make_rule(
            initial_states={"node": lambda: 0},
            evaluator=lambda context, evaluation: 1,
        )
        with self.assertRaises(TypeError):
            rule.stage(make_context(), make_snapshot())
        self.assertEqual(rule._state, {"node": 0})

    def test_numpy_bool_evaluator_return_rejected(self):
        rule = make_rule(
            initial_states={"node": lambda: 0},
            evaluator=lambda context, evaluation: np.True_,
        )
        with self.assertRaises(TypeError):
            rule.stage(make_context(), make_snapshot())
        self.assertEqual(rule._state, {"node": 0})

    def test_stage_next_state_is_read_only(self):
        rule = make_rule(
            initial_states={"node": lambda: 0},
            evaluator=lambda context, evaluation: evaluation.transition(
                "node", lambda state: (False, state + 1)
            ),
        )
        stage = rule.stage(make_context(), make_snapshot())
        with self.assertRaises(TypeError):
            stage._next_state["node"] = 999  # ty: ignore
        rule.commit(stage)
        self.assertEqual(rule._state, {"node": 1})


class RuleCommitTest(unittest.TestCase):
    def test_foreign_stage_rejected(self):
        rule_a = make_rule()
        rule_b = make_rule(rule_id="r2")
        stage = rule_a.stage(make_context(), make_snapshot())
        with self.assertRaises(ValueError):
            rule_b.commit(stage)

    def test_stale_stage_rejected(self):
        rule = make_rule()
        first = rule.stage(make_context(), make_snapshot())
        rule.stage(make_context(), make_snapshot())
        with self.assertRaises(ValueError):
            rule.commit(first)


class ActionCandidateTest(unittest.TestCase):
    def test_target_must_match_expected_snapshot(self):
        snapshot = make_snapshot(target_id="t")
        with self.assertRaises(ValueError):
            ActionCandidate(
                scenario_id="scenario",
                target_id="other",
                operation=TimerOperation.SPLIT,
                rule_id="r",
                priority=0,
                expected_snapshot=snapshot,
            )


class LogicIntegrationTest(unittest.TestCase):
    def test_shared_logic_definition_has_independent_node_states(self):
        edge = RisingEdge()
        values = {"a": True, "b": True}
        fired = []

        def evaluator(context, evaluation):
            fired_a = evaluation.transition(
                "a", lambda state: edge.step(values["a"], state)
            )
            fired_b = evaluation.transition(
                "b", lambda state: edge.step(values["b"], state)
            )
            fired.append((fired_a, fired_b))
            return fired_a or fired_b

        rule = make_rule(
            initial_states={
                "a": lambda: edge.initial_state(),
                "b": lambda: edge.initial_state(),
            },
            evaluator=evaluator,
        )
        rule.commit(rule.stage(make_context(), make_snapshot()))
        values = {"a": True, "b": False}
        rule.commit(rule.stage(make_context(), make_snapshot()))
        values = {"a": True, "b": True}
        rule.commit(rule.stage(make_context(), make_snapshot()))
        self.assertEqual(fired, [(False, False), (False, False), (False, True)])


if __name__ == "__main__":
    unittest.main()
