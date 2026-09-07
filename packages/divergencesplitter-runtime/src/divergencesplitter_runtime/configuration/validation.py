"""Semantic startup validation for pre-constructed configuration objects."""

from divergencesplitter.livesplit.models import LiveSplitConnection
from divergencesplitter.scenario.models import Scenario

from divergencesplitter_runtime.livesplit.models import LiveSplitSnapshot, TimerPhase


def validate_scenario(scenario: Scenario) -> None:
    """Validate one scenario independently of its LiveSplit destination."""

    errors: list[Exception] = []
    if not scenario.reset_conditions:
        errors.append(ValueError("scenario has no reset conditions"))
    if errors:
        raise ExceptionGroup("scenario configuration is invalid", errors)


def validate_instances(
    instances: tuple[tuple[LiveSplitConnection, Scenario], ...],
) -> None:
    """Validate connection endpoints and their uniqueness across instances."""

    errors: list[Exception] = []
    rpc_owners: dict[str, int] = {}
    event_owners: dict[str, int] = {}

    for index, (connection, scenario) in enumerate(instances):
        if not connection.rpc_endpoint:
            errors.append(ValueError(f"instances[{index}].rpc_endpoint is empty"))
        if not connection.event_endpoint:
            errors.append(ValueError(f"instances[{index}].event_endpoint is empty"))
        if not scenario.reset_conditions:
            errors.append(ValueError(f"instances[{index}] has no reset conditions"))

        previous = rpc_owners.get(connection.rpc_endpoint)
        if previous is not None:
            errors.append(
                ValueError(
                    f"instances[{index}] shares rpc_endpoint with instances[{previous}]"
                )
            )
        else:
            rpc_owners[connection.rpc_endpoint] = index

        previous = event_owners.get(connection.event_endpoint)
        if previous is not None:
            errors.append(
                ValueError(
                    f"instances[{index}] shares event_endpoint with instances[{previous}]"
                )
            )
        else:
            event_owners[connection.event_endpoint] = index

    if errors:
        raise ExceptionGroup("instance configuration is invalid", errors)


def validate_split_count(scenario: Scenario, snapshot: LiveSplitSnapshot) -> None:
    """Validate the scenario once LiveSplit provides its authoritative count."""

    if snapshot.phase is TimerPhase.NOT_RUNNING and snapshot.split_count == 0:
        return
    if len(scenario.splits) > snapshot.split_count + 1:
        raise ValueError(
            "scenario has more split slots than the LiveSplit split count plus one"
        )
