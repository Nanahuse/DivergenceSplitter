# Scenario authoring

[日本語](README.md) | [English (Translation)](README.en.md)

This is an English translation. The Japanese version is the original and takes priority if there are differences.

[Documentation home](../../README.en.md)

A scenario is a `.yaml` or `.yml` file that defines automatic timer controls. It specifies when to Start and when each LiveSplit segment should Split or perform another action. Optional conditions can Reset a run or undo its final split after it ends.

A Profile combines the file with a video input and the Bridge port for LiveSplit on the same PC. Scenario settings use these terms:

| Term | Meaning |
| --- | --- |
| Detector | An image-analysis method that returns a score, such as similarity or brightness. |
| Condition | A test that becomes true based on scores, elapsed time, counts, or other conditions. |
| Action | A control sent to LiveSplit, such as Start, Split, or Reset. |
| Rule | A condition paired with an action; when the condition is true, the action is requested. |

1. Try the [minimal scenario](../../examples/minimal-scenario.yaml) using
   [Getting started](../getting-started.en.md).
2. Read the [YAML reference](yaml-reference.en.md) for structure, actions, evaluation
   order, paths, anchors, and runtime resets.
3. Choose a [detector](detectors.en.md), then wrap it in `detected` and any needed
   [conditions](conditions.en.md).
4. Adapt [examples](examples.en.md), Apply, and inspect scores in
   [Diagnostics](../user-guide.en.md#diagnostics).

Keep the coordinate system stable: input Crop/Resize runs before detector ROI.
Reference-image resizing is a separate Profile option; see
[configuration](../configuration.en.md#crop-resize-and-reference-images).

Scenarios are evaluated only when normalized frames arrive and the instance has
a valid Bridge state. See [conditions](conditions.en.md#time-counts-and-state)
for timing and input behavior.

Developers working on settings or verification can consult the
[loader](../../src/core/scenario_loader.cpp) and [test instructions (Japanese)](../development/testing.md).
