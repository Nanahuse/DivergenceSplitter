"""Trusted Python configuration loading."""

from pathlib import Path
from runpy import run_path
from typing import Any, cast

from divergencesplitter.frame.source import FrameSource
from divergencesplitter.scenario.models import Scenario

from .validation import validate_scenarios

ConfigurationExports = tuple[tuple[Scenario, ...], FrameSource[Any]]


def load_configuration(path: str | Path) -> ConfigurationExports:
    """Execute a trusted configuration module and extract its fixed exports."""

    namespace = run_path(str(path))
    missing = [
        ValueError(f"configuration must export {name!r}")
        for name in ("scenarios", "frame_source")
        if name not in namespace
    ]
    if missing:
        raise ExceptionGroup("configuration exports are incomplete", missing)

    scenarios = cast("tuple[Scenario, ...]", namespace["scenarios"])
    frame_source = cast("FrameSource[Any]", namespace["frame_source"])
    validate_scenarios(scenarios)
    return scenarios, frame_source
