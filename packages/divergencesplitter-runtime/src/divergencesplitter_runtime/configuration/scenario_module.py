"""Trusted Python scenario module loading."""

from pathlib import Path
from runpy import run_path

from divergencesplitter.scenario.models import Scenario

from divergencesplitter_runtime.configuration.validation import validate_scenario


class ScenarioModuleExecutionError(Exception):
    """A trusted scenario module could not be executed."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        super().__init__(type(error).__name__)


class ScenarioModuleValidationError(ExceptionGroup):
    """Scenario module exports or static constraints are invalid."""


class ScenarioLoaderError(Exception):
    """A scenario could not be loaded from its file."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        super().__init__(str(error))


def load_scenario_module(path: str | Path) -> Scenario:
    """Execute a trusted Python module and extract its scenario."""

    try:
        namespace = run_path(str(path))
    except KeyboardInterrupt:
        raise
    except BaseException as error:
        raise ScenarioModuleExecutionError(error) from error
    errors: list[Exception] = []
    scenario: Scenario | None = None

    if "scenario" not in namespace:
        errors.append(ValueError("scenario module must export 'scenario'"))
    else:
        scenario_value = namespace["scenario"]
        if isinstance(scenario_value, Scenario):
            scenario = scenario_value
        else:
            errors.append(
                TypeError(
                    "scenario module export 'scenario' is not a Scenario, "
                    f"got {type(scenario_value).__name__}"
                )
            )

    if "frame_source" in namespace:
        errors.append(
            ValueError(
                "scenario module must not export 'frame_source'; "
                "configure the source in the JSON file"
            )
        )

    if "connection" in namespace:
        errors.append(
            ValueError(
                "scenario module must not export 'connection'; "
                "configure the connection in the JSON file"
            )
        )

    if errors:
        raise ScenarioModuleValidationError(
            "scenario module exports are invalid",
            errors,
        )
    if scenario is None:
        raise RuntimeError("scenario module export validation did not produce a value")

    try:
        validate_scenario(scenario)
    except ExceptionGroup as error:
        raise ScenarioModuleValidationError(
            "scenario module configuration is invalid",
            list(error.exceptions),
        ) from error
    return scenario
