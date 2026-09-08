"""Pure error presentation for one terminal session failure.

Nothing in this module imports Dear PyGui. It converts the controller's
``SessionResult`` into a transfer-only ``ErrorView`` using the existing
``SessionFailureKind`` boundaries as the display authority, and it decides
when a failure should be shown at all. All of these decisions are covered by
behavior tests.
"""

from __future__ import annotations

from dataclasses import dataclass

from divergencesplitter_ui.session import (
    SessionFailureKind,
    SessionResult,
    SessionState,
)

_CATEGORY_LABELS = {
    SessionFailureKind.CONFIGURATION_FILE: "Configuration file",
    SessionFailureKind.CONFIGURATION_VALIDATION: "Configuration validation",
    SessionFailureKind.SCENARIO_EXECUTION: "Scenario execution",
    SessionFailureKind.SCENARIO_VALIDATION: "Scenario validation",
    SessionFailureKind.SOURCE_CONFIGURATION: "Source configuration",
    SessionFailureKind.STARTUP_VALIDATION: "Startup validation",
    SessionFailureKind.RUNTIME: "Runtime",
}

_FALLBACK_CATEGORY = "Runtime"


@dataclass(frozen=True)
class ErrorView:
    """Transfer-only display values for one terminal failure."""

    category: str
    exception_type: str
    message: str


def category_label(kind: SessionFailureKind) -> str:
    """Return the display label for one existing failure boundary."""

    return _CATEGORY_LABELS.get(kind, _FALLBACK_CATEGORY)


def error_view(result: SessionResult) -> ErrorView | None:
    """Convert a terminal result to its display values.

    Only a ``FAILED`` result that carries an exception produces a view; a
    completed, stopped, or error-free result has nothing to display. The
    category never comes from message or log analysis.
    """

    if result.state is not SessionState.FAILED or result.error is None:
        return None
    kind = result.failure_kind
    if kind is None:
        kind = SessionFailureKind.RUNTIME
    return ErrorView(
        category=category_label(kind),
        exception_type=type(result.error).__name__,
        message=str(result.error),
    )


class ErrorPresenter:
    """Decide once per terminal result whether the error screen must show.

    The controller keeps the same ``SessionResult`` for the lifetime of a
    terminal session, so presenting its view again every frame would rebuild
    the window repeatedly. This presenter returns exactly one view per result
    object and forgets nothing: closing the window never consumes the result,
    and the next session's new failure object is always presented again.
    """

    def __init__(self) -> None:
        self._last_presented: SessionResult | None = None

    def tick(self, result: SessionResult | None) -> ErrorView | None:
        if result is None or result is self._last_presented:
            return None
        view = error_view(result)
        if view is None:
            return None
        self._last_presented = result
        return view
