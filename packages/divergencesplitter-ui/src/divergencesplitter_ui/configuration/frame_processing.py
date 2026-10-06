"""Crop and Resize section for the Flet Configuration page.

The section reads and writes the existing ``EditableSourceTransform`` through
``SettingsModel`` and reuses the runtime interpolation enum. Disabling a
transform stores ``None`` but keeps the last field values, so re-enabling does
not lose the draft.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
from divergencesplitter_runtime.configuration.models import ResizeInterpolation

from divergencesplitter_ui.settings import (
    EditableProfile,
    EditPermission,
    SettingsModel,
)

_INTERPOLATION_BY_LABEL = {
    interpolation.value.title(): interpolation for interpolation in ResizeInterpolation
}


def _int_field(
    label: str, value: int, on_change, *, width: int = 140, key: str
) -> ft.TextField:
    return ft.TextField(
        label=label,
        value=str(value),
        width=width,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=on_change,
        key=key,
    )


def _int_value(field: ft.TextField, fallback: int) -> int:
    try:
        return int(field.value.strip())
    except TypeError, ValueError:
        return fallback


class FrameProcessingSection:
    """Edit crop margins and resize output."""

    def __init__(
        self,
        model: SettingsModel,
        *,
        on_changed: Callable[[], None],
    ) -> None:
        self._model = model
        self._on_changed = on_changed
        self._crop_enabled = ft.Switch(
            label="Crop",
            value=False,
            on_change=self._on_crop_enabled_changed,
            key="profile-crop-enabled",
        )
        self._crop_left = _int_field(
            "Left", 0, self._on_crop_changed, key="profile-crop-left"
        )
        self._crop_right = _int_field(
            "Right", 0, self._on_crop_changed, key="profile-crop-right"
        )
        self._crop_top = _int_field(
            "Top", 0, self._on_crop_changed, key="profile-crop-top"
        )
        self._crop_bottom = _int_field(
            "Bottom", 0, self._on_crop_changed, key="profile-crop-bottom"
        )
        self._crop_fields = (
            self._crop_left,
            self._crop_right,
            self._crop_top,
            self._crop_bottom,
        )
        self._resize_enabled = ft.Switch(
            label="Resize",
            value=False,
            on_change=self._on_resize_enabled_changed,
            key="profile-resize-enabled",
        )
        self._resize_width = _int_field(
            "Width", 640, self._on_resize_changed, key="profile-resize-width"
        )
        self._resize_height = _int_field(
            "Height", 360, self._on_resize_changed, key="profile-resize-height"
        )
        self._resize_interpolation = ft.Dropdown(
            label="Interpolation",
            options=[ft.DropdownOption(key=label) for label in _INTERPOLATION_BY_LABEL],
            value=ResizeInterpolation.AREA.value.title(),
            on_select=self._on_resize_interpolation_changed,
            key="profile-resize-interpolation",
        )
        self._resize_references = ft.Switch(
            label="Resize reference images",
            value=False,
            on_change=self._on_resize_references_changed,
            key="profile-resize-references",
        )
        self._resize_fields = (
            self._resize_width,
            self._resize_height,
            self._resize_interpolation,
            self._resize_references,
        )
        self._control = ft.Column(
            controls=[
                ft.Text("Frame processing"),
                self._crop_enabled,
                ft.Row(controls=list(self._crop_fields), spacing=8, wrap=True),
                self._resize_enabled,
                ft.Row(
                    controls=[self._resize_width, self._resize_height],
                    spacing=8,
                    wrap=True,
                ),
                self._resize_interpolation,
                self._resize_references,
            ],
            spacing=6,
        )

    @property
    def control(self) -> ft.Control:
        return self._control

    def apply(
        self,
        draft: EditableProfile,
        permission: EditPermission,
    ) -> bool:
        changed = False
        transform = draft.source.transform
        crop = transform.crop
        resize = transform.resize
        changed |= self._set(self._crop_enabled, crop is not None)
        changed |= self._set(self._resize_enabled, resize is not None)
        if crop is not None:
            changed |= self._set(self._crop_left, str(crop.left))
            changed |= self._set(self._crop_right, str(crop.right))
            changed |= self._set(self._crop_top, str(crop.top))
            changed |= self._set(self._crop_bottom, str(crop.bottom))
        if resize is not None:
            changed |= self._set(self._resize_width, str(resize.width))
            changed |= self._set(self._resize_height, str(resize.height))
            changed |= self._set(
                self._resize_interpolation, resize.interpolation.value.title()
            )
            changed |= self._set(self._resize_references, resize.resize_references)
        for control in (self._crop_enabled, self._resize_enabled):
            changed |= self._set_enabled(control, permission.source)
        for control in self._crop_fields:
            changed |= self._set_enabled(
                control, permission.source and crop is not None
            )
        for control in self._resize_fields:
            changed |= self._set_enabled(
                control, permission.source and resize is not None
            )
        return changed

    @staticmethod
    def _set(control, value) -> bool:
        if control.value == value:
            return False
        control.value = value
        return True

    @staticmethod
    def _set_enabled(control, enabled: bool) -> bool:
        if control.disabled == enabled:
            control.disabled = not enabled
            return True
        return False

    def _crop_values(self) -> tuple[int, int, int, int]:
        draft = self._model.draft
        assert draft is not None
        current = draft.source.transform.crop
        assert current is not None
        return (
            _int_value(self._crop_left, current.left),
            _int_value(self._crop_right, current.right),
            _int_value(self._crop_top, current.top),
            _int_value(self._crop_bottom, current.bottom),
        )

    def _on_crop_enabled_changed(self, event: ft.Event[ft.Switch]) -> None:
        if bool(self._crop_enabled.value):
            self._model.set_crop_values(
                _int_value(self._crop_left, 0),
                _int_value(self._crop_right, 0),
                _int_value(self._crop_top, 0),
                _int_value(self._crop_bottom, 0),
            )
        else:
            self._model.set_crop(None)
        self._on_changed()

    def _on_crop_changed(self, event: ft.Event[ft.TextField]) -> None:
        draft = self._model.draft
        if draft is None or draft.source.transform.crop is None:
            return
        self._model.set_crop_values(*self._crop_values())
        self._on_changed()

    def _on_resize_enabled_changed(self, event: ft.Event[ft.Switch]) -> None:
        if bool(self._resize_enabled.value):
            self._model.set_resize_values(
                _int_value(self._resize_width, 640),
                _int_value(self._resize_height, 360),
            )
        else:
            self._model.set_resize(None)
        self._on_changed()

    def _on_resize_changed(self, event: ft.Event[ft.TextField]) -> None:
        draft = self._model.draft
        if draft is None or draft.source.transform.resize is None:
            return
        self._model.set_resize_values(
            _int_value(self._resize_width, 640),
            _int_value(self._resize_height, 360),
        )
        self._on_changed()

    def _on_resize_interpolation_changed(self, event: ft.Event[ft.Dropdown]) -> None:
        interpolation = _INTERPOLATION_BY_LABEL.get(
            self._resize_interpolation.value or ""
        )
        if interpolation is None:
            return
        self._model.set_resize_interpolation(interpolation)
        self._on_changed()

    def _on_resize_references_changed(self, event: ft.Event[ft.Switch]) -> None:
        self._model.set_resize_references(bool(self._resize_references.value))
        self._on_changed()
