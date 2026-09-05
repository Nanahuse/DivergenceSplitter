import logging
from io import StringIO

import numpy as np
from divergencesplitter import (
    Action,
    All,
    Detected,
    DetectionResult,
    Frame,
    FrameContext,
    LiveSplitConnection,
    MeanAbsoluteSimilarityConfig,
    MeanAbsoluteSimilarityDetector,
    MeanBrightnessDetector,
    MonotonicTime,
    Not,
    Rule,
    Scenario,
)
from divergencesplitter_runtime.capture import PublishResult
from divergencesplitter_runtime.diagnostics import OperationalDiagnostics
from divergencesplitter_runtime.observability import build_detector_tree


def make_frame(captured_at: int = 100) -> Frame:
    return Frame(
        image=np.zeros((2, 2), dtype=np.uint8),
        captured_at=MonotonicTime(captured_at),
    )


def make_scenario(detector) -> Scenario:
    return Scenario(
        connection=LiveSplitConnection("rpc", "event"),
        reset_conditions=(Detected(detector, 100.0),),
        splits=((Rule(Detected(detector, 200.0), Action("split")),),),
    )


class TestDetectorTree:
    def test_tree_preserves_scenario_reset_split_rule_condition_nesting(self) -> None:
        detector = MeanBrightnessDetector()
        reset_detector = MeanBrightnessDetector()
        scenario = Scenario(
            connection=LiveSplitConnection("rpc", "event"),
            reset_conditions=(Detected(reset_detector, 200.0),),
            splits=(
                (
                    Rule(
                        All(
                            Detected(detector, 300.0),
                            Not(Detected(detector, 50.0)),
                        ),
                        Action("split"),
                    ),
                    Rule(Detected(detector, 400.0), Action("split")),
                ),
                None,
            ),
        )

        tree = build_detector_tree((scenario,))

        assert len(tree.scenarios) == 1
        scenario_node = tree.scenarios[0]
        assert scenario_node.scenario_index == 0

        assert len(scenario_node.reset_conditions) == 1
        reset_condition = scenario_node.reset_conditions[0]
        assert reset_condition.condition_type == "Detected"
        assert reset_condition.detector is not None
        assert reset_condition.detector.minimum_score == 200.0
        assert reset_condition.detector.detector_type == "MeanBrightnessDetector"
        assert reset_condition.detector.reference_images == ()

        assert len(scenario_node.splits) == 2
        first_split = scenario_node.splits[0]
        assert first_split.split_index == 0
        assert len(first_split.rules) == 2

        first_rule = first_split.rules[0]
        assert first_rule.rule_index == 0
        assert first_rule.action == "split"
        assert first_rule.condition.condition_type == "All"
        assert len(first_rule.condition.children) == 2
        detected = first_rule.condition.children[0]
        assert detected.condition_type == "Detected"
        assert detected.detector is not None
        assert detected.detector.minimum_score == 300.0
        assert detected.detector.detector is detector

        not_node = first_rule.condition.children[1]
        assert not_node.condition_type == "Not"
        assert not_node.children[0].detector is not None
        assert not_node.children[0].detector.minimum_score == 50.0

        second_rule = first_split.rules[1]
        assert second_rule.rule_index == 1
        assert second_rule.condition.detector is not None
        assert second_rule.condition.detector.minimum_score == 400.0

        assert scenario_node.splits[1].split_index == 1
        assert scenario_node.splits[1].rules == ()

    def test_shared_detector_appears_at_each_occurrence_with_same_identity(
        self,
    ) -> None:
        shared = MeanBrightnessDetector()

        tree = build_detector_tree((make_scenario(shared),))
        scenario_node = tree.scenarios[0]

        reset_node = scenario_node.reset_conditions[0].detector
        split_node = scenario_node.splits[0].rules[0].condition.detector
        assert reset_node is not None
        assert split_node is not None
        assert reset_node.detector is shared
        assert split_node.detector is shared

    def test_reference_images_surface_on_detected_nodes(self) -> None:
        reference = ((0, 255), (255, 0))
        detector = MeanAbsoluteSimilarityDetector(
            MeanAbsoluteSimilarityConfig(reference)
        )

        node = build_detector_tree((make_scenario(detector),)).scenarios[0]
        reset_detector = node.reset_conditions[0].detector
        assert reset_detector is not None
        images = reset_detector.reference_images
        assert len(images) == 1
        assert images[0].label == "reference"
        assert images[0].image == reference


class TestObservableFrameSlot:
    def test_take_returns_latest_and_clears_slot(self) -> None:
        diagnostics = OperationalDiagnostics(StringIO())
        frame = make_frame(100)

        diagnostics.frame_received(frame, PublishResult.PUBLISHED)

        assert diagnostics.take_latest_input_frame() is frame
        assert diagnostics.take_latest_input_frame() is None

    def test_newer_frame_replaces_an_unread_frame(self) -> None:
        diagnostics = OperationalDiagnostics(StringIO())
        first = make_frame(100)
        second = make_frame(200)

        diagnostics.frame_received(first, PublishResult.PUBLISHED)
        diagnostics.frame_received(second, PublishResult.OVERWROTE)

        assert diagnostics.take_latest_input_frame() is second

    def test_frames_are_not_copied(self) -> None:
        diagnostics = OperationalDiagnostics(StringIO())
        frame = make_frame(100)

        diagnostics.frame_received(frame, PublishResult.PUBLISHED)

        assert diagnostics.take_latest_input_frame() is frame


class TestObservableDetectorScore:
    def test_scores_are_reported_per_detector_and_consumed(self) -> None:
        diagnostics = OperationalDiagnostics(StringIO())
        detector = MeanBrightnessDetector()
        context = FrameContext(frame=make_frame(100), now=MonotonicTime(150))
        context.detection_cache[detector] = DetectionResult(score=0.75)

        diagnostics.frame_processing_completed(context)

        scores = diagnostics.take_detector_scores()
        assert len(scores) == 1
        assert scores[0].detector is detector
        assert scores[0].score == 0.75
        assert diagnostics.take_detector_scores() == ()

    def test_re_evaluation_keeps_only_the_newest_score(self) -> None:
        diagnostics = OperationalDiagnostics(StringIO())
        detector = MeanBrightnessDetector()

        first = FrameContext(frame=make_frame(100), now=MonotonicTime(150))
        first.detection_cache[detector] = DetectionResult(score=0.5)
        diagnostics.frame_processing_completed(first)

        second = FrameContext(frame=make_frame(200), now=MonotonicTime(250))
        second.detection_cache[detector] = DetectionResult(score=0.9)
        diagnostics.frame_processing_completed(second)

        scores = diagnostics.take_detector_scores()
        assert len(scores) == 1
        assert scores[0].score == 0.9


class TestObservabilityBoundary:
    def test_runtime_started_is_logged_at_info(self) -> None:
        stream = StringIO()
        diagnostics = OperationalDiagnostics(stream, level=logging.INFO)

        diagnostics.runtime_started()

        assert "runtime.started" in stream.getvalue()

    def test_detector_tree_is_exposed_after_binding(self) -> None:
        diagnostics = OperationalDiagnostics(StringIO())
        scenario = make_scenario(MeanBrightnessDetector())

        assert diagnostics.detector_tree() is None
        diagnostics.bind_runtime((scenario,), make_frame_source())
        tree = diagnostics.detector_tree()
        assert tree is not None
        assert len(tree.scenarios) == 1


def make_frame_source():
    from divergencesplitter import VideoFileSource

    return VideoFileSource("recording.mp4")
