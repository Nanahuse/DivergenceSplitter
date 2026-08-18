import unittest

import numpy as np

from divergencesplitter.detector import MeanBrightnessDetector, evaluate
from divergencesplitter.logic import All, Any, FallingEdge, Hold, RisingEdge, Then
from divergencesplitter.models import Frame, FrameContext, MonotonicTime
from divergencesplitter.rule import Rule
from divergencesplitter.score_threshold import ScoreThreshold

EMPTY = np.zeros((1,), dtype=np.uint8)


def make_context(image=EMPTY, now_nanoseconds=0):
    return FrameContext(
        frame=Frame(image=image), now=MonotonicTime(nanoseconds=now_nanoseconds)
    )


def make_rule(logic_factories=None, transitioner=None, evaluator=None):
    if transitioner is None:
        transitioner = lambda context, evaluation: None
    if evaluator is None:
        evaluator = lambda context, evaluation: False
    return Rule(
        logic_factories=logic_factories if logic_factories is not None else {},
        transitioner=transitioner,
        evaluator=evaluator,
    )


def make_chain_rule(child_factory, parent_factory, child_step, parent_step):
    """Rule where the child node is transitioned first and its boolean is
    handed to the parent node's step within the same transition phase."""

    def transitioner(context, evaluation):
        child_result = evaluation.transition(
            "child", lambda node: child_step(node, context)
        )
        evaluation.transition(
            "parent", lambda node: parent_step(node, child_result, context)
        )

    def evaluator(context, evaluation):
        return evaluation.result("parent")

    return make_rule(
        logic_factories={"child": child_factory, "parent": parent_factory},
        transitioner=transitioner,
        evaluator=evaluator,
    )


class RuleConstructionTest(unittest.TestCase):
    def test_factory_called_once_at_construction(self):
        calls = []

        def factory():
            calls.append(1)
            return RisingEdge()

        make_rule(logic_factories={"edge": factory})
        self.assertEqual(calls, [1])

    def test_constructor_rejects_empty_node_id(self):
        with self.assertRaises(ValueError):
            make_rule(logic_factories={"": RisingEdge})


class RuleTransitionTest(unittest.TestCase):
    def test_duplicate_transition_fails_fast(self):
        def transitioner(context, evaluation):
            evaluation.transition("edge", lambda edge: edge.step(True))
            evaluation.transition("edge", lambda edge: edge.step(True))

        rule = make_rule(
            logic_factories={"edge": RisingEdge}, transitioner=transitioner
        )
        with self.assertRaises(RuntimeError):
            rule.stage(make_context())

    def test_duplicate_transition_does_not_commit(self):
        values = {"v": False}
        mode = {"duplicate": False}

        def transitioner(context, evaluation):
            evaluation.transition("edge", lambda edge: edge.step(values["v"]))
            if mode["duplicate"]:
                evaluation.transition("edge", lambda edge: edge.step(values["v"]))

        def evaluator(context, evaluation):
            return evaluation.result("edge")

        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        rule.commit(rule.stage(make_context()))
        values["v"] = True
        mode["duplicate"] = True
        with self.assertRaises(RuntimeError):
            rule.stage(make_context())
        mode["duplicate"] = False
        stage = rule.stage(make_context())
        self.assertTrue(stage.result)
        rule.commit(stage)

    def test_reentrant_transition_fails_fast_and_does_not_commit(self):
        values = {"v": False}
        mode = {"reentrant": False}

        def transitioner(context, evaluation):
            def step(edge):
                if mode["reentrant"]:
                    evaluation.transition("edge", lambda e: e.step(True))
                return edge.step(values["v"])

            evaluation.transition("edge", step)

        def evaluator(context, evaluation):
            return evaluation.result("edge")

        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        rule.commit(rule.stage(make_context()))
        values["v"] = True
        mode["reentrant"] = True
        with self.assertRaises(RuntimeError):
            rule.stage(make_context())
        mode["reentrant"] = False
        stage = rule.stage(make_context())
        self.assertTrue(stage.result)
        rule.commit(stage)

    def test_shared_node_result_read_multiple_times(self):
        calls = []
        results = []

        def transitioner(context, evaluation):
            def step(edge):
                calls.append(1)
                return edge.step(True)

            evaluation.transition("edge", step)

        def evaluator(context, evaluation):
            results.append(evaluation.result("edge"))
            results.append(evaluation.result("edge"))
            return evaluation.result("edge")

        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        rule.commit(rule.stage(make_context()))
        self.assertEqual(calls, [1])
        self.assertEqual(results, [False, False])

    def test_unknown_node_transition_fails_fast(self):
        def transitioner(context, evaluation):
            evaluation.transition("unknown", lambda edge: edge.step(True))

        rule = make_rule(
            logic_factories={"known": RisingEdge}, transitioner=transitioner
        )
        with self.assertRaises(ValueError):
            rule.stage(make_context())

    def test_unknown_node_result_fails_fast(self):
        def transitioner(context, evaluation):
            evaluation.transition("known", lambda edge: edge.step(True))

        def evaluator(context, evaluation):
            return evaluation.result("unknown")

        rule = make_rule(
            logic_factories={"known": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        with self.assertRaises(ValueError):
            rule.stage(make_context())

    def test_non_bool_step_result_rejected(self):
        def transitioner(context, evaluation):
            evaluation.transition("edge", lambda edge: 1)

        rule = make_rule(
            logic_factories={"edge": RisingEdge}, transitioner=transitioner
        )
        with self.assertRaises(TypeError):
            rule.stage(make_context())

    def test_numpy_bool_step_result_rejected(self):
        def transitioner(context, evaluation):
            evaluation.transition("edge", lambda edge: np.True_)

        rule = make_rule(
            logic_factories={"edge": RisingEdge}, transitioner=transitioner
        )
        with self.assertRaises(TypeError):
            rule.stage(make_context())


class RuleTransitionContractTest(unittest.TestCase):
    def test_missing_transition_fails_fast(self):
        def transitioner(context, evaluation):
            evaluation.transition("a", lambda edge: edge.step(True))

        def evaluator(context, evaluation):
            return True

        rule = make_rule(
            logic_factories={"a": RisingEdge, "b": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        with self.assertRaises(RuntimeError):
            rule.stage(make_context())

    def test_missing_transition_does_not_commit(self):
        values = {"a": False}
        mode = {"omit_b": False}

        def transitioner(context, evaluation):
            evaluation.transition("a", lambda edge: edge.step(values["a"]))
            if not mode["omit_b"]:
                evaluation.transition("b", lambda edge: edge.step(False))

        def evaluator(context, evaluation):
            return evaluation.result("a")

        rule = make_rule(
            logic_factories={"a": RisingEdge, "b": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        rule.commit(rule.stage(make_context()))
        values["a"] = True
        mode["omit_b"] = True
        with self.assertRaises(RuntimeError):
            rule.stage(make_context())
        mode["omit_b"] = False
        stage = rule.stage(make_context())
        self.assertTrue(stage.result)
        rule.commit(stage)

    def test_transition_in_result_phase_fails(self):
        def transitioner(context, evaluation):
            evaluation.transition("edge", lambda edge: edge.step(False))

        def evaluator(context, evaluation):
            evaluation.transition("edge", lambda edge: edge.step(True))
            return True

        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        with self.assertRaises(RuntimeError):
            rule.stage(make_context())

    def test_result_before_transition_complete_fails(self):
        def transitioner(context, evaluation):
            evaluation.result("edge")
            evaluation.transition("edge", lambda edge: edge.step(False))

        def evaluator(context, evaluation):
            return True

        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        with self.assertRaises(RuntimeError):
            rule.stage(make_context())


class RuleStateLifecycleTest(unittest.TestCase):
    def test_state_advances_across_committed_frames(self):
        values = {"v": False}

        def transitioner(context, evaluation):
            evaluation.transition("edge", lambda edge: edge.step(values["v"]))

        def evaluator(context, evaluation):
            return evaluation.result("edge")

        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)
        values["v"] = True
        stage = rule.stage(make_context())
        self.assertTrue(stage.result)
        rule.commit(stage)
        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)

    def test_stage_without_commit_does_not_advance_state(self):
        values = {"v": False}

        def transitioner(context, evaluation):
            evaluation.transition("edge", lambda edge: edge.step(values["v"]))

        def evaluator(context, evaluation):
            return evaluation.result("edge")

        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        rule.stage(make_context())
        values["v"] = True
        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)

    def test_rule_recreation_reinitializes_state(self):
        values = {"v": False}

        def build():
            def transitioner(context, evaluation):
                evaluation.transition("edge", lambda edge: edge.step(values["v"]))

            def evaluator(context, evaluation):
                return evaluation.result("edge")

            return make_rule(
                logic_factories={"edge": RisingEdge},
                transitioner=transitioner,
                evaluator=evaluator,
            )

        first = build()
        stage = first.stage(make_context())
        first.commit(stage)
        values["v"] = True
        stage = first.stage(make_context())
        self.assertTrue(stage.result)
        first.commit(stage)

        second = build()
        stage = second.stage(make_context())
        self.assertFalse(stage.result)
        second.commit(stage)

    def test_evaluator_exception_does_not_commit(self):
        values = {"v": False}
        mode = {"bad": False}

        def transitioner(context, evaluation):
            evaluation.transition("edge", lambda edge: edge.step(values["v"]))

        def evaluator(context, evaluation):
            if mode["bad"]:
                raise RuntimeError("boom")
            return evaluation.result("edge")

        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        rule.commit(rule.stage(make_context()))
        values["v"] = True
        mode["bad"] = True
        with self.assertRaises(RuntimeError):
            rule.stage(make_context())
        mode["bad"] = False
        stage = rule.stage(make_context())
        self.assertTrue(stage.result)
        rule.commit(stage)

    def test_non_bool_step_result_does_not_commit(self):
        values = {"v": False}
        mode = {"bad": False}

        def transitioner(context, evaluation):
            if mode["bad"]:

                def step(edge):
                    edge.step(True)
                    return 1

                evaluation.transition("edge", step)
            else:
                evaluation.transition("edge", lambda edge: edge.step(values["v"]))

        def evaluator(context, evaluation):
            return evaluation.result("edge")

        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        rule.commit(rule.stage(make_context()))
        values["v"] = True
        mode["bad"] = True
        with self.assertRaises(TypeError):
            rule.stage(make_context())
        mode["bad"] = False
        stage = rule.stage(make_context())
        self.assertTrue(stage.result)
        rule.commit(stage)


class RuleNodeIndependenceTest(unittest.TestCase):
    def test_same_config_nodes_do_not_share_state(self):
        values = {"a": True, "b": True}
        fired = []

        def transitioner(context, evaluation):
            fired_a = evaluation.transition("a", lambda edge: edge.step(values["a"]))
            fired_b = evaluation.transition("b", lambda edge: edge.step(values["b"]))
            fired.append((fired_a, fired_b))

        def evaluator(context, evaluation):
            return evaluation.result("a") or evaluation.result("b")

        rule = make_rule(
            logic_factories={"a": RisingEdge, "b": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        rule.commit(rule.stage(make_context()))
        values["b"] = False
        rule.commit(rule.stage(make_context()))
        values["b"] = True
        rule.commit(rule.stage(make_context()))
        self.assertEqual(fired, [(False, False), (False, False), (False, True)])

    def test_explicitly_shared_node_transitions_once_per_frame(self):
        seen = []

        def transitioner(context, evaluation):
            def step(edge):
                seen.append(edge)
                return edge.step(True)

            evaluation.transition("shared", step)

        def evaluator(context, evaluation):
            return evaluation.result("shared") or evaluation.result("shared")

        rule = make_rule(
            logic_factories={"shared": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        rule.commit(rule.stage(make_context()))
        self.assertEqual(len(seen), 1)


class RuleStageTest(unittest.TestCase):
    def test_result_reflects_evaluator_return(self):
        fired = make_rule(evaluator=lambda context, evaluation: True)
        self.assertTrue(fired.stage(make_context()).result)
        unfired = make_rule(evaluator=lambda context, evaluation: False)
        self.assertFalse(unfired.stage(make_context()).result)

    def test_non_bool_evaluator_return_rejected(self):
        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=lambda context, evaluation: evaluation.transition(
                "edge", lambda edge: edge.step(False)
            ),
            evaluator=lambda context, evaluation: 1,
        )
        with self.assertRaises(TypeError):
            rule.stage(make_context())

    def test_numpy_bool_evaluator_return_rejected(self):
        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=lambda context, evaluation: evaluation.transition(
                "edge", lambda edge: edge.step(False)
            ),
            evaluator=lambda context, evaluation: np.True_,
        )
        with self.assertRaises(TypeError):
            rule.stage(make_context())

    def test_stage_exposes_only_opaque_result(self):
        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=lambda context, evaluation: evaluation.transition(
                "edge", lambda edge: edge.step(False)
            ),
            evaluator=lambda context, evaluation: evaluation.result("edge"),
        )
        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        public = {name for name in dir(stage) if not name.startswith("_")}
        self.assertEqual(public, {"result"})


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

    def test_double_commit_rejected(self):
        rule = make_rule()
        stage = rule.stage(make_context())
        rule.commit(stage)
        with self.assertRaises(ValueError):
            rule.commit(stage)

    def test_multiple_rules_staged_then_committed(self):
        rule_a = make_rule()
        rule_b = make_rule()
        stage_a = rule_a.stage(make_context())
        stage_b = rule_b.stage(make_context())
        rule_a.commit(stage_a)
        rule_b.commit(stage_b)


class LogicIntegrationTest(unittest.TestCase):
    def test_hold_uses_context_time(self):
        def transitioner(context, evaluation):
            evaluation.transition("hold", lambda hold: hold.step(True, context.now))

        def evaluator(context, evaluation):
            return evaluation.result("hold")

        rule = make_rule(
            logic_factories={"hold": lambda: Hold(duration_nanoseconds=10)},
            transitioner=transitioner,
            evaluator=evaluator,
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


class RuleResultPhaseShortCircuitTest(unittest.TestCase):
    def test_all_hold_with_false_gate_still_advances_hold(self):
        gate = {"value": False}

        def transitioner(context, evaluation):
            evaluation.transition("hold", lambda hold: hold.step(True, context.now))

        def evaluator(context, evaluation):
            return All().apply([evaluation.result("hold"), gate["value"]])

        rule = make_rule(
            logic_factories={"hold": lambda: Hold(duration_nanoseconds=10)},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        stage = rule.stage(make_context(now_nanoseconds=0))
        self.assertFalse(stage.result)
        rule.commit(stage)
        stage = rule.stage(make_context(now_nanoseconds=5))
        self.assertFalse(stage.result)
        rule.commit(stage)
        gate["value"] = True
        stage = rule.stage(make_context(now_nanoseconds=10))
        self.assertTrue(stage.result)
        rule.commit(stage)

    def test_false_input_during_false_gate_resets_hold(self):
        values = {"b": True}
        gate = {"value": True}

        def transitioner(context, evaluation):
            evaluation.transition(
                "hold", lambda hold: hold.step(values["b"], context.now)
            )

        def evaluator(context, evaluation):
            return All().apply([evaluation.result("hold"), gate["value"]])

        rule = make_rule(
            logic_factories={"hold": lambda: Hold(duration_nanoseconds=10)},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        stage = rule.stage(make_context(now_nanoseconds=0))
        self.assertFalse(stage.result)
        rule.commit(stage)
        values["b"] = False
        gate["value"] = False
        stage = rule.stage(make_context(now_nanoseconds=5))
        self.assertFalse(stage.result)
        rule.commit(stage)
        values["b"] = True
        gate["value"] = True
        stage = rule.stage(make_context(now_nanoseconds=10))
        self.assertFalse(stage.result)
        rule.commit(stage)

    def test_any_pure_gate_still_advances_edge(self):
        values = {"x": False}
        gate = {"value": False}

        def transitioner(context, evaluation):
            evaluation.transition("edge", lambda edge: edge.step(values["x"]))

        def evaluator(context, evaluation):
            return Any().apply([gate["value"], evaluation.result("edge")])

        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)
        values["x"] = True
        gate["value"] = True
        stage = rule.stage(make_context())
        self.assertTrue(stage.result)
        rule.commit(stage)
        gate["value"] = False
        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)

    def test_result_phase_pure_suffix_skipped_by_all_short_circuit(self):
        calls = []

        def pure_predicate():
            calls.append(1)
            return True

        def transitioner(context, evaluation):
            evaluation.transition("a", lambda edge: edge.step(False))

        def evaluator(context, evaluation):
            def values():
                yield evaluation.result("a")
                yield pure_predicate()

            return All().apply(values())

        rule = make_rule(
            logic_factories={"a": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        self.assertEqual(calls, [])

    def test_result_phase_pure_suffix_skipped_by_any_short_circuit(self):
        calls = []

        def pure_predicate():
            calls.append(1)
            return False

        def transitioner(context, evaluation):
            evaluation.transition("hold", lambda hold: hold.step(True, context.now))

        def evaluator(context, evaluation):
            def values():
                yield evaluation.result("hold")
                yield pure_predicate()

            return Any().apply(values())

        rule = make_rule(
            logic_factories={"hold": lambda: Hold(duration_nanoseconds=0)},
            transitioner=transitioner,
            evaluator=evaluator,
        )
        stage = rule.stage(make_context())
        self.assertTrue(stage.result)
        self.assertEqual(calls, [])


class DetectorThresholdLogicTest(unittest.TestCase):
    def test_detector_threshold_logic_pipeline(self):
        detector = MeanBrightnessDetector()
        threshold = ScoreThreshold(minimum_score=128.0)

        def transitioner(context, evaluation):
            result = evaluate(context, detector)
            bright = threshold.apply(result)
            evaluation.transition("edge", lambda edge: edge.step(bright))

        def evaluator(context, evaluation):
            return evaluation.result("edge")

        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            transitioner=transitioner,
            evaluator=evaluator,
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


class StatefulCompositionTest(unittest.TestCase):
    def test_rising_edge_of_hold_fires_once_on_hold_turn_on(self):
        level = {"value": False}

        def child_step(hold, context):
            return hold.step(level["value"], context.now)

        def parent_step(edge, child_result, context):
            return edge.step(child_result)

        rule = make_chain_rule(
            child_factory=lambda: Hold(duration_nanoseconds=0),
            parent_factory=RisingEdge,
            child_step=child_step,
            parent_step=parent_step,
        )
        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)

        level["value"] = True
        stage = rule.stage(make_context())
        self.assertTrue(stage.result)
        rule.commit(stage)

        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)

    def test_falling_edge_of_hold_fires_on_hold_release(self):
        level = {"value": True}

        def child_step(hold, context):
            return hold.step(level["value"], context.now)

        def parent_step(edge, child_result, context):
            return edge.step(child_result)

        rule = make_chain_rule(
            child_factory=lambda: Hold(duration_nanoseconds=0),
            parent_factory=FallingEdge,
            child_step=child_step,
            parent_step=parent_step,
        )
        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)

        level["value"] = False
        stage = rule.stage(make_context())
        self.assertTrue(stage.result)
        rule.commit(stage)

        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)

    def test_hold_of_rising_edge_zero_duration_fires_only_on_pulse_frame(self):
        level = {"value": False}

        def child_step(edge, context):
            return edge.step(level["value"])

        def parent_step(hold, child_result, context):
            return hold.step(child_result, context.now)

        rule = make_chain_rule(
            child_factory=RisingEdge,
            parent_factory=lambda: Hold(duration_nanoseconds=0),
            child_step=child_step,
            parent_step=parent_step,
        )
        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)

        level["value"] = True
        stage = rule.stage(make_context())
        self.assertTrue(stage.result)
        rule.commit(stage)

        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)

    def test_hold_of_rising_edge_positive_duration_not_satisfied_by_pulse(self):
        level = {"value": False}

        def child_step(edge, context):
            return edge.step(level["value"])

        def parent_step(hold, child_result, context):
            return hold.step(child_result, context.now)

        rule = make_chain_rule(
            child_factory=RisingEdge,
            parent_factory=lambda: Hold(duration_nanoseconds=10),
            child_step=child_step,
            parent_step=parent_step,
        )
        rule.commit(rule.stage(make_context(now_nanoseconds=0)))
        level["value"] = True
        stage = rule.stage(make_context(now_nanoseconds=10))
        self.assertFalse(stage.result)
        rule.commit(stage)

        stage = rule.stage(make_context(now_nanoseconds=20))
        self.assertFalse(stage.result)
        rule.commit(stage)

    def test_rising_edge_of_then_fires_once_on_completion(self):
        cond = {"value": False}

        def child_step(then, context):
            return then.step([cond["value"]], context.now)

        def parent_step(edge, child_result, context):
            return edge.step(child_result)

        rule = make_chain_rule(
            child_factory=lambda: Then(step_count=1, within_nanoseconds=0),
            parent_factory=RisingEdge,
            child_step=child_step,
            parent_step=parent_step,
        )
        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)

        cond["value"] = True
        stage = rule.stage(make_context())
        self.assertTrue(stage.result)
        rule.commit(stage)

        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)

    def test_hold_of_then_satisfied_after_completion_duration(self):
        cond = {"value": False}

        def child_step(then, context):
            return then.step([cond["value"]], context.now)

        def parent_step(hold, child_result, context):
            return hold.step(child_result, context.now)

        rule = make_chain_rule(
            child_factory=lambda: Then(step_count=1, within_nanoseconds=0),
            parent_factory=lambda: Hold(duration_nanoseconds=10),
            child_step=child_step,
            parent_step=parent_step,
        )
        stage = rule.stage(make_context(now_nanoseconds=0))
        self.assertFalse(stage.result)
        rule.commit(stage)

        cond["value"] = True
        stage = rule.stage(make_context(now_nanoseconds=5))
        self.assertFalse(stage.result)
        rule.commit(stage)

        stage = rule.stage(make_context(now_nanoseconds=15))
        self.assertTrue(stage.result)
        rule.commit(stage)

    def test_child_transition_fed_to_parent_step_in_order(self):
        order = []

        def child_step(edge, context):
            order.append("child")
            return edge.step(True)

        def parent_step(edge, child_result, context):
            order.append("parent")
            return edge.step(child_result)

        rule = make_chain_rule(
            child_factory=RisingEdge,
            parent_factory=FallingEdge,
            child_step=child_step,
            parent_step=parent_step,
        )
        rule.commit(rule.stage(make_context()))
        self.assertEqual(order, ["child", "parent"])


class ThenOrderingTest(unittest.TestCase):
    def test_early_edge_pulse_is_lost(self):
        gate_value = {"value": False}
        pulse_value = {"value": False}

        def transitioner(context, evaluation):
            gate = evaluation.transition(
                "gate", lambda node: node.step(gate_value["value"])
            )
            pulse = evaluation.transition(
                "pulse", lambda node: node.step(pulse_value["value"])
            )
            evaluation.transition(
                "then", lambda node: node.step([gate, pulse], context.now)
            )

        def evaluator(context, evaluation):
            return evaluation.result("then")

        rule = make_rule(
            logic_factories={
                "gate": RisingEdge,
                "pulse": RisingEdge,
                "then": lambda: Then(step_count=2, within_nanoseconds=1000),
            },
            transitioner=transitioner,
            evaluator=evaluator,
        )

        rule.commit(rule.stage(make_context(now_nanoseconds=0)))

        pulse_value["value"] = True
        rule.commit(rule.stage(make_context(now_nanoseconds=1)))

        pulse_value["value"] = False
        gate_value["value"] = True
        stage = rule.stage(make_context(now_nanoseconds=2))
        self.assertFalse(stage.result)
        rule.commit(stage)

        gate_value["value"] = False
        stage = rule.stage(make_context(now_nanoseconds=3))
        self.assertFalse(stage.result)
        rule.commit(stage)

    def test_hold_level_usable_after_stage_reached(self):
        gate_value = {"value": False}
        level_value = {"value": False}

        def transitioner(context, evaluation):
            gate = evaluation.transition(
                "gate", lambda node: node.step(gate_value["value"])
            )
            level = evaluation.transition(
                "level", lambda node: node.step(level_value["value"], context.now)
            )
            evaluation.transition(
                "then", lambda node: node.step([gate, level], context.now)
            )

        def evaluator(context, evaluation):
            return evaluation.result("then")

        rule = make_rule(
            logic_factories={
                "gate": RisingEdge,
                "level": lambda: Hold(duration_nanoseconds=0),
                "then": lambda: Then(step_count=2, within_nanoseconds=1000),
            },
            transitioner=transitioner,
            evaluator=evaluator,
        )

        rule.commit(rule.stage(make_context(now_nanoseconds=0)))

        level_value["value"] = True
        rule.commit(rule.stage(make_context(now_nanoseconds=1)))

        gate_value["value"] = True
        stage = rule.stage(make_context(now_nanoseconds=2))
        self.assertFalse(stage.result)
        rule.commit(stage)

        gate_value["value"] = False
        stage = rule.stage(make_context(now_nanoseconds=3))
        self.assertTrue(stage.result)
        rule.commit(stage)


if __name__ == "__main__":
    unittest.main()
