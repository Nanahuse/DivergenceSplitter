"""Trusted Python scenario module loading."""

from pathlib import Path
from runpy import run_path
from typing import TypeIs

from divergencesplitter.scenario.models import Scenario

from divergencesplitter_runtime.configuration.validation import validate_scenarios


class ScenarioModuleExecutionError(Exception):
    """A trusted scenario module could not be executed."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        super().__init__(type(error).__name__)


class ScenarioModuleValidationError(ExceptionGroup):
    """Scenario module exports or static constraints are invalid."""


def load_scenario_module(
    path: str | Path,
) -> tuple[Scenario, ...]:
    """Execute a trusted Python module and extract its scenarios."""

    try:
        namespace = run_path(str(path))
    except KeyboardInterrupt:
        raise
    except BaseException as error:
        raise ScenarioModuleExecutionError(error) from error
    errors: list[Exception] = []
    scenarios: tuple[Scenario, ...] | None = None

    if "scenarios" not in namespace:
        errors.append(ValueError("scenario module must export 'scenarios'"))
    else:
        scenarios_value = namespace["scenarios"]
        if _is_scenario_tuple(scenarios_value):
            scenarios = scenarios_value
        else:
            errors.extend(_scenario_type_errors(scenarios_value))

    if "frame_source" in namespace:
        errors.append(
            ValueError(
                "scenario module must not export 'frame_source'; "
                "configure the source in the JSON file"
            )
        )

    if errors:
        raise ScenarioModuleValidationError(
            "scenario module exports are invalid",
            errors,
        )
    if scenarios is None:
        raise RuntimeError("scenario module export validation did not produce values")

    try:
        validate_scenarios(scenarios)
    except ExceptionGroup as error:
        raise ScenarioModuleValidationError(
            "scenario module configuration is invalid",
            list(error.exceptions),
        ) from error
    return scenarios


def _is_scenario_tuple(value: object) -> TypeIs[tuple[Scenario, ...]]:
    return isinstance(value, tuple) and all(
        isinstance(scenario, Scenario) for scenario in value
    )


def _scenario_type_errors(value: object) -> list[Exception]:
    if not isinstance(value, tuple):
        return [TypeError("scenario module export 'scenarios' is not a tuple")]
    return [
        TypeError(f"scenario module export 'scenarios[{index}]' is not a Scenario")
        for index, scenario in enumerate(value)
        if not isinstance(scenario, Scenario)
    ]
