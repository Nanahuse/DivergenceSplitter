from pathlib import Path

import cv2
import numpy as np
import pytest
from divergencesplitter import Detected, TemplateMatchDetector, Then
from divergencesplitter_runtime.configuration.scenario_yaml import (
    ScenarioYamlError,
    ScenarioYamlValidationError,
    load_scenario_yaml,
)


def write_reference_image(directory: Path, name: str = "title.png") -> Path:
    image = np.array(
        [
            [0, 255, 255, 0],
            [255, 0, 0, 255],
            [255, 0, 0, 255],
            [0, 255, 255, 0],
        ],
        dtype=np.uint8,
    )
    color = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    path = directory / name
    assert cv2.imwrite(str(path), color)
    return path


def write_scenario(directory: Path, content: str, name: str = "scenario.yaml") -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_detected_template_match_scenario(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    write_reference_image(tmp_path / "images", "title.png")
    path = write_scenario(
        tmp_path,
        """
start_condition:
  type: detected
  minimum_score: 0.8
  detector:
    type: template_match
    reference: ./images/title.png

reset_condition:
  type: detected
  minimum_score: 0.8
  detector:
    type: template_match
    reference: ./images/title.png

splits:
  - rules:
      - condition:
          type: detected
          minimum_score: 0.9
          detector:
            type: template_match
            reference: ./images/title.png
        action: split
""",
    )

    scenario = load_scenario_yaml(path)

    reset = scenario.reset_condition
    assert isinstance(reset, Detected)
    assert reset.minimum_score == 0.8
    rules = scenario.splits[0]
    assert rules is not None
    assert rules[0].action.operation == "split"
    assert isinstance(rules[0].condition, Detected)
    assert isinstance(rules[0].condition.detector, TemplateMatchDetector)


def test_incomplete_condition_is_optional_and_loaded_when_present(
    tmp_path: Path,
) -> None:
    write_reference_image(tmp_path, "title.png")
    path = write_scenario(
        tmp_path,
        """
start_condition:
  type: detected
  minimum_score: 0.8
  detector: {type: template_match, reference: ./title.png}
reset_condition:
  type: detected
  minimum_score: 0.8
  detector: {type: template_match, reference: ./title.png}
incomplete_condition:
  type: detected
  minimum_score: 0.8
  detector: {type: template_match, reference: ./title.png}
splits: []
""",
    )

    scenario = load_scenario_yaml(path)

    assert isinstance(scenario.incomplete_condition, Detected)


def test_template_match_roi_is_loaded(tmp_path: Path) -> None:
    write_reference_image(tmp_path, "title.png")
    path = write_scenario(
        tmp_path,
        """
start_condition:
  type: detected
  minimum_score: 0.8
  detector:
    type: template_match
    reference: ./title.png
    roi: {x: 1, y: 2, width: 3, height: 4}
reset_condition:
  type: detected
  minimum_score: 0.8
  detector:
    type: template_match
    reference: ./title.png
splits: []
""",
    )

    scenario = load_scenario_yaml(path)

    assert isinstance(scenario.start_condition, Detected)
    assert isinstance(scenario.start_condition.detector, TemplateMatchDetector)
    assert scenario.start_condition.detector.config.roi is not None
    assert scenario.start_condition.detector.config.roi.x == 1


def test_incomplete_condition_can_be_omitted_but_not_null(tmp_path: Path) -> None:
    write_reference_image(tmp_path, "title.png")
    base = """
start_condition:
  type: detected
  minimum_score: 0.8
  detector: {type: template_match, reference: ./title.png}
reset_condition:
  type: detected
  minimum_score: 0.8
  detector: {type: template_match, reference: ./title.png}
splits: []
"""
    omitted = load_scenario_yaml(write_scenario(tmp_path, base))
    assert omitted.incomplete_condition is None

    with pytest.raises(ScenarioYamlValidationError):
        load_scenario_yaml(
            write_scenario(
                tmp_path,
                base.replace("splits: []", "incomplete_condition: null\nsplits: []"),
                "null.yaml",
            )
        )


def test_old_reset_conditions_schema_is_rejected(tmp_path: Path) -> None:
    path = write_scenario(
        tmp_path,
        """
reset_conditions: []
splits: []
""",
    )

    with pytest.raises(ScenarioYamlValidationError):
        load_scenario_yaml(path)


def test_loads_then_condition_with_time_and_nested_conditions(tmp_path: Path) -> None:
    write_reference_image(tmp_path, "title.png")
    path = write_scenario(
        tmp_path,
        """
start_condition:
  type: detected
  minimum_score: 0.5
  detector:
    type: template_match
    reference: ./title.png

reset_condition:
  type: detected
  minimum_score: 0.5
  detector:
    type: template_match
    reference: ./title.png

splits:
  - rules:
      - condition:
          type: then
          within: 3s
          conditions:
            - type: detected
              minimum_score: 0.9
              detector:
                type: template_match
                reference: ./title.png
            - type: detected
              minimum_score: 0.95
              detector:
                type: template_match
                reference: ./title.png
        action: split
""",
    )

    scenario = load_scenario_yaml(path)

    rules = scenario.splits[0]
    assert rules is not None
    condition = rules[0].condition
    assert isinstance(condition, Then)
    assert len(condition.children) == 2


@pytest.mark.parametrize(
    ("text", "expected_ns"),
    [
        ("500ms", 500_000_000),
        ("2s", 2_000_000_000),
        ("1.5s", 1_500_000_000),
    ],
)
def test_duration_expressions_parse_to_nanoseconds(
    tmp_path: Path,
    text: str,
    expected_ns: int,
) -> None:
    from divergencesplitter_runtime.configuration.scenario_yaml import _duration

    assert _duration(text, "within") == expected_ns


def test_anchor_and_alias_are_resolved_natively(tmp_path: Path) -> None:
    write_reference_image(tmp_path, "title.png")
    path = write_scenario(
        tmp_path,
        """
start_condition:
  type: detected
  minimum_score: 0.8
  detector: &title
    type: template_match
    reference: ./title.png

reset_condition:
  type: detected
  minimum_score: 0.8
  detector: *title

splits:
  - rules:
      - condition:
          type: detected
          minimum_score: 0.9
          detector: *title
        action: split
""",
    )

    scenario = load_scenario_yaml(path)

    rules = scenario.splits[0]
    assert rules is not None
    reset_condition = scenario.reset_condition
    assert isinstance(reset_condition, Detected)
    assert isinstance(rules[0].condition, Detected)
    reset_detector = reset_condition.detector
    split_detector = rules[0].condition.detector
    assert isinstance(split_detector, TemplateMatchDetector)
    assert split_detector == reset_detector


def test_unsupported_condition_type_is_rejected_clearly(tmp_path: Path) -> None:
    path = write_scenario(
        tmp_path,
        """
start_condition:
  type: elapsed
  duration: 2s
reset_condition:
  type: elapsed
  duration: 2s
splits: []
""",
    )

    with pytest.raises(ScenarioYamlValidationError, match="elapsed.*not yet supported"):
        load_scenario_yaml(path)


def test_unsupported_detector_type_is_rejected_clearly(tmp_path: Path) -> None:
    path = write_scenario(
        tmp_path,
        """
start_condition:
  type: detected
  minimum_score: 0.8
  detector:
    type: mean_brightness
reset_condition:
  type: detected
  minimum_score: 0.8
  detector:
    type: mean_brightness
splits: []
""",
    )

    with pytest.raises(
        ScenarioYamlValidationError, match="mean_brightness.*not yet supported"
    ):
        load_scenario_yaml(path)


def test_unknown_condition_type_is_rejected(tmp_path: Path) -> None:
    path = write_scenario(
        tmp_path,
        """
start_condition:
  type: mystery
reset_condition:
  type: mystery
splits: []
""",
    )

    with pytest.raises(ScenarioYamlValidationError, match="unsupported condition type"):
        load_scenario_yaml(path)


def test_invalid_duration_is_rejected(tmp_path: Path) -> None:
    path = write_scenario(
        tmp_path,
        """
start_condition:
  type: then
  within: 3hours
  conditions: []
reset_condition:
  type: then
  within: 3hours
  conditions: []
splits: []
""",
    )

    with pytest.raises(ScenarioYamlValidationError, match="must be a duration"):
        load_scenario_yaml(path)


def test_invalid_yaml_is_reported_as_file_error(tmp_path: Path) -> None:
    path = write_scenario(tmp_path, "reset_conditions: [unclosed\n")

    with pytest.raises(ScenarioYamlError):
        load_scenario_yaml(path)
