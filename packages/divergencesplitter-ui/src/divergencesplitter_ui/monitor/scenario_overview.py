"""Scenario Overview panel for the Flet Monitor.

The panel renders the pure ``ScenarioOverviewView``: it never reads the runtime
tree or observations itself. One card is kept per scenario index and reused
across updates; the Evaluating section reconciles its control tree so a
score-only change updates the existing detail text instead of rebuilding the
card. The card list is the only scrollable region of the Monitor.
"""

from __future__ import annotations

import flet as ft
from divergencesplitter_runtime.configuration.models import Theme

from divergencesplitter_ui.presentation_overview import (
    ConditionEvaluationView,
    EvaluationGroupView,
    ScenarioCardView,
    ScenarioOverviewView,
)
from divergencesplitter_ui.theme import (
    SemanticColors,
    instance_status_color,
    semantic_colors,
)

_INDENT_WIDTH = 14
_EMPTY_EVALUATING = "—"


def _condition_signature(view: ConditionEvaluationView) -> tuple:
    return (view.label, tuple(_condition_signature(child) for child in view.children))


def _layout_signature(groups: tuple[EvaluationGroupView, ...]) -> tuple:
    return tuple(
        (
            group.kind,
            group.label,
            tuple(
                (
                    rule.label,
                    tuple(_condition_signature(item) for item in rule.conditions),
                )
                for rule in group.rules
            ),
        )
        for group in groups
    )


def _condition_details(views: tuple[ConditionEvaluationView, ...]) -> list[str]:
    details: list[str] = []
    for view in views:
        details.append(view.detail)
        details.extend(_condition_details(view.children))
    return details


def _all_details(groups: tuple[EvaluationGroupView, ...]) -> list[str]:
    details: list[str] = []
    for group in groups:
        for rule in group.rules:
            details.extend(_condition_details(rule.conditions))
    return details


def _condition_control(
    view: ConditionEvaluationView,
    depth: int,
    detail_texts: list[ft.Text],
) -> ft.Control:
    detail = ft.Text(view.detail)
    detail_texts.append(detail)
    controls: list[ft.Control] = [
        ft.Row(controls=[ft.Text(view.label), detail], spacing=12)
    ]
    controls.extend(
        _condition_control(child, depth + 1, detail_texts) for child in view.children
    )
    return ft.Container(
        content=ft.Column(controls=controls, spacing=2),
        padding=ft.Padding.only(left=depth * _INDENT_WIDTH),
    )


def _build_conditions(
    views: tuple[ConditionEvaluationView, ...],
    depth: int,
    detail_texts: list[ft.Text],
) -> list[ft.Control]:
    return [_condition_control(view, depth, detail_texts) for view in views]


def _build_group(
    group: EvaluationGroupView,
    detail_texts: list[ft.Text],
) -> ft.Control:
    controls: list[ft.Control] = [ft.Text(group.label, weight=ft.FontWeight.BOLD)]
    for rule in group.rules:
        if rule.label is not None:
            controls.append(
                ft.Container(
                    content=ft.Text(rule.label),
                    padding=ft.Padding.only(left=_INDENT_WIDTH),
                )
            )
        controls.extend(_build_conditions(rule.conditions, 2, detail_texts))
    return ft.Column(controls=controls, spacing=2)


class _EvaluatingSection:
    """Reconcile the active evaluation controls against the view structure."""

    def __init__(self) -> None:
        self._column = ft.Column(controls=[ft.Text(_EMPTY_EVALUATING)], spacing=8)
        self._signature: tuple | None = None
        self._detail_texts: list[ft.Text] = []

    @property
    def control(self) -> ft.Control:
        return self._column

    def apply(self, groups: tuple[EvaluationGroupView, ...]) -> bool:
        signature = _layout_signature(groups)
        if signature != self._signature:
            self._rebuild(groups, signature)
            return True
        changed = False
        for text, value in zip(self._detail_texts, _all_details(groups), strict=True):
            if text.value != value:
                text.value = value
                changed = True
        return changed

    def _rebuild(
        self,
        groups: tuple[EvaluationGroupView, ...],
        signature: tuple,
    ) -> None:
        self._signature = signature
        self._detail_texts = []
        if not groups:
            self._column.controls = [ft.Text(_EMPTY_EVALUATING)]
            return
        self._column.controls = [
            _build_group(group, self._detail_texts) for group in groups
        ]


class _ScenarioCard:
    """One scenario's card, updated in place."""

    def __init__(self) -> None:
        self._scenario_index = -1
        self._title = ft.Text("")
        self._status = ft.Text("")
        self._evaluating = _EvaluatingSection()
        self._average = ft.Text("")
        self._max = ft.Text("")
        self._control = ft.Card(
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                self._title,
                                ft.Container(expand=True),
                                self._status,
                            ]
                        ),
                        ft.Text("Evaluating"),
                        self._evaluating.control,
                        ft.Divider(),
                        ft.Row(
                            controls=[
                                ft.Text("Evaluation", width=90),
                                ft.Text("Avg"),
                                self._average,
                                ft.Text("Max"),
                                self._max,
                            ],
                            spacing=12,
                        ),
                    ],
                    spacing=8,
                ),
                padding=12,
            )
        )

    @property
    def control(self) -> ft.Control:
        return self._control

    @property
    def scenario_index(self) -> int:
        return self._scenario_index

    def apply(self, view: ScenarioCardView, colors: SemanticColors) -> bool:
        self._scenario_index = view.scenario_index
        changed = False
        title = f"Scenario {view.scenario_index}"
        if self._title.value != title:
            self._title.value = title
            changed = True
        status_text = f"● {view.status.label}"
        if self._status.value != status_text:
            self._status.value = status_text
            changed = True
        color = instance_status_color(view.status.state, colors)
        if self._status.color != color:
            self._status.color = color
            changed = True
        if self._evaluating.apply(view.evaluation_groups):
            changed = True
        if self._average.value != view.evaluation.average_label:
            self._average.value = view.evaluation.average_label
            changed = True
        if self._max.value != view.evaluation.max_label:
            self._max.value = view.evaluation.max_label
            changed = True
        return changed


class ScenarioOverviewPanel:
    """Display one card per scenario inside a scrollable list."""

    def __init__(self, theme: Theme = Theme.LIGHT) -> None:
        self._cards: dict[int, _ScenarioCard] = {}
        self._theme = theme
        self._colors = semantic_colors(theme)
        self._list = ft.ListView(controls=[], spacing=10, expand=True)
        self._control = ft.Column(
            controls=[ft.Text("Scenario Overview"), self._list],
            expand=True,
            spacing=8,
        )

    @property
    def control(self) -> ft.Control:
        """The root control to add to the page."""

        return self._control

    def set_theme(self, theme: Theme) -> None:
        """Switch the semantic colors; the next ``apply`` repaints the cards."""

        self._theme = theme
        self._colors = semantic_colors(theme)

    def apply(self, view: ScenarioOverviewView) -> bool:
        changed = False
        wanted = {card.scenario_index for card in view.scenarios}
        for index in list(self._cards):
            if index not in wanted:
                removed = self._cards.pop(index)
                self._list.controls.remove(removed.control)
                changed = True
        for card_view in view.scenarios:
            card = self._cards.get(card_view.scenario_index)
            if card is None:
                card = _ScenarioCard()
                self._cards[card_view.scenario_index] = card
                changed = True
            if card.apply(card_view, self._colors):
                changed = True
        ordered = [self._cards[item.scenario_index].control for item in view.scenarios]
        if [id(control) for control in self._list.controls] != [
            id(control) for control in ordered
        ]:
            self._list.controls = ordered
            changed = True
        return changed
