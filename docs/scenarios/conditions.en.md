# Condition reference

[日本語（正本）](conditions.md) | [English](conditions.en.md)

[Scenario authoring](README.en.md) · [YAML lifecycle](yaml-reference.en.md#state-and-reset-lifecycle)

Every condition is a mapping with a required `type`. The following twelve types
are the complete public set. Fields listed below are required unless described as
optional. `condition` is a single child mapping; `conditions` is an ordered list
of child mappings. Unknown fields are rejected.

## Evaluation and short-circuiting

`all` and `any` visit children in YAML order. Once their Boolean result is known,
they call remaining children in **short-circuit mode**. This is different from
not calling an inactive rule group at all:

| Type called in short-circuit mode | State behavior |
| --- | --- |
| `detected` | Does not run its detector or update latest/max scores. |
| `all`, `any`, `not` | Pass short-circuit mode to children. |
| `rising_edge`, `falling_edge`, `once`, `hold`, `nth` | Normally evaluate their child and update their own state, even though their own Boolean result is discarded. Completed `once`/`nth` mark the child skipped instead. |
| `elapsed` | Starts/advances its clock and completion state. |
| `reset_when` | Normally evaluates its reset condition, resets if needed, then short-circuits its main child. |
| `then` | Normally evaluates only its active child and advances progress/completion; other children are marked skipped without evaluation. |

The node's displayed status is `skipped`, but its descendants can show a normal
result. A skipped `nth` can reach its count without returning true to its parent.
A skipped edge can likewise record a transition without returning true to its
parent. Put stateful conditions deliberately in the list; do not assume
that a preceding false `all` child freezes later clocks or counters.

By contrast, `mark_skipped` (used for inactive `then` steps or completed wrappers)
only changes diagnostic statuses recursively and does not run children. Later
rules after the first action and inactive phase/split groups are not evaluated.

All time comparisons use monotonic application time sampled for the frame, not
LiveSplit time or a frame count. No new evaluation means no new result. A pause
or gap in frames does not freeze time; the next sample can satisfy an elapsed
duration. `hold` can only observe false values on evaluated frames.

## detected

```yaml
type: detected
minimum_score: 0.9
detector: {type: mean_brightness}
```

Required: `minimum_score` (finite number), `detector` (one detector mapping).
True when `score >= minimum_score`, including equality. The loader does not
restrict thresholds to `[0, 1]`, but every supported detector returns a score in
that range. A threshold above 1 cannot match; 0 matches every valid score.

Tracks latest and maximum score since reset. Reset clears both. Short-circuit
evaluation leaves them unchanged. Detector exceptions make the condition `error`
and the runtime counts a rule error rather than treating it as false.

## all

```yaml
type: all
conditions:
  - {type: elapsed, duration: 1s}
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

Required: `conditions`. True if every child is true. Evaluation is left to right;
after the first false, remaining children use short-circuit mode. An empty list
is true. No private state; reset recursively resets every child.

## any

```yaml
type: any
conditions:
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
  - {type: elapsed, duration: 10s}
```

Required: `conditions`. True if at least one child is true. After the first true,
remaining children use short-circuit mode. An empty list is false. No private
state; reset recursively resets every child.

## not

```yaml
type: not
condition: {type: detected, minimum_score: 0.1, detector: {type: mean_brightness}}
```

Required: `condition`. Negates its child's normal result. In short-circuit mode,
passes that mode to the child. No private state; reset resets its child.

## rising_edge and falling_edge

```yaml
type: rising_edge
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

Both require `condition`. `rising_edge` is true for a false → true transition;
`falling_edge` is true for true → false. The first evaluation only establishes a
baseline and returns false, even if the child is already true for a rising edge
or false for a falling edge. Each later evaluation records the child's current
value, including short-circuit evaluation. The result is a single evaluation
pulse, not a latch. Reset clears the previous-value baseline and resets the child.
To configure the falling variant, use `type: falling_edge` with the same fields.

## once

```yaml
type: once
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

Required: `condition`. Latches the first true child result and stays **true on
every subsequent evaluation** until reset. It does not produce a one-frame pulse.
After completion, the child is marked skipped and stops updating. Short-circuit
evaluation can complete the latch. Reset clears completion and resets the child.

## elapsed

```yaml
type: elapsed
duration: 3s
```

Required: `duration` ([duration syntax](yaml-reference.en.md#durations)). The clock
starts on its first evaluation after reset, including a short-circuit call. It
does not start at file load, Apply, timer start, or entry into a segment unless
that is also when this node is first evaluated. True once elapsed time is at
least the duration; it remains true until reset. `0s` is true on the first call.
Reset clears start time, completion, and elapsed progress.

## hold

```yaml
type: hold
duration: 500ms
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

Required: `duration`, `condition`. Starts timing at the first true child sample.
True when all subsequent observed samples stay true for at least the duration.
Any false sample clears the start time and returns false; the next true sample
begins a new interval. A completed hold is not latched: a later false makes it
false again. `0ms` follows the child immediately. Updates also occur in
short-circuit mode. Reset clears timing/progress and resets the child.

## nth

```yaml
type: nth
count: 3
condition:
  type: rising_edge
  condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

Required: `count` (integer at least 1), `condition`. Counts every true child
evaluation, including consecutive true frames and short-circuit calls. False
does not clear the count. It returns true only on the `count`-th true evaluation;
then it returns false and marks the child skipped until reset. Wrap a detection
in `rising_edge` as above to count appearances rather than frames. Reset clears
the observed count and completion flag and resets the child.

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

Required: `condition`, `reset_condition`. Evaluates the reset child **first** on
every call. If true, resets both children, including the reset condition itself.
Then evaluates the main condition on that same frame and returns its result.
Reset does not force a false result or skip a frame. In short-circuit mode the
reset child is still normal, then the main child uses short-circuit mode.
External reset also resets both children; there is no additional private state.

## then

```yaml
type: then
within: 5s
conditions:
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
  - {type: elapsed, duration: 1s}
```

Required: a non-empty `conditions` list. Optional: `within` (duration); omitted
means no deadline. Only the active step is evaluated. A true result advances
**one** step; the next step is first evaluated on a later frame. Previous and
future steps are marked skipped without running them. A false active step waits
at that step. A one-element list completes when that element first returns true.

For multiple steps, `within` starts when step 0 succeeds. It is a window for the
whole remaining sequence, not a separate timeout per step. Before each later
evaluation, elapsed time **greater than** the window restarts at step 0, which
can run again on that same frame. Equality is still within the window. A timeout
clears only step progress and the window start; it **does not reset child
state**, so a child's old `elapsed`, `once`, or `nth` state can affect a retry.

The last step makes `then` true, and it stays true on all later evaluations until
reset. Short-circuit calls can advance/complete it. Full reset clears position,
deadline start, completion, and every child. In the example, the 1s elapsed clock
starts when step 1 is first evaluated, not on step 0's success frame.

`then` combines observations into one condition for one action. A
[RuleSequence](yaml-reference.en.md#rules-and-sequences) instead emits one action per
rule and advances through those actions.
