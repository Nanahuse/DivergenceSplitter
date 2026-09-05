"""Dear PyGui import boundary.

Dear PyGui is a Windows-only dependency, so it is loaded as a module object
rather than resolved statically. This keeps the Linux CI typecheck and test
suite green (where ``dearpygui`` is not installed) while the desktop UI remains
Windows-only. Calling sites treat the returned module as opaque.
"""

from __future__ import annotations

import importlib

dpg = importlib.import_module("dearpygui.dearpygui")
