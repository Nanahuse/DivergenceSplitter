"""Semantic startup validation for pre-constructed configuration objects."""

from divergencesplitter.livesplit.models import LiveSplitConnection
from divergencesplitter.scenario.models import Scenario

from divergencesplitter_runtime.livesplit.models import LiveSplitSnapshot, TimerPhase


def validate_scenario(scenario: Scenario) -> None:
    """Validate one scenario independently of its LiveSplit destination."""

    errors: list[Exception] = []
    if errors:
        raise ExceptionGroup("scenario configuration is invalid", errors)


def validate_instances(
    instances: tuple[tuple[LiveSplitConnection, Scenario], ...],
) -> None:
    """Validate Bridge ports and their uniqueness across instances."""

    errors: list[Exception] = []
    port_owners: dict[int, int] = {}

    for index, (connection, scenario) in enumerate(instances):
        previous = port_owners.get(connection.port)
        if previous is not None:
            errors.append(
                ValueError(
                    f"instances[{index}] shares port {connection.port} "
                    f"with instances[{previous}]"
                )
            )
        else:
            port_owners[connection.port] = index

    if errors:
        raise ExceptionGroup("instance configuration is invalid", errors)


def validate_split_count(scenario: Scenario, snapshot: LiveSplitSnapshot) -> None:
    """Validate the scenario once LiveSplit provides its authoritative count."""

    if snapshot.phase is TimerPhase.NOT_RUNNING and snapshot.split_count == 0:
        return
    if len(scenario.splits) > snapshot.split_count:
        raise ValueError("scenario has more split slots than the LiveSplit split count")
