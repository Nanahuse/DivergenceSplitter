"""Flet error dialog for one terminal session failure.

The dialog reuses the pure ``ErrorPresenter`` so the failure classification and
the "present once per result" decision stay in one place. It only displays; a
close never restarts, stops, or resets the session, and the controller's
terminal result is left untouched.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from divergencesplitter_ui.errors import ErrorPresenter, ErrorView
from divergencesplitter_ui.session import SessionResult


class ErrorDialog:
    """Present exactly one dialog per new terminal failure result."""

    def __init__(
        self,
        *,
        show_dialog: Callable[[ft.AlertDialog], None],
        hide_dialog: Callable[[], object],
    ) -> None:
        self._show = show_dialog
        self._hide = hide_dialog
        self._presenter = ErrorPresenter()
        self._open = False

    def tick(self, result: SessionResult | None) -> bool:
        """Present the result once; return whether a dialog was shown."""

        view = self._presenter.tick(result)
        if view is None:
            return False
        self._show(self._build(view))
        self._open = True
        return True

    def _build(self, view: ErrorView) -> ft.AlertDialog:
        return ft.AlertDialog(
            modal=True,
            title=ft.Text("Error"),
            content=ft.Column(
                controls=[
                    ft.Text(f"Category: {view.category}"),
                    ft.Text(f"Type: {view.exception_type}"),
                    ft.Text(f"Message: {view.message}", selectable=True),
                ],
                tight=True,
                spacing=6,
            ),
            actions=[ft.TextButton(content="Close", on_click=self._close)],
            on_dismiss=self._dismissed,
        )

    def _close(self) -> None:
        # Closing the dialog is a display action only.
        if not self._open:
            return
        self._open = False
        self._hide()

    def _dismissed(self) -> None:
        if not self._open:
            return
        self._open = False
        self._hide()
