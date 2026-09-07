"""Scenario file loading dispatcher.

``load_scenario`` selects a loader from the file extension and returns a single
:class:`~divergencesplitter.scenario.models.Scenario`. The CLI and UI never deal
with the scenario file format directly.
"""

from pathlib import Path

from divergencesplitter.scenario.models import Scenario

from divergencesplitter_runtime.configuration.scenario_module import (
    ScenarioLoaderError,
    ScenarioModuleExecutionError,
    ScenarioModuleValidationError,
    load_scenario_module,
)
from divergencesplitter_runtime.configuration.scenario_yaml import (
    ScenarioYamlError,
    load_scenario_yaml,
)

_PYTHON_SUFFIXES = (".py",)
_YAML_SUFFIXES = (".yaml", ".yml")


def load_scenario(path: str | Path) -> Scenario:
    """Load one Scenario from a Python or YAML scenario file."""

    resolved = Path(path)
    suffix = resolved.suffix.lower()
    if suffix in _PYTHON_SUFFIXES:
        return load_scenario_module(resolved)
    if suffix in _YAML_SUFFIXES:
        try:
            return load_scenario_yaml(resolved)
        except ScenarioYamlError as error:
            raise ScenarioLoaderError(error) from error
    raise ValueError(f"unsupported scenario format: {resolved.suffix!r}")


__all__ = [
    "ScenarioLoaderError",
    "ScenarioModuleExecutionError",
    "ScenarioModuleValidationError",
    "ScenarioYamlError",
    "load_scenario",
    "load_scenario_module",
    "load_scenario_yaml",
]
