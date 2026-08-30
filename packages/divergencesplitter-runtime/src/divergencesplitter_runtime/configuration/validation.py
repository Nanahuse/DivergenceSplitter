"""Semantic startup validation for pre-constructed configuration objects."""

from divergencesplitter.scenario.models import Scenario

from divergencesplitter_runtime.livesplit.models import LiveSplitSnapshot, TimerPhase


def validate_scenarios(scenarios: tuple[Scenario, ...]) -> None:
    errors: list[Exception] = []
    rpc_owners: dict[str, int] = {}
    event_owners: dict[str, int] = {}

    for index, scenario in enumerate(scenarios):
        connection = scenario.connection
        if not connection.rpc_endpoint:
            errors.append(ValueError(f"scenarios[{index}].rpc_endpoint is empty"))
        if not connection.event_endpoint:
            errors.append(ValueError(f"scenarios[{index}].event_endpoint is empty"))
        if not scenario.reset_conditions:
            errors.append(ValueError(f"scenarios[{index}] has no reset conditions"))

        previous = rpc_owners.get(connection.rpc_endpoint)
        if previous is not None:
            errors.append(
                ValueError(
                    f"scenarios[{index}] shares rpc_endpoint with scenarios[{previous}]"
                )
            )
        else:
            rpc_owners[connection.rpc_endpoint] = index

        previous = event_owners.get(connection.event_endpoint)
        if previous is not None:
            errors.append(
                ValueError(
                    f"scenarios[{index}] shares event_endpoint with scenarios[{previous}]"
                )
            )
        else:
            event_owners[connection.event_endpoint] = index

    if errors:
        raise ExceptionGroup("scenario configuration is invalid", errors)


def validate_split_count(scenario: Scenario, snapshot: LiveSplitSnapshot) -> None:
    """Validate the scenario once LiveSplit provides its authoritative count."""

    if snapshot.phase is TimerPhase.NOT_RUNNING and snapshot.split_count == 0:
        return
    if len(scenario.splits) > snapshot.split_count + 1:
        raise ValueError(
            "scenario has more split slots than the LiveSplit split count plus one"
        )
