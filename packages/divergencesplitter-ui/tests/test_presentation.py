from __future__ import annotations

from divergencesplitter import (
    ConditionStatus,
    Detected,
    LiveSplitConnection,
    MeanBrightnessDetector,
    Scenario,
)
from divergencesplitter_runtime.observability import (
    ConditionObservation,
    build_detector_tree,
)
from divergencesplitter_ui.presentation import (
    UNOBSERVED_LABEL,
    ExpansionEvent,
    ExpansionState,
    ObservationIndex,
    ScreenPresenter,
    condition_label,
    detector_label,
    format_score,
    has_new_observations,
    scenario_label,
    status_label,
    view_for,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0

    def now_ns(self) -> int:
        return self.now


def make_scenario(*reset_conditions, splits=()) -> Scenario:
    return Scenario(
        connection=LiveSplitConnection("rpc", "event"),
        reset_conditions=reset_conditions,
        splits=splits,
    )


class TestStatusAndScoreFormatting:
    def test_unobserved_label(self) -> None:
        assert status_label(None) == UNOBSERVED_LABEL

    def test_true_false_skipped_labels(self) -> None:
        assert status_label(ConditionStatus.TRUE) == "TRUE"
        assert status_label(ConditionStatus.FALSE) == "FALSE"
        assert status_label(ConditionStatus.SKIPPED) == "SKIPPED"

    def test_format_score_none_is_empty(self) -> None:
        assert format_score(None) == ""

    def test_format_score_number(self) -> None:
        assert format_score(0.0) == "0"
        assert format_score(78.51234) == "78.51"

    def test_scenario_label_contains_connection_destination(self) -> None:
        scenario = make_scenario()
        node = build_detector_tree((scenario,)).scenarios[0]

        assert scenario_label(node) == "Scenario 0  rpc=rpc  event=event"


class TestObservationIdentity:
    def test_shared_detector_distinct_detected_not_confused(self) -> None:
        shared = MeanBrightnessDetector()
        first = Detected(shared, 100.0)
        second = Detected(shared, 200.0)
        tree = build_detector_tree((make_scenario(first, second),))
        observations = (
            ConditionObservation(first, ConditionStatus.TRUE, 50.0, 90.0),
            ConditionObservation(second, ConditionStatus.FALSE, 10.0, 30.0),
        )
        index = ObservationIndex.build(observations)

        first_view = view_for(tree.scenarios[0].reset_conditions[0], index)
        second_view = view_for(tree.scenarios[0].reset_conditions[1], index)

        assert first_view.minimum_score == 100.0
        assert first_view.latest_score == 50.0
        assert first_view.max_score == 90.0
        assert second_view.minimum_score == 200.0
        assert second_view.latest_score == 10.0
        assert second_view.max_score == 30.0

    def test_reused_condition_maps_to_same_observation(self) -> None:
        shared_condition = Detected(MeanBrightnessDetector(), 100.0)
        tree = build_detector_tree((make_scenario(shared_condition, shared_condition),))
        observations = (
            ConditionObservation(shared_condition, ConditionStatus.TRUE, 50.0, 90.0),
        )
        index = ObservationIndex.build(observations)

        first_view = view_for(tree.scenarios[0].reset_conditions[0], index)
        second_view = view_for(tree.scenarios[0].reset_conditions[1], index)

        assert first_view.latest_score == 50.0
        assert second_view.latest_score == 50.0
        assert first_view.max_score == 90.0
        assert second_view.max_score == 90.0

    def test_missing_observation_is_unobserved(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 100.0)
        tree = build_detector_tree((make_scenario(condition),))
        index = ObservationIndex.build(())

        view = view_for(tree.scenarios[0].reset_conditions[0], index)

        assert view.status_label == UNOBSERVED_LABEL
        assert view.latest_score is None
        assert view.max_score is None


class TestSkippedDetection:
    def test_skipped_child_has_skipped_status_and_no_current_score(self) -> None:
        skipped = Detected(MeanBrightnessDetector(), -1.0)
        tree = build_detector_tree((make_scenario(skipped),))
        observations = (
            ConditionObservation(skipped, ConditionStatus.SKIPPED, None, 0.0),
        )
        index = ObservationIndex.build(observations)

        view = view_for(tree.scenarios[0].reset_conditions[0], index)

        assert view.status_label == "SKIPPED"
        assert view.latest_score is None
        assert view.max_score == 0.0
        assert condition_label(view) == "Detected [SKIPPED]"
        assert detector_label(view) == (
            "MeanBrightnessDetector [SKIPPED]  threshold=-1  current=—  max=0"
        )


class TestObservationId:
    def test_non_empty_observation_is_new_snapshot(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 100.0)
        assert has_new_observations(
            (ConditionObservation(condition, None, None, None),)
        )

    def test_empty_observation_is_no_snapshot(self) -> None:
        assert not has_new_observations(())


class TestScreenPresenterCadence:
    def test_image_due_every_100ms(self) -> None:
        clock = FakeClock()
        presenter = ScreenPresenter(clock=clock)

        assert presenter.image_due() is True
        clock.now = 50_000_000
        assert presenter.image_due() is False
        clock.now = 100_000_000
        assert presenter.image_due() is True
        clock.now = 200_000_000
        assert presenter.image_due() is True

    def test_fps_due_every_second(self) -> None:
        clock = FakeClock()
        presenter = ScreenPresenter(clock=clock)

        assert presenter.fps_due() is True
        clock.now = 500_000_000
        assert presenter.fps_due() is False
        clock.now = 1_000_000_000
        assert presenter.fps_due() is True

    def test_state_changed_only_on_change(self) -> None:
        presenter = ScreenPresenter()

        assert presenter.state_changed("RUNNING") is True
        assert presenter.state_changed("RUNNING") is False
        assert presenter.state_changed("STOPPED") is True


class TestExpansionState:
    def test_lazy_show_and_hide(self) -> None:
        state = ExpansionState()

        assert state.reconcile(1, expanded=True, has_reference_images=True) is (
            ExpansionEvent.SHOW
        )
        assert state.is_expanded(1)
        assert state.reconcile(1, expanded=True, has_reference_images=True) is (
            ExpansionEvent.NONE
        )
        assert state.reconcile(1, expanded=False, has_reference_images=True) is (
            ExpansionEvent.HIDE
        )
        assert not state.is_expanded(1)
        assert state.reconcile(1, expanded=False, has_reference_images=True) is (
            ExpansionEvent.NONE
        )

    def test_no_reference_images_never_materialize(self) -> None:
        state = ExpansionState()

        assert state.reconcile(2, expanded=True, has_reference_images=False) is (
            ExpansionEvent.NONE
        )
