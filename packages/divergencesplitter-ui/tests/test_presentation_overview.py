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
    MonotonicTime,
    Nth,
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
from divergencesplitter_runtime.metrics import (
    InstanceEvaluationMetrics,
    RuntimeMetricsSnapshot,
)
from divergencesplitter_runtime.observability import (
    ConditionObservation,
    InstanceRunSnapshot,
    build_detector_tree,
)
from divergencesplitter_ui.presentation import ObservationIndex
from divergencesplitter_ui.presentation_overview import (
    EvaluationKind,
    build_scenario_card,
    scenario_overview_view,
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
    active: bool = True,
) -> ConditionObservation:
    return ConditionObservation(
        condition=condition,
        status=ConditionStatus.TRUE,
        latest_score=None,
        max_score=None,
        active=active,
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
    metrics: RuntimeMetricsSnapshot | None = None,
):
    tree = build_detector_tree((instance,))
    return scenario_overview_view(tree, observations, run_infos, statuses, metrics)


def run_info(*segments: tuple[int, str]) -> LiveSplitRunInfo:
    return LiveSplitRunInfo(
        session_id=1,
        run_revision=1,
        segments=tuple(LiveSplitSegmentInfo(index, name) for index, name in segments),
    )


class TestScenarioStatus:
    def test_ready_is_connected_without_error_detail(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree = build_detector_tree((make_instance(start=condition),))

        card = build_scenario_card(
            tree.scenarios[0],
            ObservationIndex.build(()),
            run_info=None,
            status=InstanceStatus(0, InstanceRuntimeState.READY, "connection reset"),
            metrics=None,
        )

        assert card.status.label == "Connected"
        assert card.status.state is InstanceRuntimeState.READY

    def test_missing_status_is_unknown(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree = build_detector_tree((make_instance(start=condition),))

        card = build_scenario_card(
            tree.scenarios[0],
            ObservationIndex.build(()),
            run_info=None,
            status=None,
            metrics=None,
        )

        assert card.status.state is None
        assert card.status.label == "—"


class TestActiveGroups:
    def test_start_shown_only_when_active(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(start=condition)

        active = build_view(instance, (detected_observation(condition),))
        inactive = build_view(
            instance, (detected_observation(condition, active=False),)
        )

        assert [group.kind for group in active.scenarios[0].evaluation_groups] == [
            EvaluationKind.START
        ]
        assert inactive.scenarios[0].evaluation_groups == ()

    def test_reset_and_incomplete_shown_when_active(self) -> None:
        start = Detected(MeanBrightnessDetector(), 0.9)
        reset = Detected(MeanBrightnessDetector(), 0.5)
        incomplete = Detected(MeanBrightnessDetector(), 0.7)
        instance = make_instance(start=start, reset=reset, incomplete=incomplete)
        observations = (
            detected_observation(reset),
            detected_observation(incomplete),
        )

        card = build_view(instance, observations).scenarios[0]

        kinds = {group.kind for group in card.evaluation_groups}
        assert kinds == {EvaluationKind.RESET, EvaluationKind.INCOMPLETE}

    def test_only_active_splits_are_listed(self) -> None:
        first = Detected(MeanBrightnessDetector(), 0.9)
        second = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=(
                (Rule(first, Action("split")),),
                (Rule(second, Action("split")),),
            ),
        )
        observations = (detected_observation(second),)

        card = build_view(instance, observations).scenarios[0]

        assert [group.label for group in card.evaluation_groups] == ["Split 1"]

    def test_reset_and_split_are_both_shown(self) -> None:
        split_condition = Detected(MeanBrightnessDetector(), 0.9)
        reset = Detected(MeanBrightnessDetector(), 0.5)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            reset=reset,
            splits=((Rule(split_condition, Action("split")),),),
        )
        observations = (
            detected_observation(split_condition),
            detected_observation(reset),
        )

        card = build_view(instance, observations).scenarios[0]

        kinds = [group.kind for group in card.evaluation_groups]
        assert EvaluationKind.SPLIT in kinds
        assert EvaluationKind.RESET in kinds

    def test_no_active_condition_yields_empty_evaluating(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(condition, Action("split")),),),
        )

        card = build_view(instance, ()).scenarios[0]

        assert card.evaluation_groups == ()


class TestSplitLabel:
    def test_segment_name_is_included(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(condition, Action("split")),),),
        )
        infos = (InstanceRunSnapshot(0, run_info((0, "W3 Lemmy"))),)

        card = build_view(
            instance, (detected_observation(condition),), run_infos=infos
        ).scenarios[0]

        assert card.evaluation_groups[0].label == "Split 0 — W3 Lemmy"

    def test_missing_segment_name_falls_back(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(condition, Action("split")),),),
        )

        card = build_view(instance, (detected_observation(condition),)).scenarios[0]

        assert card.evaluation_groups[0].label == "Split 0"


class TestRules:
    def test_rule_index_matches_declaration(self) -> None:
        first = Detected(MeanBrightnessDetector(), 0.9)
        second = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(first, Action("split")), Rule(second, Action("split"))),),
        )

        card = build_view(instance, (detected_observation(second),)).scenarios[0]

        rules = card.evaluation_groups[0].rules
        assert [rule.label for rule in rules] == ["Rule 1"]

    def test_rule_sequence_reports_active_step(self) -> None:
        first = Detected(MeanBrightnessDetector(), 0.9)
        second = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=(
                (
                    RuleSequence(
                        Rule(first, Action("split")),
                        Rule(second, Action("split")),
                    ),
                ),
            ),
        )

        card = build_view(instance, (detected_observation(second),)).scenarios[0]

        rules = card.evaluation_groups[0].rules
        assert [rule.label for rule in rules] == ["Rule 0 / Step 1"]


class TestConditionFormatting:
    def _condition(self, observations, start):
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(start, Action("split")),),),
        )
        return build_view(instance, observations).scenarios[0].evaluation_groups[0]

    def test_detected_score_format(self) -> None:
        detected = Detected(MeanBrightnessDetector(), 0.9)
        group = self._condition((detected_observation(detected),), detected)

        assert group.rules[0].conditions[0].detail == ("0.8432 / 0.9000   Max: 0.9127")

    def test_detected_missing_score_uses_dash(self) -> None:
        detected = Detected(MeanBrightnessDetector(), 0.9)
        observation = detected_observation(detected, latest=None, max_score=None)
        group = self._condition((observation,), detected)

        assert group.rules[0].conditions[0].detail == "— / 0.9000   Max: —"

    def test_detected_error_is_explicit(self) -> None:
        detected = Detected(MeanBrightnessDetector(), 0.9)
        observation = detected_observation(
            detected,
            latest=0.4,
            max_score=0.4,
            status=ConditionStatus.ERROR,
        )
        group = self._condition((observation,), detected)

        detail = group.rules[0].conditions[0].detail
        assert detail.startswith("ERROR")
        assert "0.4000 / 0.9000" in detail

    def test_hold_progress(self) -> None:
        detected = Detected(MeanBrightnessDetector(), 0.9)
        hold = Hold(detected, duration_nanoseconds=1_000_000_000)
        observation = progress_observation(
            hold, current=742_000_000, target=1_000_000_000, unit="nanoseconds"
        )
        group = self._condition((observation, detected_observation(detected)), hold)

        condition = group.rules[0].conditions[0]
        assert condition.label == "Hold"
        assert "0.742 s / 1.000 s" in condition.detail
        assert [child.label for child in condition.children] == ["Detected"]

    def test_nth_progress(self) -> None:
        detected = Detected(MeanBrightnessDetector(), 0.9)
        nth = Nth(detected, 3)
        observation = progress_observation(nth, current=2, target=3, unit="count")
        group = self._condition((observation, detected_observation(detected)), nth)

        condition = group.rules[0].conditions[0]
        assert condition.label == "Nth"
        assert "2 / 3" in condition.detail
        assert [child.label for child in condition.children] == ["Detected"]

    def test_then_progress_is_one_based(self) -> None:
        first = Detected(MeanBrightnessDetector(), 0.9)
        second = Detected(MeanBrightnessDetector(), 0.9)
        third = Detected(MeanBrightnessDetector(), 0.9)
        then = Then(first, second, third)
        observation = progress_observation(then, current=0, target=3, unit="step")
        group = self._condition((observation, detected_observation(first)), then)

        condition = group.rules[0].conditions[0]
        assert condition.label == "Then"
        assert condition.detail == "step 1 / 3"
        assert [child.label for child in condition.children] == ["Detected"]

    def test_then_progress_at_last_step_is_not_beyond_target(self) -> None:
        first = Detected(MeanBrightnessDetector(), 0.9)
        second = Detected(MeanBrightnessDetector(), 0.9)
        third = Detected(MeanBrightnessDetector(), 0.9)
        then = Then(first, second, third)
        observation = progress_observation(then, current=2, target=3, unit="step")
        group = self._condition((observation, detected_observation(first)), then)

        condition = group.rules[0].conditions[0]
        assert condition.detail == "step 3 / 3"

    def test_elapsed_progress(self) -> None:
        elapsed = Elapsed(2_000_000_000)
        observation = progress_observation(
            elapsed, current=750_000_000, target=2_000_000_000, unit="nanoseconds"
        )
        group = self._condition((observation,), elapsed)

        condition = group.rules[0].conditions[0]
        assert condition.label == "Elapsed"
        assert condition.detail == "0.750 s / 2.000 s"


class TestActivePathShape:
    def test_single_chain_is_nested_vertically(self) -> None:
        detected = Detected(MeanBrightnessDetector(), 0.9)
        hold = Hold(detected, duration_nanoseconds=1_000_000_000)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(hold, Action("split")),),),
        )

        card = build_view(
            instance,
            (
                progress_observation(
                    hold,
                    current=100_000_000,
                    target=1_000_000_000,
                    unit="nanoseconds",
                ),
                detected_observation(detected),
            ),
        ).scenarios[0]

        condition = card.evaluation_groups[0].rules[0].conditions[0]
        assert condition.label == "Hold"
        assert condition.children[0].label == "Detected"
        assert condition.children[0].children == ()

    def test_multiple_active_branches_are_preserved(self) -> None:
        first = Detected(MeanBrightnessDetector(), 0.9)
        second = Detected(MeanBrightnessDetector(), 0.9)
        combined = All(first, second)
        instance = make_instance(
            start=Detected(MeanBrightnessDetector(), 0.9),
            splits=((Rule(combined, Action("split")),),),
        )

        card = build_view(
            instance,
            (
                detected_observation(first, latest=0.1, max_score=0.2),
                detected_observation(second, latest=0.3, max_score=0.4),
            ),
        ).scenarios[0]

        condition = card.evaluation_groups[0].rules[0].conditions[0]
        assert condition.label == "All"
        assert [child.label for child in condition.children] == ["Detected", "Detected"]
        assert condition.children[0].detail == "0.1000 / 0.9000   Max: 0.2000"
        assert condition.children[1].detail == "0.3000 / 0.9000   Max: 0.4000"


class TestEvaluationPerformance:
    def test_metrics_are_formatted(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(start=condition)
        metrics = RuntimeMetricsSnapshot(
            sampled_at=MonotonicTime(0),
            window_seconds=1.0,
            input_fps=60.0,
            processing_fps=60.0,
            input_frames_total=0,
            processed_frames_total=0,
            instance_evaluations=(InstanceEvaluationMetrics(0, 3_100_000, 16_900_000),),
        )

        card = build_view(instance, metrics=metrics).scenarios[0]

        assert card.evaluation.average_label == "3.1 ms"
        assert card.evaluation.max_label == "16.9 ms"

    def test_unmeasured_metrics_use_dash(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(start=condition)
        metrics = RuntimeMetricsSnapshot(
            sampled_at=MonotonicTime(0),
            window_seconds=1.0,
            input_fps=0.0,
            processing_fps=0.0,
            input_frames_total=0,
            processed_frames_total=0,
            instance_evaluations=(InstanceEvaluationMetrics(0, None, None),),
        )

        card = build_view(instance, metrics=metrics).scenarios[0]

        assert card.evaluation.average_label == "—"
        assert card.evaluation.max_label == "—"

    def test_missing_metrics_use_dash(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(start=condition)

        card = build_view(instance).scenarios[0]

        assert card.evaluation.average_label == "—"
        assert card.evaluation.max_label == "—"


class TestMultipleScenarios:
    def test_scenario_data_does_not_mix(self) -> None:
        first = Detected(MeanBrightnessDetector(), 0.9)
        second = Detected(MeanBrightnessDetector(), 0.5)
        first_instance = make_instance(
            start=first,
            splits=((Rule(first, Action("split")),),),
        )
        second_instance = make_instance(
            start=second,
            splits=((Rule(second, Action("split")),),),
        )
        tree = build_detector_tree((first_instance, second_instance))
        observations = (
            detected_observation(first, latest=0.1111),
            detected_observation(second, latest=0.9999),
        )
        statuses = (
            InstanceStatus(0, InstanceRuntimeState.READY),
            InstanceStatus(1, InstanceRuntimeState.FAILED),
        )

        view = scenario_overview_view(tree, observations, (), statuses, None)

        assert [card.scenario_index for card in view.scenarios] == [0, 1]
        assert view.scenarios[0].status.label == "Connected"
        assert view.scenarios[1].status.label == "Failed"
        first_detail = (
            view.scenarios[0].evaluation_groups[0].rules[0].conditions[0].detail
        )
        second_detail = (
            view.scenarios[1].evaluation_groups[0].rules[0].conditions[0].detail
        )
        assert "0.1111" in first_detail
        assert "0.9999" in second_detail

    def test_no_tree_yields_empty_overview(self) -> None:
        view = scenario_overview_view(None, (), (), (), None)

        assert view.scenarios == ()


class TestReusedCondition:
    def test_reused_condition_resolves_to_one_observation(self) -> None:
        # A condition instance reused in two tree positions shares one
        # observation, so an active evaluation is reported in both positions.
        # This documents the identity-join limitation rather than hiding it.
        shared = Detected(MeanBrightnessDetector(), 0.9)
        instance = make_instance(start=shared, reset=shared)

        card = build_view(instance, (detected_observation(shared),)).scenarios[0]

        start_group, reset_group = card.evaluation_groups
        start_condition = start_group.rules[0].conditions[0]
        reset_condition = reset_group.rules[0].conditions[0]
        assert start_condition.detail == reset_condition.detail
        assert start_condition.detail == "0.8432 / 0.9000   Max: 0.9127"
