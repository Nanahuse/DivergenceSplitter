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


def make_rule(logic_factories=None, evaluator=None):
    if evaluator is None:
        evaluator = lambda context, evaluation: False
    return Rule(
        logic_factories=logic_factories if logic_factories is not None else {},
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


class RuleEvaluationTest(unittest.TestCase):
    def test_same_node_evaluates_once_per_frame(self):
        calls = []

        def evaluator(context, evaluation):
            def step(edge):
                calls.append(1)
                return edge.step(True)

            evaluation.evaluate("edge", step)
            evaluation.evaluate("edge", step)
            return False

        rule = make_rule(logic_factories={"edge": RisingEdge}, evaluator=evaluator)
        rule.commit(rule.stage(make_context()))
        self.assertEqual(calls, [1])

    def test_same_node_returns_cached_result(self):
        results = []
        calls = []

        def evaluator(context, evaluation):
            def step(edge):
                calls.append(1)
                return edge.step(True)

            results.append(evaluation.evaluate("edge", step))
            results.append(evaluation.evaluate("edge", step))
            return False

        rule = make_rule(logic_factories={"edge": RisingEdge}, evaluator=evaluator)
        rule.commit(rule.stage(make_context()))
        self.assertEqual(calls, [1])
        self.assertEqual(results, [False, False])

    def test_unknown_node_fails_fast(self):
        def evaluator(context, evaluation):
            return evaluation.evaluate("unknown", lambda edge: edge.step(True))

        rule = make_rule(logic_factories={"known": RisingEdge}, evaluator=evaluator)
        with self.assertRaises(ValueError):
            rule.stage(make_context())

    def test_non_bool_step_result_rejected(self):
        def evaluator(context, evaluation):
            return evaluation.evaluate("edge", lambda edge: 1)

        rule = make_rule(logic_factories={"edge": RisingEdge}, evaluator=evaluator)
        with self.assertRaises(TypeError):
            rule.stage(make_context())

    def test_numpy_bool_step_result_rejected(self):
        def evaluator(context, evaluation):
            return evaluation.evaluate("edge", lambda edge: np.True_)

        rule = make_rule(logic_factories={"edge": RisingEdge}, evaluator=evaluator)
        with self.assertRaises(TypeError):
            rule.stage(make_context())


class RuleStateLifecycleTest(unittest.TestCase):
    def test_state_advances_across_committed_frames(self):
        values = {"v": False}

        def evaluator(context, evaluation):
            return evaluation.evaluate("edge", lambda edge: edge.step(values["v"]))

        rule = make_rule(logic_factories={"edge": RisingEdge}, evaluator=evaluator)
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

        def evaluator(context, evaluation):
            return evaluation.evaluate("edge", lambda edge: edge.step(values["v"]))

        rule = make_rule(logic_factories={"edge": RisingEdge}, evaluator=evaluator)
        rule.stage(make_context())
        values["v"] = True
        stage = rule.stage(make_context())
        self.assertFalse(stage.result)
        rule.commit(stage)

    def test_rule_recreation_reinitializes_state(self):
        values = {"v": False}

        def build():
            return make_rule(
                logic_factories={"edge": RisingEdge},
                evaluator=lambda context, evaluation: evaluation.evaluate(
                    "edge", lambda edge: edge.step(values["v"])
                ),
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

        def evaluator(context, evaluation):
            if mode["bad"]:
                raise RuntimeError("boom")
            return evaluation.evaluate("edge", lambda edge: edge.step(values["v"]))

        rule = make_rule(logic_factories={"edge": RisingEdge}, evaluator=evaluator)
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

        def evaluator(context, evaluation):
            if mode["bad"]:

                def step(edge):
                    edge.step(True)
                    return 1

                return evaluation.evaluate("edge", step)
            return evaluation.evaluate("edge", lambda edge: edge.step(values["v"]))

        rule = make_rule(logic_factories={"edge": RisingEdge}, evaluator=evaluator)
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

        def evaluator(context, evaluation):
            fired_a = evaluation.evaluate("a", lambda edge: edge.step(values["a"]))
            fired_b = evaluation.evaluate("b", lambda edge: edge.step(values["b"]))
            fired.append((fired_a, fired_b))
            return fired_a or fired_b

        rule = make_rule(
            logic_factories={"a": RisingEdge, "b": RisingEdge}, evaluator=evaluator
        )
        rule.commit(rule.stage(make_context()))
        values["b"] = False
        rule.commit(rule.stage(make_context()))
        values["b"] = True
        rule.commit(rule.stage(make_context()))
        self.assertEqual(fired, [(False, False), (False, False), (False, True)])

    def test_explicitly_shared_node_evaluates_once_per_frame(self):
        seen = []

        def evaluator(context, evaluation):
            def step(edge):
                seen.append(edge)
                return edge.step(True)

            first = evaluation.evaluate("shared", step)
            second = evaluation.evaluate("shared", step)
            return first or second

        rule = make_rule(logic_factories={"shared": RisingEdge}, evaluator=evaluator)
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
            evaluator=lambda context, evaluation: 1,
        )
        with self.assertRaises(TypeError):
            rule.stage(make_context())

    def test_numpy_bool_evaluator_return_rejected(self):
        rule = make_rule(
            logic_factories={"edge": RisingEdge},
            evaluator=lambda context, evaluation: np.True_,
        )
        with self.assertRaises(TypeError):
            rule.stage(make_context())


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
    def test_hold_uses_context_time(self):
        rule = make_rule(
            logic_factories={"hold": lambda: Hold(duration_nanoseconds=10)},
            evaluator=lambda context, evaluation: evaluation.evaluate(
                "hold", lambda hold: hold.step(True, context.now)
            ),
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

        def evaluator(context, evaluation):
            result = evaluate(context, detector)
            bright = threshold.apply(result)
            return evaluation.evaluate("edge", lambda edge: edge.step(bright))

        rule = make_rule(logic_factories={"edge": RisingEdge}, evaluator=evaluator)

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
