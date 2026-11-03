# Condition reference

[日本語](conditions.md) | [English (Translation)](conditions.en.md)

This is an English translation. The Japanese version is the original and takes priority if there are differences.

[Scenario authoring](README.en.md) · [YAML lifecycle](yaml-reference.en.md#state-and-reset-lifecycle)

Every condition is a mapping with a required `type`. The following twelve types
are the complete public set. Fields listed below are required unless described as
optional. `condition` is a single child mapping; `conditions` is an ordered list
of child mappings. Unknown fields are rejected.

## Time, counts, and state

Time conditions use the application's elapsed time when a video frame is evaluated, not LiveSplit's real time, game time, or a frame count. Pausing the timer or losing frames does not stop that clock; a time condition can become true on the next frame evaluation. No result is updated until a frame is evaluated. `hold` checks continuity only on frames that are evaluated.

When conditions are combined, timing and counting can progress while another condition is false. If an `nth` count or an edge transition occurs while another required condition is false, the combined condition may never become true. Use [`then`](#then) to require conditions in sequence.

## detected

```yaml
type: detected
minimum_score: 0.9
detector: {type: mean_brightness}
```

`minimum_score` must be a finite number and `detector` must be a detector mapping; both are required. True when the score is at least `minimum_score`, including equality. Thresholds are not restricted to a range, but every supported detector returns a score in `[0, 1]`. A threshold above 1 cannot match; 0 matches every valid score.

Diagnostics shows the latest score and maximum score since reset. Reset clears both. A detector failure produces `error` and increases the rule error count; it is distinct from a false result.

## all

```yaml
type: all
conditions:
  - {type: elapsed, duration: 1s}
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

Required: `conditions`. True when every specified condition is true. An empty list is also true. Reset clears the state of every specified condition.

## any

```yaml
type: any
conditions:
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
  - {type: elapsed, duration: 10s}
```

Required: `conditions`. True when at least one specified condition is true. An empty list is false. Reset clears the state of every specified condition.

## not

```yaml
type: not
condition: {type: detected, minimum_score: 0.1, detector: {type: mean_brightness}}
```

Required: `condition`. True when the specified condition is false, and false when it is true. Reset also clears that condition's state.

## rising_edge and falling_edge

```yaml
type: rising_edge
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

Both require `condition`. `rising_edge` becomes true when the condition changes from false to true; `falling_edge` becomes true when it changes from true to false. The first evaluation after loading or reset establishes a baseline and returns false. An initially true condition does not trigger `rising_edge`, and an initially false condition does not trigger `falling_edge`.

Only the evaluation that detects the change is true; the result does not stay true. Reset clears the transition history and the specified condition's state. For the falling variant, use `type: falling_edge` with the same fields.

## once

```yaml
type: once
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

Required: `condition`. Once the specified condition first becomes true, the result stays true until reset. This is not a one-frame pulse. Later changes to the specified condition do not change the result.

Reset clears the recorded success and the specified condition's state.

## elapsed

```yaml
type: elapsed
duration: 3s
```

Required: `duration` ([duration syntax](yaml-reference.en.md#durations)). Timing starts when this condition is first evaluated after loading or reset. Loading a file, Apply, timer start, or entering a segment does not itself start the clock. These events coincide with the start only if the first evaluation happens then.

True once elapsed time is at least `duration`, and stays true until reset. `0s` is true on the first evaluation. Reset restarts timing and clears the displayed elapsed time.

## hold

```yaml
type: hold
duration: 500ms
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

Required: `duration`, `condition`. Timing starts when the specified condition first becomes true. True when all subsequently evaluated values remain true for at least `duration`. Any false value restarts timing; the next true value starts a new interval.

A later false value makes the result false even after success. `0ms` follows the specified condition's result. Reset clears timing and displayed progress, and resets the specified condition.

## nth

```yaml
type: nth
count: 3
condition:
  type: rising_edge
  condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

`count` must be an integer of at least 1 and `condition` must be a condition mapping; both are required. Counts each evaluation where the specified condition is true, including consecutive true frames. A false value does not clear the count. True only on the `count`-th occurrence, then false until reset.

Use `rising_edge` as above to count image appearances. Reset clears the count, recorded success, and the specified condition's state.

## reset_when

```yaml
type: reset_when
condition:
  type: once
  condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
reset_condition:
  type: not
  condition: {type: detected, minimum_score: 0.1, detector: {type: mean_brightness}}
```

Required: `condition`, `reset_condition`. On a frame where `reset_condition` is true, both conditions reset before `condition` is evaluated. The result can therefore be true on that same frame if `condition` becomes true. Reset alone does not force a false result or delay evaluation until the next frame.

Resetting this condition also resets both specified conditions.

## then

```yaml
type: then
within: 5s
conditions:
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
  - {type: elapsed, duration: 1s}
```

Required: a non-empty `conditions` list. Conditions must become true in the listed order. A true result advances one step; the next step is first evaluated on a later frame. A false result waits at the current step. A one-condition list completes on that condition's first true result.

Optional: `within`, a time limit. Omit it for no deadline. With multiple steps, the limit starts when the first step succeeds and applies to all remaining steps together, not separately to each step. The next evaluation after elapsed time exceeds `within` restarts at the first step. If the first condition is true on that frame, progress resumes immediately. Equality is still within the limit.

Timeout restarts only the sequence; it does not reset the individual conditions. Previous `elapsed` timing, `once` success, and `nth` counts can therefore affect the next attempt.

The final step makes the result true, and it stays true until reset. Reset clears progress, timing, recorded completion, and every condition's state. The example's one-second interval begins when the second condition, `elapsed`, is first evaluated.

`then` checks a sequence of conditions for one action. Use [RuleSequence](yaml-reference.en.md#rules-and-sequences) to perform a separate action at each step.
