import unittest

import numpy as np

from divergencesplitter.detector import MeanBrightnessDetector, evaluate
from divergencesplitter.logic import Hold, RisingEdge
from divergencesplitter.models import Frame, FrameContext, MonotonicTime
from divergencesplitter.rule import Rule
from divergencesplitter.score_threshold import ScoreThreshold

EMPTY = np.zeros((1,), dtype=np.uint8)


def make_context(image=EMPTY, now_nanoseconds=0):
    return FrameContext(
        frame=Frame(image=image), now=MonotonicTime(nanoseconds=now_nanoseconds)
    )


def make_rule(initial_states=None, evaluator=None):
    if evaluator is None:
        evaluator = lambda context, evaluation: False
    return Rule(
        initial_states=initial_states if initial_states is not None else {},
        evaluator=evaluator,
    )


class RuleStateTest(unittest.TestCase):
    def test_state_initialized_from_initializer(self):
        calls = []

        def initializer():
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
        rule.commit(rule.stage(make_context()))
        self.assertEqual(observed, [5])

    def test_stateless_rule_has_no_state(self):
        rule = make_rule()
        self.assertEqual(len(rule._state), 0)
        for _ in range(3):
            rule.commit(rule.stage(make_context()))
        self.assertEqual(len(rule._state), 0)

    def test_constructor_rejects_empty_node_id(self):
        with self.assertRaises(ValueError):
            make_rule(initial_states={"": lambda: 0})

    def test_stage_without_commit_does_not_advance_state(self):
        rule = make_rule(
            initial_states={"node": lambda: 0},
            evaluator=lambda context, evaluation: evaluation.transition(
                "node", lambda state: (False, state + 1)
            ),
        )
        rule.stage(make_context())
        stage = rule.stage(make_context())
        rule.commit(stage)
        self.assertEqual(rule._state, {"node": 1})

    def test_evaluator_exception_does_not_commit(self):
        def evaluator(context, evaluation):
            raise RuntimeError("boom")

        rule = make_rule(initial_states={"node": lambda: 0}, evaluator=evaluator)
        with self.assertRaises(RuntimeError):
            rule.stage(make_context())
        self.assertEqual(rule._state, {"node": 0})

    def test_rule_recreation_reinitializes_state(self):
        def build():
            return make_rule(
                initial_states={"node": lambda: 0},
                evaluator=lambda context, evaluation: evaluation.transition(
                    "node", lambda state: (False, state + 1)
                ),
            )

        first = build()
        first.commit(first.stage(make_context()))
        self.assertEqual(first._state, {"node": 1})
        second = build()
        second.commit(second.stage(make_context()))
        self.assertEqual(second._state, {"node": 1})


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
        stage = rule.stage(make_context())
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
        rule.commit(rule.stage(make_context()))
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
        rule.commit(rule.stage(make_context()))
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
        rule.commit(rule.stage(make_context()))
        self.assertEqual(seen, ["initial"])
        self.assertEqual(rule._state, {"shared": "advanced"})

    def test_unknown_node_fails_fast(self):
        def evaluator(context, evaluation):
            evaluation.transition("unknown", lambda state: (False, state))
            return False

        rule = make_rule(initial_states={"known": lambda: 0}, evaluator=evaluator)
        with self.assertRaises(ValueError):
            rule.stage(make_context())

    def test_non_bool_fired_from_step_rejected(self):
        def evaluator(context, evaluation):
            evaluation.transition("node", lambda state: (1, state))
            return False

        rule = make_rule(initial_states={"node": lambda: 0}, evaluator=evaluator)
        with self.assertRaises(TypeError):
            rule.stage(make_context())
        self.assertEqual(rule._state, {"node": 0})

    def test_numpy_bool_fired_from_step_rejected(self):
        def evaluator(context, evaluation):
            evaluation.transition("node", lambda state: (np.True_, state))
            return False

        rule = make_rule(initial_states={"node": lambda: 0}, evaluator=evaluator)
        with self.assertRaises(TypeError):
            rule.stage(make_context())
        self.assertEqual(rule._state, {"node": 0})

    def test_state_progresses_across_committed_frames(self):
        rule = make_rule(
            initial_states={"node": lambda: 0},
            evaluator=lambda context, evaluation: evaluation.transition(
                "node", lambda state: (False, state + 1)
            ),
        )
        rule.commit(rule.stage(make_context()))
        rule.commit(rule.stage(make_context()))
        self.assertEqual(rule._state, {"node": 2})


class RuleStageTest(unittest.TestCase):
    def test_result_reflects_evaluator_return(self):
        fired = make_rule(evaluator=lambda context, evaluation: True)
        self.assertTrue(fired.stage(make_context()).result)
        unfired = make_rule(evaluator=lambda context, evaluation: False)
        self.assertFalse(unfired.stage(make_context()).result)

    def test_non_bool_evaluator_return_rejected(self):
        rule = make_rule(
            initial_states={"node": lambda: 0},
            evaluator=lambda context, evaluation: 1,
        )
        with self.assertRaises(TypeError):
            rule.stage(make_context())
        self.assertEqual(rule._state, {"node": 0})

    def test_numpy_bool_evaluator_return_rejected(self):
        rule = make_rule(
            initial_states={"node": lambda: 0},
            evaluator=lambda context, evaluation: np.True_,
        )
        with self.assertRaises(TypeError):
            rule.stage(make_context())
        self.assertEqual(rule._state, {"node": 0})

    def test_stage_next_state_is_read_only(self):
        rule = make_rule(
            initial_states={"node": lambda: 0},
            evaluator=lambda context, evaluation: evaluation.transition(
                "node", lambda state: (False, state + 1)
            ),
        )
        stage = rule.stage(make_context())
        with self.assertRaises(TypeError):
            stage._next_state["node"] = 999
        rule.commit(stage)
        self.assertEqual(rule._state, {"node": 1})


class RuleCommitTest(unittest.TestCase):
    def test_foreign_stage_rejected(self):
        rule_a = make_rule()
        rule_b = make_rule()
        stage = rule_a.stage(make_context())
        with self.assertRaises(ValueError):
            rule_b.commit(stage)

    def test_stale_stage_rejected(self):
        rule = make_rule()
        first = rule.stage(make_context())
        rule.stage(make_context())
        with self.assertRaises(ValueError):
            rule.commit(first)


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
            initial_states={"a": edge.initial_state, "b": edge.initial_state},
            evaluator=evaluator,
        )
        rule.commit(rule.stage(make_context()))
        values = {"a": True, "b": False}
        rule.commit(rule.stage(make_context()))
        values = {"a": True, "b": True}
        rule.commit(rule.stage(make_context()))
        self.assertEqual(fired, [(False, False), (False, False), (False, True)])

    def test_hold_uses_context_time(self):
        hold = Hold(duration_nanoseconds=10)

        def evaluator(context, evaluation):
            return evaluation.transition(
                "hold", lambda state: hold.step(True, context.now, state)
            )

        rule = make_rule(
            initial_states={"hold": hold.initial_state}, evaluator=evaluator
        )
        stage = rule.stage(make_context(now_nanoseconds=0))
        self.assertFalse(stage.result)
        rule.commit(stage)
        stage = rule.stage(make_context(now_nanoseconds=9))
        self.assertFalse(stage.result)
        rule.commit(stage)
        stage = rule.stage(make_context(now_nanoseconds=10))
        self.assertTrue(stage.result)
        rule.commit(stage)


class DetectorThresholdLogicTest(unittest.TestCase):
    def test_detector_threshold_logic_pipeline(self):
        detector = MeanBrightnessDetector()
        threshold = ScoreThreshold(minimum_score=128.0)
        edge = RisingEdge()

        def evaluator(context, evaluation):
            result = evaluate(context, detector)
            bright = threshold.apply(result)
            return evaluation.transition("edge", lambda state: edge.step(bright, state))

        rule = make_rule(
            initial_states={"edge": edge.initial_state}, evaluator=evaluator
        )

        dark = make_context(image=np.zeros((1, 1), dtype=np.uint8))
        bright = make_context(image=np.full((1, 1), 255, dtype=np.uint8))

        stage = rule.stage(dark)
        self.assertFalse(stage.result)
        rule.commit(stage)

        stage = rule.stage(bright)
        self.assertTrue(stage.result)
        rule.commit(stage)

        stage = rule.stage(bright)
        self.assertFalse(stage.result)
        rule.commit(stage)


if __name__ == "__main__":
    unittest.main()
