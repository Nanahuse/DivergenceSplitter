from dataclasses import replace

import cv2
import numpy as np
import pytest
from divergencesplitter import (
    Action,
    All,
    Detected,
    Frame,
    FrameContext,
    MonotonicTime,
    Rule,
    RuleSequence,
    Scenario,
)
from divergencesplitter.detector import (
    MeanAbsoluteSimilarityConfig,
    MeanAbsoluteSimilarityDetector,
    RootMeanSquareSimilarityConfig,
    RootMeanSquareSimilarityDetector,
)
from divergencesplitter.detector.models import freeze_config_image
from divergencesplitter.frame.normalizer import ResizeInterpolation
from divergencesplitter_runtime.configuration.models import (
    ResizeConfiguration,
    SourceTransformConfiguration,
)
from divergencesplitter_runtime.configuration.reference_resize import (
    resize_scenario_references,
)


@pytest.mark.parametrize(
    "interpolation,cv_interpolation",
    [
        (ResizeInterpolation.AREA, cv2.INTER_AREA),
        (ResizeInterpolation.NEAREST, cv2.INTER_NEAREST),
        (ResizeInterpolation.LINEAR, cv2.INTER_LINEAR),
        (ResizeInterpolation.CUBIC, cv2.INTER_CUBIC),
        (ResizeInterpolation.LANCZOS4, cv2.INTER_LANCZOS4),
    ],
)
@pytest.mark.parametrize(
    "detector_type,config_type",
    [
        (RootMeanSquareSimilarityDetector, RootMeanSquareSimilarityConfig),
        (MeanAbsoluteSimilarityDetector, MeanAbsoluteSimilarityConfig),
    ],
)
def test_reference_resize_prevents_shape_mismatch_and_preserves_shared_conditions(
    interpolation, cv_interpolation, detector_type, config_type
):
    image = np.arange(16 * 12 * 3, dtype=np.uint8).reshape(12, 16, 3)
    condition = Detected(
        detector_type(config_type(freeze_config_image(image.tolist()))), 0.99
    )
    scenario = Scenario(
        All(condition),
        condition,
        condition,
        ((RuleSequence(Rule(condition, Action("split"))),),),
    )
    frame = Frame(
        cv2.resize(image, (8, 6), interpolation=cv_interpolation), MonotonicTime(0)
    )
    with pytest.raises(ValueError, match="shape mismatch"):
        condition.evaluate(FrameContext(frame, MonotonicTime(0)))
    condition.reset()
    transform = SourceTransformConfiguration(
        resize=ResizeConfiguration(8, 6, interpolation, True)
    )
    resized = resize_scenario_references(scenario, transform)
    assert resized.start_condition.evaluate(FrameContext(frame, MonotonicTime(0)))
    child = resized.start_condition.children[0]
    assert child is resized.reset_condition is resized.incomplete_condition
    assert isinstance(child, Detected)
    assert np.asarray(child.detector.reference_images[0].image).shape == (6, 8, 3)
    rules = resized.splits[0]
    assert rules is not None and isinstance(rules[0], RuleSequence)
    assert rules[0].rules[0].condition is child
    assert np.asarray(condition.detector.reference_images[0].image).shape == image.shape
    assert condition.status is None
    assert transform.resize is not None
    assert (
        resize_scenario_references(
            scenario,
            replace(
                transform, resize=replace(transform.resize, resize_references=False)
            ),
        )
        is scenario
    )
