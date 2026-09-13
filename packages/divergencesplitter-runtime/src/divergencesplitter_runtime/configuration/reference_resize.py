"""Apply the opt-in reference resize before starting scenario evaluation."""

from copy import deepcopy
from dataclasses import replace

import numpy as np
from divergencesplitter import (
    Condition,
    Detected,
    Frame,
    MonotonicTime,
    Rule,
    RuleSequence,
    Scenario,
)
from divergencesplitter.detector import (
    DifferenceHashSimilarityDetector,
    HistogramSimilarityDetector,
    MeanAbsoluteSimilarityDetector,
    PerceptualHashSimilarityDetector,
    PhaseCorrelationDetector,
    RootMeanSquareSimilarityDetector,
    TemplateMatchDetector,
)
from divergencesplitter.detector.models import freeze_config_image
from divergencesplitter.frame.normalizer import (
    FrameNormalizationError,
    FrameNormalizer,
    OutputSize,
)

from divergencesplitter_runtime.configuration.models import SourceTransformConfiguration


def resize_scenario_references(
    scenario: Scenario, transform: SourceTransformConfiguration
) -> Scenario:
    """Copy a scenario with rebuilt references; preserve shared condition identity.

    Reference images already describe the comparison region, so capture crop
    margins are not applied again. ROI coordinates remain in output-frame pixels.
    """
    resize = transform.resize
    if resize is None or not resize.resize_references:
        return scenario
    memo: dict[int, object] = {}
    seen: set[int] = set()

    def visit(condition: Condition) -> None:
        if id(condition) in seen:
            return
        seen.add(id(condition))
        if isinstance(condition, Detected):
            detector = condition.detector
            if id(detector) not in memo:
                if isinstance(
                    detector,
                    (
                        DifferenceHashSimilarityDetector,
                        HistogramSimilarityDetector,
                        MeanAbsoluteSimilarityDetector,
                        PerceptualHashSimilarityDetector,
                        PhaseCorrelationDetector,
                        RootMeanSquareSimilarityDetector,
                        TemplateMatchDetector,
                    ),
                ):
                    config = detector.config
                    size = (
                        resize.to_output_size()
                        if config.roi is None
                        else OutputSize(config.roi.width, config.roi.height)
                    )
                    image = np.asarray(config.reference)
                    # Frozen tuples lose numpy dtype; preserve 8-bit image rounding.
                    if np.all((image >= 0) & (image <= 255)) and np.all(
                        image == np.floor(image)
                    ):
                        image = image.astype(np.uint8)
                    else:
                        image = image.astype(np.float64)
                    normalized = FrameNormalizer(
                        output_size=size, resize_interpolation=resize.interpolation
                    ).normalize(Frame(image, MonotonicTime(0)))
                    if isinstance(normalized, FrameNormalizationError):
                        raise ValueError(normalized.message)  # noqa: TRY004
                    reference = freeze_config_image(normalized.image.tolist())
                    if isinstance(detector, DifferenceHashSimilarityDetector):
                        memo[id(detector)] = DifferenceHashSimilarityDetector(
                            replace(detector.config, reference=reference)
                        )
                    if isinstance(detector, HistogramSimilarityDetector):
                        memo[id(detector)] = HistogramSimilarityDetector(
                            replace(detector.config, reference=reference)
                        )
                    if isinstance(detector, MeanAbsoluteSimilarityDetector):
                        memo[id(detector)] = MeanAbsoluteSimilarityDetector(
                            replace(detector.config, reference=reference)
                        )
                    if isinstance(detector, PerceptualHashSimilarityDetector):
                        memo[id(detector)] = PerceptualHashSimilarityDetector(
                            replace(detector.config, reference=reference)
                        )
                    if isinstance(detector, PhaseCorrelationDetector):
                        memo[id(detector)] = PhaseCorrelationDetector(
                            replace(detector.config, reference=reference)
                        )
                    if isinstance(detector, RootMeanSquareSimilarityDetector):
                        memo[id(detector)] = RootMeanSquareSimilarityDetector(
                            replace(detector.config, reference=reference)
                        )
                    if isinstance(detector, TemplateMatchDetector):
                        memo[id(detector)] = TemplateMatchDetector(
                            replace(detector.config, reference=reference)
                        )
                else:
                    memo[id(detector)] = detector
        for child in condition.children:
            visit(child)

    visit(scenario.start_condition)
    for condition in (scenario.reset_condition, scenario.incomplete_condition):
        if condition is not None:
            visit(condition)
    for rules in scenario.splits:
        for rule in rules or ():
            if isinstance(rule, RuleSequence):
                for step in rule.rules:
                    visit(step.condition)
            elif isinstance(rule, Rule):
                visit(rule.condition)
    return deepcopy(scenario, memo)
