from __future__ import annotations

from divergencesplitter_runtime.instance_runtime import InstanceRuntimeState
from divergencesplitter_ui.monitor.scenario_overview import ScenarioOverviewPanel
from divergencesplitter_ui.presentation_overview import (
    ConditionEvaluationView,
    EvaluationGroupView,
    EvaluationKind,
    EvaluationPerformanceView,
    RuleEvaluationView,
    ScenarioCardView,
    ScenarioOverviewView,
    ScenarioStatusView,
)


def collect_text(control) -> list[str]:
    """Collect every displayed string under ``control`` for behavior tests."""

    found: list[str] = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        found.append(value)
    for child in getattr(control, "controls", None) or ():
        found.extend(collect_text(child))
    content = getattr(control, "content", None)
    if content is not None:
        found.extend(collect_text(content))
    return found


def condition(label: str, detail: str = "") -> ConditionEvaluationView:
    return ConditionEvaluationView(label=label, detail=detail)


def split_group(label: str, *rules: RuleEvaluationView) -> EvaluationGroupView:
    return EvaluationGroupView(
        kind=EvaluationKind.SPLIT, label=label, rules=tuple(rules)
    )


def rule(label: str | None, *conditions: ConditionEvaluationView) -> RuleEvaluationView:
    return RuleEvaluationView(label=label, conditions=tuple(conditions))


def card(
    scenario_index: int,
    *,
    state: InstanceRuntimeState | None = InstanceRuntimeState.READY,
    status: str = "Connected",
    groups: tuple[EvaluationGroupView, ...] = (),
    average: str = "3.1 ms",
    max_latency: str = "16.9 ms",
) -> ScenarioCardView:
    return ScenarioCardView(
        scenario_index=scenario_index,
        status=ScenarioStatusView(state=state, label=status),
        evaluation_groups=groups,
        evaluation=EvaluationPerformanceView(
            average_label=average, max_label=max_latency
        ),
    )


def view(*cards: ScenarioCardView) -> ScenarioOverviewView:
    return ScenarioOverviewView(scenarios=tuple(cards))


class TestScenarioCards:
    def test_multiple_scenarios_are_displayed(self) -> None:
        panel = ScenarioOverviewPanel()

        panel.apply(view(card(0), card(1)))

        texts = collect_text(panel.control)
        assert "Scenario 0" in texts
        assert "Scenario 1" in texts

    def test_scenario_removed_after_count_shrinks(self) -> None:
        panel = ScenarioOverviewPanel()
        panel.apply(view(card(0), card(1)))

        changed = panel.apply(view(card(0)))

        assert changed is True
        texts = collect_text(panel.control)
        assert "Scenario 0" in texts
        assert "Scenario 1" not in texts

    def test_identical_view_is_not_changed(self) -> None:
        panel = ScenarioOverviewPanel()
        panel.apply(view(card(0)))
        assert panel.apply(view(card(0))) is False


class TestStatus:
    def test_status_change_is_reflected(self) -> None:
        panel = ScenarioOverviewPanel()
        panel.apply(view(card(0, status="Connected")))
        assert "● Connected" in collect_text(panel.control)

        panel.apply(
            view(
                card(
                    0,
                    state=InstanceRuntimeState.FAILED,
                    status="Failed",
                )
            )
        )

        texts = collect_text(panel.control)
        assert "● Failed" in texts
        assert "● Connected" not in texts


class TestEvaluating:
    def test_active_path_is_rendered(self) -> None:
        panel = ScenarioOverviewPanel()

        panel.apply(
            view(
                card(
                    0,
                    groups=(
                        split_group(
                            "Split 2 — W3 Lemmy",
                            rule("Rule 0", condition("Detected", "0.8432 / 0.9000")),
                        ),
                    ),
                )
            )
        )

        texts = collect_text(panel.control)
        assert "Evaluating" in texts
        assert "Split 2 — W3 Lemmy" in texts
        assert "Rule 0" in texts
        assert "Detected" in texts
        assert "0.8432 / 0.9000" in texts

    def test_active_path_change_replaces_old_content(self) -> None:
        panel = ScenarioOverviewPanel()
        panel.apply(
            view(
                card(
                    0,
                    groups=(split_group("Split 2", rule("Rule 0", condition("Hold"))),),
                )
            )
        )

        panel.apply(
            view(
                card(
                    0,
                    groups=(
                        split_group("Split 3", rule("Rule 1", condition("Elapsed"))),
                    ),
                )
            )
        )

        texts = collect_text(panel.control)
        assert "Split 3" in texts
        assert "Elapsed" in texts
        assert "Split 2" not in texts
        assert "Hold" not in texts

    def test_empty_evaluating_clears_previous_content(self) -> None:
        panel = ScenarioOverviewPanel()
        panel.apply(
            view(
                card(
                    0,
                    groups=(split_group("Split 2", rule("Rule 0", condition("Hold"))),),
                )
            )
        )

        panel.apply(view(card(0)))

        texts = collect_text(panel.control)
        assert "Split 2" not in texts
        assert "Hold" not in texts
        assert "—" in texts

    def test_score_only_change_keeps_structure(self) -> None:
        panel = ScenarioOverviewPanel()
        group = split_group("Split 2", rule("Rule 0", condition("Detected", "0.1")))
        panel.apply(view(card(0, groups=(group,))))
        assert panel.apply(view(card(0, groups=(group,)))) is False

        changed_group = split_group(
            "Split 2", rule("Rule 0", condition("Detected", "0.2"))
        )

        assert panel.apply(view(card(0, groups=(changed_group,)))) is True
        assert "0.2" in collect_text(panel.control)
