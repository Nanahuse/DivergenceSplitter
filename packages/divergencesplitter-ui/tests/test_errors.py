from __future__ import annotations

import pytest
from divergencesplitter_ui.errors import (
    ErrorPresenter,
    ErrorView,
    category_label,
    error_view,
)
from divergencesplitter_ui.session import (
    SessionFailureKind,
    SessionResult,
    SessionState,
)


def failed(kind: SessionFailureKind, error: BaseException) -> SessionResult:
    return SessionResult(SessionState.FAILED, error, kind)


class TestCategoryLabels:
    @pytest.mark.parametrize(
        ("kind", "label"),
        [
            (SessionFailureKind.CONFIGURATION_FILE, "Configuration file"),
            (SessionFailureKind.CONFIGURATION_VALIDATION, "Configuration validation"),
            (SessionFailureKind.SCENARIO_EXECUTION, "Scenario execution"),
            (SessionFailureKind.SCENARIO_VALIDATION, "Scenario validation"),
            (SessionFailureKind.SOURCE_CONFIGURATION, "Source configuration"),
            (SessionFailureKind.STARTUP_VALIDATION, "Startup validation"),
            (SessionFailureKind.RUNTIME, "Runtime"),
        ],
    )
    def test_kind_maps_to_expected_display_category(
        self, kind: SessionFailureKind, label: str
    ) -> None:
        assert category_label(kind) == label


class TestErrorView:
    def test_failed_result_builds_view(self) -> None:
        error = ValueError("broken")

        view = error_view(failed(SessionFailureKind.RUNTIME, error))

        assert view is not None
        assert view == ErrorView(
            category="Runtime",
            exception_type="ValueError",
            message="broken",
        )

    def test_exception_type_and_message_come_from_the_exception(self) -> None:
        error = TypeError("Scenario must export exactly one `scenario`.")

        view = error_view(failed(SessionFailureKind.SCENARIO_VALIDATION, error))

        assert view is not None
        assert view.category == "Scenario validation"
        assert view.exception_type == "TypeError"
        assert view.message == "Scenario must export exactly one `scenario`."

    def test_non_failed_states_never_produce_a_view(self) -> None:
        error = RuntimeError("boom")
        for state in (
            SessionState.IDLE,
            SessionState.LOADING,
            SessionState.CONNECTING,
            SessionState.RUNNING,
            SessionState.STOPPING,
            SessionState.COMPLETED,
            SessionState.STOPPED,
        ):
            assert error_view(SessionResult(state, error)) is None

    def test_failed_without_error_never_produces_a_view(self) -> None:
        assert error_view(SessionResult(SessionState.FAILED, None)) is None


class TestErrorPresenter:
    def test_same_terminal_result_is_presented_once(self) -> None:
        presenter = ErrorPresenter()
        result = failed(SessionFailureKind.RUNTIME, ValueError("boom"))

        first = presenter.tick(result)

        assert first is not None
        assert presenter.tick(result) is None
        assert presenter.tick(result) is None

    def test_next_session_new_failure_is_presented_again(self) -> None:
        presenter = ErrorPresenter()
        presenter.tick(failed(SessionFailureKind.RUNTIME, ValueError("one")))

        second = presenter.tick(
            failed(SessionFailureKind.SOURCE_CONFIGURATION, ValueError("two"))
        )

        assert second is not None
        assert second.category == "Source configuration"
        assert second.message == "two"

    def test_non_failed_result_is_ignored_without_consuming(self) -> None:
        presenter = ErrorPresenter()
        completed = SessionResult(SessionState.COMPLETED, None, None)

        assert presenter.tick(completed) is None

        failure = failed(SessionFailureKind.SCENARIO_EXECUTION, RuntimeError("late"))
        assert presenter.tick(failure) is not None
        assert presenter.tick(completed) is None
