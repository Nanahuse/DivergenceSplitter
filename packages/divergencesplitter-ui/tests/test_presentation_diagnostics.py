from __future__ import annotations

from divergencesplitter import (
    Action,
    All,
    ConditionStatus,
    Detected,
    Elapsed,
    Hold,
    LiveSplitConnection,
    MeanBrightnessDetector,
    Nth,
    RootMeanSquareSimilarityConfig,
    RootMeanSquareSimilarityDetector,
    Rule,
    RuleSequence,
    Scenario,
    Then,
)
from divergencesplitter_runtime.instance_runtime import (
    InstanceRuntimeState,
    InstanceStatus,
)
from divergencesplitter_runtime.instances import ScenarioInstance
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitRunInfo,
    LiveSplitSegmentInfo,
)
from divergencesplitter_runtime.observability import (
    ConditionObservation,
    InstanceRunSnapshot,
    build_detector_tree,
)
from divergencesplitter_ui.presentation_diagnostics import (
    INCOMPLETE_KIND,
    RESET_KIND,
    START_KIND,
    diagnostics_view,
)


def make_instance(*, start, reset=None, incomplete=None, splits=()) -> ScenarioInstance:
    return ScenarioInstance(
        connection=LiveSplitConnection("rpc", "event"),
        scenario=Scenario(start, reset, incomplete, splits),
    )


def detected_observation(
    condition: Detected,
    *,
    latest: float | None = 0.8432,
    max_score: float | None = 0.9127,
    status: ConditionStatus = ConditionStatus.TRUE,
    active: bool = True,
) -> ConditionObservation:
    return ConditionObservation(
        condition=condition,
        status=status,
        latest_score=latest,
        max_score=max_score,
        active=active,
        progress_current=latest,
        progress_target=condition.minimum_score,
        progress_unit="score",
    )


def progress_observation(
    condition,
    *,
    current: float | None,
    target: float | None,
    unit: str,
    elapsed: int | None = None,
    active: bool = True,
) -> ConditionObservation:
    return ConditionObservation(
        condition=condition,
        status=ConditionStatus.TRUE,
        latest_score=None,
        max_score=None,
        active=active,
        elapsed_nanoseconds=elapsed,
        progress_current=current,
        progress_target=target,
        progress_unit=unit,
    )


def build_view(
    instance: ScenarioInstance,
    observations: tuple[ConditionObservation, ...] = (),
    *,
    run_infos: tuple[InstanceRunSnapshot, ...] = (),
    statuses: tuple[InstanceStatus, ...] = (),
):
    tree = build_detector_tree((instance,))
    return tree, diagnostics_view(tree, observations, run_infos, statuses)


def run_info(*segments: tuple[int, str]) -> LiveSplitRunInfo:
    return LiveSplitRunInfo(
        session_id=1,
        run_revision=1,
        segments=tuple(LiveSplitSegmentInfo(index, name) for index, name in segments),
    )


class TestConnection:
    def test_endpoints_and_status_are_reported(self) -> None:
        instance = ScenarioInstance(
            connection=LiveSplitConnection("tcp://rpc:1", "tcp://event:2"),
            scenario=Scenario(Detected(MeanBrightnessDetector(), 0.9), None, None, ()),
        )
        tree = build_detector_tree((instance,))
        statuses = (InstanceStatus(0, InstanceRuntimeState.READY),)

        view = diagnostics_view(tree, (), (), statuses)

        connection = view.scenarios[0].connection
        assert connection.status_label == "Connected"
        assert connection.rpc_endpoint == "tcp://rpc:1"
        assert connection.event_endpoint == "tcp://event:2"
        assert connection.error_label == "—"
        assert connection.has_error is False

    def test_connection_error_is_reported(self) -> None:
        instance = make_instance(start=Detected(MeanBrightnessDetector(), 0.9))
        tree = build_detector_tree((instance,))
        statuses = (
            InstanceStatus(0, InstanceRuntimeState.FAILED, "connection refused"),
        )

        view = diagnostics_view(tree, (), (), statuses)

        connection = view.scenarios[0].connection
        assert connection.status_label == "Failed"
        assert connection.error_label == "connection refused"
        assert connection.has_error is True

    def test_missing_status_is_unknown(self) -> None:
        instance = make_instance(start=Detected(MeanBrightnessDetector(), 0.9))

        _, view = build_view(instance)

        assert view.scenarios[0].connection.status_label == "—"
        assert view.scenarios[0].connection.has_error is False


class TestGroups:
    def test_start_is_always_present(self) -> None:
        instance = make_instance(start=Detected(MeanBrightnessDetector(), 0.9))

        _, view = build_view(instance)

        kinds = [group.kind for group in view.scenarios[0].groups]
        assert kinds == [START_KIND]

    def test_reset_only_when_defined(self) -> None:
        without = make_instance(start=Detected(MeanBrightnessDetector(), 0.9))
        with_reset = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            reset=Detected(MeanBrightnessDetector(), 0.5),
        )

        _, without_view = build_view(without)
        _, with_view = build_view(with_reset)

        assert RESET_KIND not in [g.kind for g in without_view.scenarios[0].groups]
        assert RESET_KIND in [g.kind for g in with_view.scenarios[0].groups]

    def test_incomplete_only_when_defined(self) -> None:
        with_incomplete = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            incomplete=Detected(MeanBrightnessDetector(), 0.5),
        )

        _, view = build_view(with_incomplete)

        assert INCOMPLETE_KIND in [g.kind for g in view.scenarios[0].groups]

    def test_split_labels_use_segment_names(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(condition, Action("split")),),),
        )
        infos = (InstanceRunSnapshot(0, run_info((0, "W3 Lemmy"))),)

        _, view = build_view(instance, run_infos=infos)

        split = view.scenarios[0].groups[-1]
        assert split.label == "Split 0 — W3 Lemmy"


class TestRules:
    def test_plain_rule_keeps_action_and_condition(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(condition, Action("split")),),),
        )

        _, view = build_view(instance)

        rule = view.scenarios[0].groups[-1].rules[0]
        assert rule.label == "Rule 0 (split)"
        assert len(rule.conditions) == 1
        assert rule.steps == ()

    def test_rule_sequence_keeps_every_step(self) -> None:
        first = Detected(MeanBrightnessDetector(), 0.9)
        second = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=(
                (
                    RuleSequence(
                        Rule(first, Action("split")),
                        Rule(second, Action("skip")),
                    ),
                ),
            ),
        )

        _, view = build_view(instance)

        rule = view.scenarios[0].groups[-1].rules[0]
        assert rule.label == "Rule 0 (sequence)"
        assert [step.label for step in rule.steps] == [
            "Step 0 (split)",
            "Step 1 (skip)",
        ]


class TestConditions:
    def test_status_and_active_are_reported(self) -> None:
        active = Detected(MeanBrightnessDetector(), 0.9)
        inactive = Detected(MeanBrightnessDetector(), 0.9)
        group = All(active, inactive)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(group, Action("split")),),),
        )

        _, view = build_view(
            instance,
            (
                detected_observation(active, status=ConditionStatus.FALSE),
                detected_observation(inactive, active=False),
            ),
        )

        condition = view.scenarios[0].groups[-1].rules[0].conditions[0]
        active_child, inactive_child = condition.children
        assert "[FALSE]" in active_child.label
        assert "ACTIVE" in active_child.label
        assert active_child.active is True
        assert "[TRUE]" in inactive_child.label
        assert "ACTIVE" not in inactive_child.label
        assert inactive_child.active is False

    def test_unobserved_condition_is_kept(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(condition, Action("split")),),),
        )

        _, view = build_view(instance)

        condition_view = view.scenarios[0].groups[-1].rules[0].conditions[0]
        assert "UNOBSERVED" in condition_view.label
        assert condition_view.active is False


class TestDetector:
    def test_scores_and_type_are_reported(self) -> None:
        detector = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(detector, Action("split")),),),
        )

        _, view = build_view(instance, (detected_observation(detector),))

        info = view.scenarios[0].groups[-1].rules[0].conditions[0].detector
        assert info is not None
        assert info.detector_type == "MeanBrightnessDetector"
        assert info.threshold_label == "0.9000"
        assert info.current_label == "0.8432"
        assert info.max_label == "0.9127"

    def test_missing_scores_use_dash(self) -> None:
        detector = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(detector, Action("split")),),),
        )

        _, view = build_view(instance)

        info = view.scenarios[0].groups[-1].rules[0].conditions[0].detector
        assert info is not None
        assert info.current_label == "—"
        assert info.max_label == "—"

    def test_reference_images_are_exposed(self) -> None:
        detector = Detected(
            RootMeanSquareSimilarityDetector(
                RootMeanSquareSimilarityConfig(((0.0, 1.0), (1.0, 0.0)))
            ),
            0.9,
        )
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(detector, Action("split")),),),
        )

        _, view = build_view(instance)

        info = view.scenarios[0].groups[-1].rules[0].conditions[0].detector
        assert info is not None
        assert len(info.references) == 1
        assert info.references[0].image == ((0.0, 1.0), (1.0, 0.0))


class TestProgress:
    def _condition(self, condition, observation):
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(condition, Action("split")),),),
        )
        _, view = build_view(instance, (observation,))
        return view.scenarios[0].groups[-1].rules[0].conditions[0]

    def test_hold_progress(self) -> None:
        detected = Detected(MeanBrightnessDetector(), 0.9)
        hold = Hold(detected, duration_nanoseconds=1_000_000_000)
        observation = progress_observation(
            hold, current=742_000_000, target=1_000_000_000, unit="nanoseconds"
        )

        condition = self._condition(hold, observation)

        assert condition.label == "▶ Hold [TRUE]  0.742 s / 1.000 s  ACTIVE"

    def test_elapsed_progress(self) -> None:
        elapsed = Elapsed(2_000_000_000)
        observation = progress_observation(
            elapsed,
            current=750_000_000,
            target=2_000_000_000,
            unit="nanoseconds",
            elapsed=750_000_000,
        )

        condition = self._condition(elapsed, observation)

        assert condition.label == "▶ Elapsed [TRUE]  0.750 s / 2.000 s  ACTIVE"

    def test_nth_progress(self) -> None:
        detected = Detected(MeanBrightnessDetector(), 0.9)
        nth = Nth(detected, 3)
        observation = progress_observation(nth, current=2, target=3, unit="count")

        condition = self._condition(nth, observation)

        assert condition.label == "▶ Nth [TRUE]  2 / 3  ACTIVE"

    def test_then_progress(self) -> None:
        first = Detected(MeanBrightnessDetector(), 0.9)
        second = Detected(MeanBrightnessDetector(), 0.9)
        then = Then(first, second)
        observation = progress_observation(then, current=1, target=2, unit="step")

        condition = self._condition(then, observation)

        assert condition.label == "▶ Then [TRUE]  step 2 / 2  ACTIVE"


class TestMultipleScenarios:
    def test_scenario_data_does_not_mix(self) -> None:
        first = Detected(MeanBrightnessDetector(), 0.9)
        second = Detected(MeanBrightnessDetector(), 0.5)
        instances = (
            ScenarioInstance(
                LiveSplitConnection("tcp://rpc:0", "tcp://event:0"),
                Scenario(first, None, None, ((Rule(first, Action("split")),),)),
            ),
            ScenarioInstance(
                LiveSplitConnection("tcp://rpc:1", "tcp://event:1"),
                Scenario(second, None, None, ((Rule(second, Action("split")),),)),
            ),
        )
        tree = build_detector_tree(instances)
        statuses = (
            InstanceStatus(0, InstanceRuntimeState.READY),
            InstanceStatus(1, InstanceRuntimeState.FAILED, "boom"),
        )

        view = diagnostics_view(
            tree,
            (
                detected_observation(first, latest=0.1111),
                detected_observation(second, latest=0.9999),
            ),
            (),
            statuses,
        )

        assert view.scenarios[0].connection.rpc_endpoint == "tcp://rpc:0"
        assert view.scenarios[0].connection.error_label == "—"
        assert view.scenarios[1].connection.rpc_endpoint == "tcp://rpc:1"
        assert view.scenarios[1].connection.error_label == "boom"
        first_detector = view.scenarios[0].groups[-1].rules[0].conditions[0].detector
        second_detector = view.scenarios[1].groups[-1].rules[0].conditions[0].detector
        assert first_detector is not None
        assert second_detector is not None
        assert first_detector.current_label == "0.1111"
        assert second_detector.current_label == "0.9999"


class TestTreeKey:
    def test_tree_key_is_the_source_tree(self) -> None:
        instance = make_instance(start=Detected(MeanBrightnessDetector(), 0.9))

        tree, view = build_view(instance)

        assert view.tree_key is tree

    def test_no_tree_yields_empty_view_without_key(self) -> None:
        view = diagnostics_view(None, (), (), ())

        assert view.tree_key is None
        assert view.scenarios == ()
