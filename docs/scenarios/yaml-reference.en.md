# YAML reference

[日本語](yaml-reference.md) | [English (Translation)](yaml-reference.en.md)

This is an English translation. The Japanese version is the original and takes priority if there are differences.

[Scenario authoring](README.en.md) · [Conditions](conditions.en.md) · [Detectors](detectors.en.md) · [Examples](examples.en.md)

## Scenario structure

```yaml
start_condition:
  type: elapsed
  duration: 2s
reset_condition: null
incomplete_condition: null
splits:
  - rules:
      - condition: {type: elapsed, duration: 3s}
        action: split
  - null
```

| Root field | Required | Meaning |
| --- | --- | --- |
| `start_condition` | Yes | Condition that requests `start` while the timer is not running. |
| `splits` | Yes | Ordered list. Item 0 configures LiveSplit segment index 0, item 1 index 1, and so on. An empty list is accepted. |
| `reset_condition` | No | Condition that requests `reset` while running or paused. Omitted or `null` disables it. |
| `incomplete_condition` | No | Condition that requests `undo` after the run has ended, for example to undo an incorrect final split. Omitted or `null` disables it. |

Each split item is either `null` (manual segment, no automatic rule) or a mapping
containing only `rules`, an ordered list of rules/sequences. `rules: []` also has
no automatic rule. A null item does not automatically send Skip. A shorter list
leaves later LiveSplit segments without configured rules; a longer list disables
scenario evaluation. An empty stopped LiveSplit run is temporarily allowed, but
the count is validated again when its state changes.

Condition and detector `type` values and action names are case-sensitive. Unknown
fields are rejected in split, rule, condition, detector, and ROI mappings. The
root mapping allows extra keys so that you can define anchors or metadata; those
keys do not add behavior. A typo in an optional root key can therefore be ignored.
Required fields must still be present with the right structure.

## Rules and sequences

A rule has exactly `condition` (one condition mapping) and `action` (one scalar
operation name). A true condition requests that action. Rules in a split are
tried in list order. Evaluation stops at the first rule that returns an action;
later rules are not evaluated on that frame. Rule evaluation exceptions are
counted and the next rule is tried.
A plain rule is not automatically one-shot.

For multiple ordered actions, use a `sequence` containing a non-empty list of
plain rules. Nested sequences and action arrays are not supported:

```yaml
sequence:
  - condition: {type: elapsed, duration: 1s}
    action: pause
  - condition: {type: elapsed, duration: 2s}
    action: resume
  - condition: {type: elapsed, duration: 1s}
    action: split
```

This mapping occupies one item of a split's `rules` list. It is a **RuleSequence**:
only its active rule is evaluated, and returning an action advances it by one
step. The next rule starts on a later evaluation, not on the same frame. Completed
sequences return no action until reset. Advancement occurs when the rule produces
an action, not as a transaction after Bridge confirms all steps. Dispatch failure,
resynchronization, and segment changes can reset the containing group.

Put actions that leave the current segment (Split, Skip, Undo, Reset) last if later
steps depend on staying in that segment. Pause/Resume transitions at the same
segment normally preserve sequence position. For sequential observations followed
by **one** action, use [`then`](conditions.en.md#then); it is a condition, not a
RuleSequence.

## Actions

These are the complete action names. They send the corresponding Bridge timer
control; whether a control is valid depends on LiveSplit's current state.

| `action` | Effect |
| --- | --- |
| `start` | Start a stopped timer. This is also the implicit action for `start_condition`. |
| `split` | Complete the current segment; completing the final segment ends the run. |
| `skip` | Skip the current segment. |
| `undo` | Undo the previous split; after the run ends, return to its last segment. This is the implicit action for `incomplete_condition`. |
| `reset` | Reset the timer to not running. This is the implicit action for `reset_condition`. |
| `pause` | Pause the timer. |
| `resume` | Resume a paused timer. |

There are no action arguments, delays, scripts, or game-time operations in this
schema. Express waits using conditions; the application-wide Reaction time is
described in [Settings](../user-guide.en.md#settings).

## Evaluation order

When frames arrive and the timer state is synchronized with Bridge:

| Timer phase | Evaluated group |
| --- | --- |
| Not running | `start_condition` only. |
| Running or paused | `reset_condition` first, then rules for the current split index if Reset did not fire. |
| Ended | `incomplete_condition` only. |

Paused timers still evaluate time conditions and rules for the current segment.
Pausing the timer does not stop condition timing. Groups outside the current
phase are not evaluated.

### Pending actions and confirmation

While an action is waiting to be sent or confirmed, no other normal action starts. Normal actions and Reset have separate confirmation waits. While Running or Paused, however, `reset_condition` is still checked during a normal action's reaction delay and while a sent Split/Skip awaits confirmation. A pending Reset prevents new actions.

Manual Reset and an automatic Reset that becomes true during a normal action's reaction delay are sent without an additional delay. They cancel the unsent normal action. Other automatic actions use the configured Reaction time. If received timer information shows no change, the reaction wait continues.

After Bridge accepts an action, the application waits up to one second for the corresponding timer state change. Pause/Resume alone does not confirm Split/Skip, and a late Split does not confirm Reset. Receiving timer information without the required state change does not end the wait.

The second starts when Bridge accepts the action and continues even if video input stops. At expiry, the application checks the timer again, ends the wait for an unconfirmed action, and resets the corresponding rule group. A new automatic action requires evaluation of a new frame. This wait is separate from communication response timeouts and condition `elapsed` timing.

A rejected Reset also causes the timer to be checked again and the groups listed below to reset. Cancelling Reset before sending it preserves any confirmation wait for a normal action already sent. If timer state cannot be checked, evaluation stops while the connection recovers. See [troubleshooting](../troubleshooting.en.md#control-confirmation-and-reset-failures) for screen checks and [architecture (Japanese)](../development/architecture.md#bridgeとタイマー制御) for the communication design.

## State and reset lifecycle

Condition state is independent for each Profile instance and each configured
occurrence. Reusing an anchor does not share timing or counts. Reset clears the
condition and all conditions combined within it, returning their displayed status
to `not_evaluated`. See [conditions](conditions.en.md) for each type's behavior.

Condition timing, counts, and sequence progress reset at these points:

| Event | Reset behavior |
| --- | --- |
| New session / initial Bridge baseline / reconnect | All groups start fresh. |
| Transition to Not running, or an update to the LiveSplit run / segment count | All groups reset. |
| Move to another running/paused segment, including Undo | The destination segment's rules reset. |
| Transition to Ended | The Incomplete group resets. |
| Return from Ended to Running/Paused | Incomplete and Reset groups reset, and the destination segment resets. |
| Pause ↔ Resume at the same index | The split group normally retains its condition/sequence state. |
| Timer information is refreshed during execution | Resets follow the run/phase/index changes above. Without these changes, condition/sequence progress and control confirmation waits are preserved. |
| Normal action not sent/rejected, or still unconfirmed after the check at expiry | Start for `start`, Incomplete for `undo`, otherwise the current split group. |
| Reset not sent, or still unconfirmed after the check at expiry | The Reset group resets. |
| Timer state successfully checked after a rejected Reset | Reset group plus Start if Not running, Incomplete if Ended, or the current split group if Running/Paused. Both normal-action and Reset confirmation waits end. |

See [`reset_when`](conditions.en.md#reset_when) for resetting individual conditions
and [`then`](conditions.en.md#then) for progress after a time limit expires.

## Durations

`elapsed.duration`, `hold.duration`, and `then.within` accept a non-negative
decimal immediately followed by `ms` or `s`, for example `0ms`, `500ms`, `1.5s`.
Use a leading digit (`0.5s`, not `.5s`). Plain numbers, negatives, signs, spaces,
exponents, minutes, and compound durations such as `1m30s` are rejected. Quoting
is optional; these scalars are parsed as strings. Duration comparisons are
inclusive (`>=`), except that `then.within` expires only when elapsed time is
strictly greater than its window.

## Paths

Scenario files must end in `.yaml` or `.yml` (extension matching ignores case).
The Profile stores their absolute paths. Detector `reference` paths can be
absolute or relative; relative paths resolve against the YAML file's directory,
not the profile directory or process working directory. There is no include,
glob, environment-variable, or home-directory expansion.

Use forward slashes on Windows (`images/title.png`, `C:/game/title.png`). If using
backslashes, YAML single quotes keep them literal. Reference images are decoded
with their original channels/depth; see [image constraints](detectors.en.md#reference-images-and-channels).

## Condition inheritance

DivergenceSplitter's `extends: *anchor` loads one anchored condition mapping and applies optional `overrides`. Use it in any condition slot, including scenario conditions, rule conditions, and children of composite conditions. Place anchors anywhere in the YAML, including under `definitions`.

```yaml
definitions:
  base: &base
    id: wait
    type: elapsed
    duration: 1s

start_condition:
  extends: *base
  overrides:
    wait:
      duration: 2s
splits: []
```

- Set `id` to a nonempty string. IDs must be unique across the inherited condition tree, including its root and descendants.
- `overrides` maps IDs to settings. Mappings merge recursively by field. Scalars and sequences are replaced as a whole.
- Set an optional setting to `null` to clear its inherited value. For example, this restores the default behavior for a `then` condition's `within` or a detector's `roi`.
- In an inheritance chain, overrides apply from the earliest base to the final use site. You can give the inheriting condition an `id`. When omitted, it keeps the base condition's root ID.
- An `extends` mapping can also contain `overrides` and `id`. Use `overrides` to change settings.

A direct `*anchor` alias uses the entire definition. A `<<` merge imports mapping keys. With `extends`, you can also change settings on a child condition by ID, including children in sequences. See the supported fields and a multi-split example. [Condition reference](conditions.en.md) · [Scenario examples](examples.en.md#inherit-a-condition-and-change-the-image-per-split)

## YAML anchors, aliases, and merges

Anchors (`&name`) and aliases (`*name`) are YAML features provided by rapidyaml
(ryml). Alias complete condition/detector mappings, using definitions at the
root or nested elsewhere. An alias refers to the most recent preceding anchor
with that name:

```yaml
bright: &bright
  type: detected
  minimum_score: 0.8
  detector: {type: mean_brightness}
start_condition: *bright
splits:
  - rules:
      - condition:
          type: falling_edge
          condition: *bright
        action: split
```

The unused `bright` root key only holds the anchor definition. Conditions such
as `once` have independent state at each use; timing and counts are not shared.

Use `<<: *name` to merge a mapping and then override individual fields. Nested
merges are supported:

```yaml
definitions:
  detected: &detected
    type: detected
    minimum_score: 0.9
    detector: {type: mean_brightness}

start_condition:
  <<: *detected
  minimum_score: 0.95

splits:
  - rules:
      - condition:
          <<: *detected
          minimum_score: 0.8
        action: split
```

Precedence follows rapidyaml 0.16.0's standard behavior. For a single merge,
always write explicit overrides **after** `<<`; fields written before it can be
replaced by the merge source. With `<<: [*a, *b]`, the **later `b` wins** on
duplicate keys. With multiple merges, even explicit fields after `<<` can be
overwritten by a later merge source. This differs from the YAML 1.1 merge
definition, where explicit fields always win and earlier list entries have priority.

To reliably override the result of multiple merges, give the combined mapping
its own anchor, then use a single merge:

```yaml
a: &a {type: detected, minimum_score: 0.2}
b: &b {minimum_score: 0.8, detector: {type: mean_brightness}}
combined: &combined {<<: [*a, *b]}
start_condition:
  <<: *combined
  minimum_score: 0.95
splits: []
```

Merging operates on mapping entries; to customize a nested detector, also use
`<<` inside that detector mapping.

Merge keys are an extension supported by rapidyaml, rather than part of YAML
1.2's core specification. The same constraints on required/unknown fields, types,
and values apply to aliases and merged mappings.
Duplicate keys in the source YAML are rejected. Missing anchors, cyclic aliases,
and merges referring to non-mappings produce YAML errors. Invalid resolved
scenario fields produce schema errors. Neither error terminates the application.
