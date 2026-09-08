"""Dear PyGui error window for one terminal session failure.

This module imports Dear PyGui and owns the error widgets. It re-renders the
window only when the pure ``ErrorPresenter`` reports a new terminal result;
closing the window never re-runs the runtime, rewrites session state, or
consumes the controller's result.
"""

from __future__ import annotations

from divergencesplitter_ui._dpg import dpg
from divergencesplitter_ui.errors import ErrorPresenter
from divergencesplitter_ui.session import SessionResult


class ErrorWindow:
    """Bind one terminal failure to a Dear PyGui window on the main thread."""

    WINDOW_TAG = "divergence-splitter-error"

    def __init__(self) -> None:
        self._presenter = ErrorPresenter()
        self._category_tag: int | str | None = None
        self._type_tag: int | str | None = None
        self._message_tag: int | str | None = None

    def build(self) -> None:
        """Create the static widgets once, before the render loop."""

        with dpg.window(
            tag=self.WINDOW_TAG,
            label="Error",
            width=460,
            height=200,
            show=False,
            modal=True,
        ):
            dpg.add_text("Category:")
            self._category_tag = dpg.add_text("")
            dpg.add_text("Type:")
            self._type_tag = dpg.add_text("")
            dpg.add_text("Message:")
            self._message_tag = dpg.add_text("", wrap=430)

    def tick(self, result: SessionResult | None) -> None:
        """Present exactly one view for a new terminal result, if any."""

        view = self._presenter.tick(result)
        if view is None:
            return
        if self._category_tag is None or self._type_tag is None:
            return
        if self._message_tag is None:
            return
        dpg.set_value(self._category_tag, view.category)
        dpg.set_value(self._type_tag, view.exception_type)
        dpg.set_value(self._message_tag, view.message)
        dpg.show_item(self.WINDOW_TAG)
