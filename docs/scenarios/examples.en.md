# Scenario examples

[日本語](examples.md) | [English (Translation)](examples.en.md)

This is an English translation. The Japanese version is the original and takes priority if there are differences.

[Scenario authoring](README.en.md) · [YAML reference](yaml-reference.en.md)

Each YAML block below is a complete scenario. Save it as a `.yaml` file and use
its absolute path in a Profile. For image examples, copy the bundled
[`reference.ppm`](../../examples/reference.ppm) beside the YAML to try loading it,
then replace it with your game's reference and tune the threshold. The bundled
8×8 pattern demonstrates image loading; it is not a game-screen detector.
All examples need incoming frames and a ready Bridge connection to act.

## Image detection

Search for a template to start, then split when it disappears. After entering the
first segment, `falling_edge` must first observe the image present before it can
recognize its disappearance. Keep Profile's Resize reference images off for this
small search template.

```yaml
start_condition:
  type: detected
  minimum_score: 0.95
  detector:
    type: template_match
    reference: reference.ppm
splits:
  - rules:
      - condition:
          type: falling_edge
          condition:
            type: detected
            minimum_score: 0.95
            detector:
              type: template_match
              reference: reference.ppm
        action: split
```

The same scenario is available as
[`image-scenario.yaml`](../../examples/image-scenario.yaml). For a fixed-position
comparison, use a suitable ROI and matching-size reference with
`mean_absolute_similarity` instead; see [detector constraints](detectors.en.md).

## Wait for time

This is the [minimal scenario](../../examples/minimal-scenario.yaml) used in
Getting started. The first clock begins on the first Start evaluation; the split
clock begins when segment 0 is first evaluated.

```yaml
start_condition: {type: elapsed, duration: 2s}
splits:
  - rules:
      - condition: {type: elapsed, duration: 3s}
        action: split
```

## Sequential observations, one action

Start on a bright frame. In segment 0, observe a dark frame, then a bright frame
continuously for 500ms to Split. More than 10 seconds after the dark frame, the
sequence restarts at its first step. Timeout does not reset the individual
conditions; see [`then`](conditions.en.md#then) for details.

```yaml
start_condition:
  type: detected
  minimum_score: 0.8
  detector: {type: mean_brightness}
splits:
  - rules:
      - condition:
          type: then
          within: 10s
          conditions:
            - type: not
              condition:
                type: detected
                minimum_score: 0.1
                detector: {type: mean_brightness}
            - type: hold
              duration: 500ms
              condition:
                type: detected
                minimum_score: 0.8
                detector: {type: mean_brightness}
        action: split
```

## Multiple conditions

After an automatic start, Split when at least two seconds have elapsed from the
first evaluation in segment 0 and the image has remained mostly red for 300ms.
The 300ms interval can overlap the initial two-second wait; this does not require
an additional 300ms after those two seconds.

```yaml
start_condition: {type: elapsed, duration: 2s}
splits:
  - rules:
      - condition:
          type: all
          conditions:
            - {type: elapsed, duration: 2s}
            - type: hold
              duration: 300ms
              condition:
                type: detected
                minimum_score: 0.9
                detector:
                  type: color_range
                  lower: [0, 0, 180]
                  upper: [80, 80, 255]
        action: split
```

## Multiple actions

Pause after one second in segment 0, resume after two seconds of evaluating the
next sequence rule, and Split after a further second. Pause and Resume preserve
the active sequence when the phase transition is confirmed at the same index.
External resets, resynchronizations, or actions that move the segment can change
this progression; see [RuleSequence](yaml-reference.en.md#rules-and-sequences).

```yaml
start_condition: {type: elapsed, duration: 2s}
splits:
  - rules:
      - sequence:
          - condition: {type: elapsed, duration: 1s}
            action: pause
          - condition: {type: elapsed, duration: 2s}
            action: resume
          - condition: {type: elapsed, duration: 1s}
            action: split
```

## Inherit a condition and change the image per split

Each split detects a different image and then waits one second before splitting. The anchor holds the shared wait and detector settings. Each split overrides the reference image on the `course` condition.

```yaml
definitions:
  course_finish: &course_finish
    type: then
    conditions:
      - id: course
        type: detected
        minimum_score: 0.9
        detector:
          type: root_mean_square_similarity
          reference: assets/default.png
      - type: elapsed
        duration: 1s

start_condition: {type: elapsed, duration: 0s}

splits:
  - rules:
      - condition:
          extends: *course_finish
          overrides:
            course:
              detector:
                reference: assets/YI1.png
        action: split
  - rules:
      - condition:
          extends: *course_finish
          overrides:
            course:
              detector:
                reference: assets/DPC.png
        action: split
```

## Reuse with anchors; count appearances

Reuse a bright condition and count three rising edges in segment 0. Consecutive
bright frames count only once because `rising_edge` supplies pulses to `nth`.
The first post-reset edge sample establishes its baseline. An unused root key
defines the anchor; aliases create independent condition state at each use site.

```yaml
bright: &bright
  type: detected
  minimum_score: 0.8
  detector: {type: mean_brightness}
start_condition: *bright
splits:
  - rules:
      - condition:
          type: nth
          count: 3
          condition:
            type: rising_edge
            condition: *bright
        action: split
  - null
```

This last example needs at least two LiveSplit segments. Its second segment is
manual. For Reset and incorrect-final-split recovery, add `reset_condition` or
`incomplete_condition` using the [root schema](yaml-reference.en.md#scenario-structure).
