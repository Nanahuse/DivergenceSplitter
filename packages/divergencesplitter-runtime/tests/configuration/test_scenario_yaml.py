import textwrap
from pathlib import Path

import cv2
import numpy as np
import pytest
from divergencesplitter import (
    All,
    Any,
    ColorRangeDetector,
    Condition,
    Detected,
    DifferenceHashSimilarityDetector,
    Elapsed,
    FallingEdge,
    Frame,
    FrameContext,
    Hold,
    MeanAbsoluteSimilarityDetector,
    MeanBrightnessDetector,
    MonotonicTime,
    Not,
    Nth,
    Once,
    PhaseCorrelationDetector,
    Region,
    ResetWhen,
    RisingEdge,
    RootMeanSquareSimilarityDetector,
    TemplateMatchDetector,
    Then,
)
from divergencesplitter.detector import ImageDetector
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


def make_context(nanoseconds: int = 0) -> FrameContext:
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    return FrameContext(
        frame=Frame(image=image, captured_at=MonotonicTime(nanoseconds)),
        now=MonotonicTime(nanoseconds),
    )


def load_condition(directory: Path, condition_yaml: str) -> Condition:
    write_reference_image(directory, "title.png")
    path = write_scenario(
        directory,
        f"""
start_condition:
{textwrap.indent(condition_yaml.strip(), "  ")}
reset_condition:
  type: detected
  minimum_score: 0.5
  detector: {{type: template_match, reference: ./title.png}}
splits: []
""",
    )
    return load_scenario_yaml(path).start_condition


def load_detector(directory: Path, detector_yaml: str) -> ImageDetector:
    write_reference_image(directory, "title.png")
    path = write_scenario(
        directory,
        f"""
start_condition:
  type: detected
  minimum_score: 0.5
  detector:
{textwrap.indent(detector_yaml.strip(), "    ")}
reset_condition:
  type: detected
  minimum_score: 0.5
  detector: {{type: template_match, reference: ./title.png}}
splits: []
""",
    )
    condition = load_scenario_yaml(path).start_condition
    assert isinstance(condition, Detected)
    return condition.detector


@pytest.mark.parametrize("within", ["500ms", "2s", "1.5s"])
def test_duration_expressions_work_through_scenario_behavior(
    tmp_path: Path, within: str
) -> None:
    write_reference_image(tmp_path, "title.png")
    path = write_scenario(
        tmp_path,
        f"""
start_condition:
  type: then
  within: {within}
  conditions:
    - type: detected
      minimum_score: 0.8
      detector:
        type: template_match
        reference: ./title.png
    - type: detected
      minimum_score: 0.8
      detector:
        type: template_match
        reference: ./title.png
reset_condition:
  type: then
  within: {within}
  conditions:
    - type: detected
      minimum_score: 0.8
      detector:
        type: template_match
        reference: ./title.png
    - type: detected
      minimum_score: 0.8
      detector:
        type: template_match
        reference: ./title.png
splits: []
""",
    )

    scenario = load_scenario_yaml(path)
    assert isinstance(scenario.start_condition, Then)
    image = cv2.imread(str(tmp_path / "title.png"))
    assert image is not None
    first = Frame(image=image, captured_at=MonotonicTime(0))
    assert (
        scenario.start_condition.evaluate(FrameContext(first, MonotonicTime(0)))
        is False
    )
    expected_ns = {"500ms": 500_000_000, "2s": 2_000_000_000, "1.5s": 1_500_000_000}[
        within
    ]
    second = Frame(image=image, captured_at=MonotonicTime(expected_ns))
    assert (
        scenario.start_condition.evaluate(
            FrameContext(second, MonotonicTime(expected_ns))
        )
        is True
    )


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


def test_loads_all_condition(tmp_path: Path) -> None:
    condition = load_condition(
        tmp_path,
        """
type: all
conditions:
  - type: detected
    minimum_score: 0.9
    detector: {type: template_match, reference: ./title.png}
  - type: detected
    minimum_score: 0.8
    detector: {type: template_match, reference: ./title.png}
""",
    )

    assert isinstance(condition, All)
    assert len(condition.children) == 2
    assert all(isinstance(child, Detected) for child in condition.children)


def test_loads_any_condition(tmp_path: Path) -> None:
    condition = load_condition(
        tmp_path,
        """
type: any
conditions:
  - type: elapsed
    duration: 1s
  - type: elapsed
    duration: 2s
""",
    )

    assert isinstance(condition, Any)
    assert len(condition.children) == 2
    assert all(isinstance(child, Elapsed) for child in condition.children)


def test_loads_not_condition(tmp_path: Path) -> None:
    condition = load_condition(
        tmp_path,
        """
type: not
condition:
  type: elapsed
  duration: 1s
""",
    )

    assert isinstance(condition, Not)
    assert len(condition.children) == 1
    assert isinstance(condition.children[0], Elapsed)


def test_loads_rising_edge_condition(tmp_path: Path) -> None:
    condition = load_condition(
        tmp_path,
        """
type: rising_edge
condition:
  type: elapsed
  duration: 100ms
""",
    )

    assert isinstance(condition, RisingEdge)
    assert isinstance(condition.children[0], Elapsed)
    assert condition.evaluate(make_context(0)) is False
    assert condition.evaluate(make_context(100_000_000)) is True


def test_loads_falling_edge_condition(tmp_path: Path) -> None:
    write_reference_image(tmp_path, "a.png")
    condition = load_condition(
        tmp_path,
        """
type: falling_edge
condition:
  type: detected
  minimum_score: 0.95
  detector:
    type: template_match
    reference: ./a.png
""",
    )

    assert isinstance(condition, FallingEdge)
    assert isinstance(condition.children[0], Detected)


def test_loads_once_condition(tmp_path: Path) -> None:
    condition = load_condition(
        tmp_path,
        """
type: once
condition:
  type: elapsed
  duration: 0s
""",
    )

    assert isinstance(condition, Once)
    assert isinstance(condition.children[0], Elapsed)


def test_loads_elapsed_condition_with_duration(tmp_path: Path) -> None:
    condition = load_condition(
        tmp_path,
        """
type: elapsed
duration: 3s
""",
    )

    assert isinstance(condition, Elapsed)
    assert condition.evaluate(make_context(0)) is False
    assert condition.evaluate(make_context(2_999_999_999)) is False
    assert condition.evaluate(make_context(3_000_000_000)) is True


def test_loads_hold_condition_requires_continuous_truth(tmp_path: Path) -> None:
    condition = load_condition(
        tmp_path,
        """
type: hold
duration: 500ms
condition:
  type: elapsed
  duration: 0s
""",
    )

    assert isinstance(condition, Hold)
    assert isinstance(condition.children[0], Elapsed)
    assert condition.evaluate(make_context(0)) is False
    assert condition.evaluate(make_context(499_999_999)) is False
    assert condition.evaluate(make_context(500_000_000)) is True


def test_loads_nth_condition_and_counts(tmp_path: Path) -> None:
    condition = load_condition(
        tmp_path,
        """
type: nth
count: 3
condition:
  type: elapsed
  duration: 0s
""",
    )

    assert isinstance(condition, Nth)
    assert isinstance(condition.children[0], Elapsed)
    assert condition.evaluate(make_context(0)) is False
    assert condition.evaluate(make_context(0)) is False
    assert condition.evaluate(make_context(0)) is True


def test_loads_reset_when_condition(tmp_path: Path) -> None:
    condition = load_condition(
        tmp_path,
        """
type: reset_when
condition:
  type: once
  condition:
    type: elapsed
    duration: 0s
reset_condition:
  type: elapsed
  duration: 100ms
""",
    )

    assert isinstance(condition, ResetWhen)
    assert len(condition.children) == 2
    assert isinstance(condition.children[0], Once)
    assert isinstance(condition.children[1], Elapsed)


def test_nested_conditions_are_parsed_recursively(tmp_path: Path) -> None:
    write_reference_image(tmp_path, "a.png")
    condition = load_condition(
        tmp_path,
        """
type: all
conditions:
  - type: falling_edge
    condition:
      type: detected
      minimum_score: 0.95
      detector:
        type: template_match
        reference: ./a.png
  - type: not
    condition:
      type: elapsed
      duration: 2s
""",
    )

    assert isinstance(condition, All)
    first, second = condition.children
    assert isinstance(first, FallingEdge)
    assert isinstance(first.children[0], Detected)
    assert isinstance(second, Not)
    assert isinstance(second.children[0], Elapsed)


def test_loads_color_range_detector(tmp_path: Path) -> None:
    detector = load_detector(
        tmp_path,
        """
type: color_range
lower: [10, 20, 30]
upper: [40, 50, 60]
""",
    )

    assert isinstance(detector, ColorRangeDetector)
    assert detector.config.lower == (10, 20, 30)
    assert detector.config.upper == (40, 50, 60)
    assert detector.config.roi is None


def test_loads_color_range_detector_with_single_channel_and_roi(
    tmp_path: Path,
) -> None:
    detector = load_detector(
        tmp_path,
        """
type: color_range
lower: [0]
upper: [255]
roi: {x: 1, y: 2, width: 3, height: 4}
""",
    )

    assert isinstance(detector, ColorRangeDetector)
    assert detector.config.roi == Region(1, 2, 3, 4)


def test_loads_difference_hash_detector(tmp_path: Path) -> None:
    detector = load_detector(
        tmp_path,
        """
type: difference_hash_similarity
reference: ./title.png
hash_size: 4
""",
    )

    assert isinstance(detector, DifferenceHashSimilarityDetector)
    assert detector.config.hash_size == 4


def test_difference_hash_hash_size_defaults_to_core_default(tmp_path: Path) -> None:
    detector = load_detector(
        tmp_path,
        """
type: difference_hash_similarity
reference: ./title.png
""",
    )

    assert isinstance(detector, DifferenceHashSimilarityDetector)
    assert detector.config.hash_size == 8


def test_loads_mean_absolute_similarity_detector(tmp_path: Path) -> None:
    detector = load_detector(
        tmp_path,
        """
type: mean_absolute_similarity
reference: ./title.png
roi: {x: 0, y: 0, width: 2, height: 2}
""",
    )

    assert isinstance(detector, MeanAbsoluteSimilarityDetector)
    assert detector.config.roi == Region(0, 0, 2, 2)


def test_loads_phase_correlation_detector(tmp_path: Path) -> None:
    detector = load_detector(
        tmp_path,
        """
type: phase_correlation
reference: ./title.png
""",
    )

    assert isinstance(detector, PhaseCorrelationDetector)


def test_loads_root_mean_square_similarity_detector(tmp_path: Path) -> None:
    detector = load_detector(
        tmp_path,
        """
type: root_mean_square_similarity
reference: ./title.png
""",
    )

    assert isinstance(detector, RootMeanSquareSimilarityDetector)


def test_loads_mean_brightness_detector_without_config(tmp_path: Path) -> None:
    detector = load_detector(
        tmp_path,
        """
type: mean_brightness
""",
    )

    assert isinstance(detector, MeanBrightnessDetector)
    assert detector.roi is None


def test_loads_mean_brightness_detector_with_roi(tmp_path: Path) -> None:
    detector = load_detector(
        tmp_path,
        """
type: mean_brightness
roi: {x: 5, y: 6, width: 7, height: 8}
""",
    )

    assert isinstance(detector, MeanBrightnessDetector)
    assert detector.roi == Region(5, 6, 7, 8)


def test_reference_image_absolute_path_is_accepted(tmp_path: Path) -> None:
    image_path = write_reference_image(tmp_path, "absolute.png")
    detector = load_detector(
        tmp_path,
        f"""
type: mean_absolute_similarity
reference: {image_path.as_posix()}
""",
    )

    assert isinstance(detector, MeanAbsoluteSimilarityDetector)


def test_unreadable_reference_image_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScenarioYamlValidationError, match="could not be read"):
        load_detector(
            tmp_path,
            """
type: mean_absolute_similarity
reference: ./missing.png
""",
        )


def test_invalid_roi_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScenarioYamlValidationError):
        load_detector(
            tmp_path,
            """
type: mean_brightness
roi: {x: -1, y: 0, width: 2, height: 2}
""",
        )


def test_unknown_detector_type_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScenarioYamlValidationError, match="unsupported detector type"):
        load_detector(tmp_path, "type: mystery\n")


def test_missing_required_condition_field_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScenarioYamlValidationError, match="missing scenario fields"):
        load_condition(
            tmp_path,
            """
type: all
""",
        )


def test_unknown_condition_field_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScenarioYamlValidationError, match="unknown scenario fields"):
        load_condition(
            tmp_path,
            """
type: elapsed
duration: 1s
unexpected: true
""",
        )


def test_non_list_conditions_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScenarioYamlValidationError, match="must be a list"):
        load_condition(
            tmp_path,
            """
type: all
conditions: {}
""",
        )


def test_non_mapping_condition_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScenarioYamlValidationError, match="must be a mapping"):
        load_condition(
            tmp_path,
            """
type: not
condition: []
""",
        )


def test_boolean_minimum_score_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScenarioYamlValidationError, match="must be a number"):
        load_condition(
            tmp_path,
            """
type: detected
minimum_score: true
detector: {type: template_match, reference: ./title.png}
""",
        )


def test_boolean_nth_count_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScenarioYamlValidationError, match="must be an integer"):
        load_condition(
            tmp_path,
            """
type: nth
count: true
condition:
  type: elapsed
  duration: 0s
""",
        )


def test_non_integer_hash_size_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScenarioYamlValidationError, match="must be an integer"):
        load_detector(
            tmp_path,
            """
type: difference_hash_similarity
reference: ./title.png
hash_size: small
""",
        )


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
