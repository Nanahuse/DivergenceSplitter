"""File dialog access for the Flet Configuration page.

The Configuration logic depends on the small ``FileDialogs`` protocol so its
New/Open/Save behaviour can be tested without a GUI. ``FletFileDialogs`` is the
runtime implementation backed by ``flet.FilePicker`` and a discard
confirmation ``flet.AlertDialog``. Native Windows dialogs are used on desktop,
so no custom file browser is built here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

import flet as ft

CONFIGURATION_EXTENSIONS = ("json",)
SCENARIO_EXTENSIONS = ("py", "yaml", "yml")
VIDEO_EXTENSIONS = ("mp4", "mkv", "avi", "mov", "webm", "m4v")


def normalize_selected_path(value: str | None) -> Path | None:
    """Return the absolute path chosen in a dialog, or ``None`` on cancel."""

    if not value:
        return None
    return Path(value).expanduser().resolve()


class FileDialogs(Protocol):
    """The file selection surface the Configuration actions depend on."""

    async def open_file(
        self,
        *,
        title: str,
        extensions: tuple[str, ...],
        initial_path: Path | None = None,
    ) -> Path | None: ...

    async def save_file(
        self,
        *,
        title: str,
        extensions: tuple[str, ...],
        initial_path: Path | None = None,
        default_name: str | None = None,
    ) -> Path | None: ...

    async def confirm_discard(self) -> bool: ...


class FletFileDialogs:
    """Back the file dialogs with ``flet.FilePicker`` and an alert dialog."""

    def __init__(self, page: ft.Page, file_picker: ft.FilePicker) -> None:
        self._page = page
        self._picker = file_picker

    async def open_file(
        self,
        *,
        title: str,
        extensions: tuple[str, ...],
        initial_path: Path | None = None,
    ) -> Path | None:
        files = await self._picker.pick_files(
            dialog_title=title,
            initial_directory=(
                None if initial_path is None else str(initial_path.parent)
            ),
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=list(extensions),
            allow_multiple=False,
        )
        if not files:
            return None
        return normalize_selected_path(files[0].path)

    async def save_file(
        self,
        *,
        title: str,
        extensions: tuple[str, ...],
        initial_path: Path | None = None,
        default_name: str | None = None,
    ) -> Path | None:
        if default_name is None and initial_path is not None:
            default_name = initial_path.name
        path = await self._picker.save_file(
            dialog_title=title,
            file_name=default_name,
            initial_directory=(
                None if initial_path is None else str(initial_path.parent)
            ),
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=list(extensions),
        )
        return normalize_selected_path(path)

    async def confirm_discard(self) -> bool:
        loop = asyncio.get_running_loop()
        result: asyncio.Future[bool] = loop.create_future()

        def finish(value: bool) -> None:
            if not result.done():
                result.set_result(value)
            self._page.pop_dialog()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("DivergenceSplitter"),
            content=ft.Text("Discard unsaved changes?"),
            actions=[
                ft.TextButton(content="Cancel", on_click=lambda e: finish(False)),
                ft.TextButton(content="Discard", on_click=lambda e: finish(True)),
            ],
            on_dismiss=lambda e: finish(False),
        )
        self._page.show_dialog(dialog)
        return await result
