"""Composition root for the in-process Flet UI integration suite.

The harness wires the *real* UI components (Navigation, ProfileHeader,
ProfilePage, SettingsPage, Monitor, Diagnostics, SettingsModel, ProfileActions,
AppSettingsActions, and every Flet control) to a small set of test doubles for
the external boundaries (session/runtime, camera enumeration, NDI, preview, file
dialogs). It then mounts that application on a recording page, so a test drives
the same event and update path the desktop application uses.

The app runs entirely in-process, which is what lets a test inject doubles and
read the real control state. Actual Flutter rendering is covered separately by
the official ``flet test`` smoke suite in ``integration_smoke``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import flet as ft
from divergencesplitter_ui.configuration.preview import PreviewController
from divergencesplitter_ui.configuration.profile_header import ProfileHeader
from divergencesplitter_ui.flet_application import FletApplication
from divergencesplitter_ui.monitor.page import Monitor
from divergencesplitter_ui.ndi_discovery import NdiDiscovery
from divergencesplitter_ui.session import SessionController
from divergencesplitter_ui.settings import SettingsModel

from integration_tests.fakes import (
    FakeCameraEnumerator,
    FakeDiagnostics,
    FakeDiagnosticsFactory,
    FakeDialogs,
    FakeNdiDiscovery,
    FakePreviewController,
    FakeProfileLoader,
    FakeRuntimeFactory,
    FakeScenarioLoader,
    FakeSourceBuilder,
    sample_profile,
)
from integration_tests.page import (
    RecordingPage,
    dispatch_event,
    enter_text,
    find_by_key,
    select,
    tap,
)


@dataclass
class Harness:
    """One mounted application plus the doubles a test steers."""

    controller: SessionController
    model: SettingsModel
    diagnostics_factory: FakeDiagnosticsFactory
    runtime_factory: FakeRuntimeFactory
    dialogs: FakeDialogs
    ndi_discovery: FakeNdiDiscovery
    preview_controller: FakePreviewController
    settings_path: Path
    profile_a: Path
    profile_b: Path
    video_a: Path
    video_b: Path
    scenario_a: Path
    scenario_b: Path
    initial_profile: Path | None = None
    app: FletApplication | None = None
    page: RecordingPage = field(default_factory=RecordingPage)

    @property
    def header(self) -> ProfileHeader:
        assert self.app is not None and self.app.header is not None
        return self.app.header

    @property
    def monitor(self) -> Monitor:
        assert self.app is not None and self.app.monitor is not None
        return self.app.monitor

    @property
    def diagnostics(self) -> FakeDiagnostics:
        """The diagnostics instance of the currently running session."""

        return self.diagnostics_factory.latest

    @property
    def runtime(self) -> object:
        """The most recently created fake runtime."""

        return self.runtime_factory.runtimes[-1]

    async def mount(self) -> None:
        application = FletApplication(
            self.controller,
            initial_profile=self.initial_profile,
            settings_model=self.model,
            settings_path=self.settings_path,
            dialogs_factory=lambda _page: self.dialogs,
            ndi_discovery=cast(NdiDiscovery, self.ndi_discovery),
            preview_controller=cast(PreviewController, self.preview_controller),
        )
        self.app = application
        await application.mount(cast(ft.Page, self.page))

    async def shutdown(self) -> None:
        if self.app is not None:
            await self.app.shutdown()

    def find(self, key: str) -> ft.Control:
        """Find a mounted control by its stable key."""

        return find_by_key(self.page, key)

    def value(self, key: str) -> str:
        """Read the string value of a mounted control."""

        value = getattr(self.find(key), "value", None)
        assert isinstance(value, str)
        return value

    def disabled(self, key: str) -> bool:
        """Read the enabled/disabled state of a mounted control."""

        return bool(getattr(self.find(key), "disabled", False))

    async def wait_until(
        self, predicate: Callable[[], bool], *, timeout: float = 8.0
    ) -> None:
        """Wait for the application's update loops to satisfy ``predicate``."""

        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("condition was not satisfied before timeout")
            await asyncio.sleep(0.02)

    async def navigate(self, view: str) -> None:
        """Select a navigation entry and wait for the view to become active."""

        assert self.app is not None
        app = self.app
        await tap(self.find(f"nav-{view}"))
        await self.wait_until(lambda: app.active_view.value == view)

    async def tap(self, key: str) -> None:
        await tap(self.find(key))

    async def select_tab(self, index: int) -> None:
        """Switch the Profile body tab and dispatch its public change handler."""

        tabs = cast(ft.Tabs, self.find("profile-tabs"))
        tabs.selected_index = index
        await dispatch_event(tabs.on_change, tabs, "change")

    async def select(self, key: str, value: str) -> None:
        await select(cast(ft.Dropdown, self.find(key)), value)

    async def enter_text(self, key: str, value: str) -> None:
        await enter_text(cast(ft.TextField, self.find(key)), value)


def _write_profile(path: Path, video: Path, scenario: Path) -> None:
    from divergencesplitter_runtime.configuration.profile_json import save_profile

    save_profile(path, sample_profile(video_path=video, scenario_path=scenario))


def build_harness(
    tmp_path: Path,
    *,
    with_initial_profile: bool = False,
    release_on_run: bool = False,
    ndi_available: bool = False,
) -> Harness:
    """Compose one application with doubles, ready to be mounted."""

    work = tmp_path / "profiles"
    work.mkdir(parents=True, exist_ok=True)
    profile_a = work / "profile_a.json"
    profile_b = work / "profile_b.json"
    video_a = work / "video_a.mp4"
    video_b = work / "video_b.mp4"
    scenario_a = work / "scenario_a.py"
    scenario_b = work / "scenario_b.py"
    _write_profile(profile_a, video_a, scenario_a)
    _write_profile(profile_b, video_b, scenario_b)

    runtime_factory = FakeRuntimeFactory(release_on_run=release_on_run)
    diagnostics_factory = FakeDiagnosticsFactory()
    controller = SessionController(
        profile_loader=FakeProfileLoader(
            profile=sample_profile(video_path=video_a, scenario_path=scenario_a)
        ),
        scenario_loader=FakeScenarioLoader(),
        source_builder=FakeSourceBuilder(),
        runtime_factory=runtime_factory,
        diagnostics_factory=diagnostics_factory,
    )
    model = SettingsModel(FakeCameraEnumerator())
    return Harness(
        controller=controller,
        model=model,
        diagnostics_factory=diagnostics_factory,
        runtime_factory=runtime_factory,
        dialogs=FakeDialogs(),
        ndi_discovery=FakeNdiDiscovery(available=ndi_available),
        preview_controller=FakePreviewController(),
        settings_path=tmp_path / "app_settings.json",
        profile_a=profile_a,
        profile_b=profile_b,
        video_a=video_a,
        video_b=video_b,
        scenario_a=scenario_a,
        scenario_b=scenario_b,
        initial_profile=profile_a if with_initial_profile else None,
    )
