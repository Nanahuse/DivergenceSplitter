"""Small Windows common-dialog adapter used by the UI pages.

This module deliberately has no Dear PyGui dependency.  The native dialog is
loaded lazily so the pure filter and path helpers remain testable elsewhere.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileDialogFilter:
    description: str
    patterns: tuple[str, ...]


CONFIGURATION_FILTERS = (
    FileDialogFilter("JSON configuration", ("*.json",)),
    FileDialogFilter("All files", ("*.*",)),
)
SCENARIO_FILTERS = (
    FileDialogFilter("Scenario files", ("*.py", "*.yaml", "*.yml")),
    FileDialogFilter("Python scenario", ("*.py",)),
    FileDialogFilter("YAML scenario", ("*.yaml", "*.yml")),
    FileDialogFilter("All files", ("*.*",)),
)


def filter_string(filters: Sequence[FileDialogFilter]) -> str:
    """Build the double-NUL terminated filter string expected by Win32."""

    parts: list[str] = []
    for item in filters:
        parts.extend((item.description, ";".join(item.patterns)))
    return "\0".join(parts) + "\0\0"


def normalize_selected_path(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value).expanduser().resolve()


def confirm_discard() -> bool:
    """Ask whether unsaved draft changes may be discarded."""

    if sys.platform != "win32":
        return False
    result = ctypes.windll.user32.MessageBoxW(
        None,
        "Discard unsaved changes?",
        "DivergenceSplitter",
        0x00000004 | 0x00000030,
    )
    return result == 6


def select_open_file(
    *,
    title: str,
    filters: Sequence[FileDialogFilter],
    initial_path: Path | None = None,
) -> Path | None:
    """Open the Windows Explorer-style modal file picker."""

    if sys.platform != "win32":
        return None

    class OpenFileName(ctypes.Structure):
        _fields_ = [
            ("lStructSize", ctypes.c_uint32),
            ("hwndOwner", ctypes.c_void_p),
            ("hInstance", ctypes.c_void_p),
            ("lpstrFilter", ctypes.c_wchar_p),
            ("lpstrCustomFilter", ctypes.c_wchar_p),
            ("nMaxCustFilter", ctypes.c_uint32),
            ("nFilterIndex", ctypes.c_uint32),
            ("lpstrFile", ctypes.c_wchar_p),
            ("nMaxFile", ctypes.c_uint32),
            ("lpstrFileTitle", ctypes.c_wchar_p),
            ("nMaxFileTitle", ctypes.c_uint32),
            ("lpstrInitialDir", ctypes.c_wchar_p),
            ("lpstrTitle", ctypes.c_wchar_p),
            ("Flags", ctypes.c_uint32),
            ("nFileOffset", ctypes.c_uint16),
            ("nFileExtension", ctypes.c_uint16),
            ("lpstrDefExt", ctypes.c_wchar_p),
            ("lCustData", ctypes.c_size_t),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", ctypes.c_wchar_p),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", ctypes.c_uint32),
            ("FlagsEx", ctypes.c_uint32),
        ]

    buffer = ctypes.create_unicode_buffer(32768)
    if initial_path is not None:
        buffer.value = str(initial_path)
    dialog = OpenFileName(
        lStructSize=ctypes.sizeof(OpenFileName),
        lpstrFilter=filter_string(filters),
        nFilterIndex=1,
        lpstrFile=ctypes.cast(buffer, ctypes.c_wchar_p),
        nMaxFile=len(buffer),
        lpstrInitialDir=str(initial_path.parent) if initial_path else None,
        lpstrTitle=title,
        Flags=0x00001000 | 0x00000800 | 0x00080000,
    )
    if not ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(dialog)):
        return None
    return normalize_selected_path(buffer.value)


def select_save_file(
    *,
    title: str,
    filters: Sequence[FileDialogFilter],
    initial_path: Path | None = None,
) -> Path | None:
    """Open the Windows Explorer-style save picker."""

    if sys.platform != "win32":
        return None

    class OpenFileName(ctypes.Structure):
        _fields_ = [
            ("lStructSize", ctypes.c_uint32),
            ("hwndOwner", ctypes.c_void_p),
            ("hInstance", ctypes.c_void_p),
            ("lpstrFilter", ctypes.c_wchar_p),
            ("lpstrCustomFilter", ctypes.c_wchar_p),
            ("nMaxCustFilter", ctypes.c_uint32),
            ("nFilterIndex", ctypes.c_uint32),
            ("lpstrFile", ctypes.c_wchar_p),
            ("nMaxFile", ctypes.c_uint32),
            ("lpstrFileTitle", ctypes.c_wchar_p),
            ("nMaxFileTitle", ctypes.c_uint32),
            ("lpstrInitialDir", ctypes.c_wchar_p),
            ("lpstrTitle", ctypes.c_wchar_p),
            ("Flags", ctypes.c_uint32),
            ("nFileOffset", ctypes.c_uint16),
            ("nFileExtension", ctypes.c_uint16),
            ("lpstrDefExt", ctypes.c_wchar_p),
            ("lCustData", ctypes.c_size_t),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", ctypes.c_wchar_p),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", ctypes.c_uint32),
            ("FlagsEx", ctypes.c_uint32),
        ]

    buffer = ctypes.create_unicode_buffer(32768)
    if initial_path is not None:
        buffer.value = str(initial_path)
    dialog = OpenFileName(
        lStructSize=ctypes.sizeof(OpenFileName),
        lpstrFilter=filter_string(filters),
        nFilterIndex=1,
        lpstrFile=ctypes.cast(buffer, ctypes.c_wchar_p),
        nMaxFile=len(buffer),
        lpstrInitialDir=str(initial_path.parent) if initial_path else None,
        lpstrTitle=title,
        Flags=0x00000002 | 0x00000800 | 0x00080000,
        lpstrDefExt="json",
    )
    if not ctypes.windll.comdlg32.GetSaveFileNameW(ctypes.byref(dialog)):
        return None
    return normalize_selected_path(buffer.value)
