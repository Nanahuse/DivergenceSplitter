# YAML reference

[日本語（正本）](yaml-reference.md) | [English](yaml-reference.en.md)

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

For each frame with a valid synchronized timer snapshot:

| Timer phase | Evaluated group |
| --- | --- |
| Not running | `start_condition` only. |
| Running or paused | `reset_condition` first, then rules for the current split index if Reset did not fire. |
| Ended | `incomplete_condition` only. |

Paused timers still evaluate conditions, including elapsed time and split rules.
The timer phase does not pause the application's monotonic clock. Inactive groups
are not called. Within an active condition, Boolean short-circuit handling has
specific state-update rules; see [condition evaluation](conditions.en.md#evaluation-and-short-circuiting).

### Pending actions and confirmation

Selecting an action makes it pending before dispatch and suppresses other normal
actions. Normal actions and Reset have separate pending state. While Running or
Paused, `reset_condition` can be evaluated during a normal action's reaction delay
or while a sent Split/Skip awaits confirmation. A pending Reset blocks new actions.

Reaction waits still process Bridge events and fresh frames. Manual Reset and an
automatic Reset interrupting a normal reaction wait bypass additional reaction
delay and cancel the unsent normal action. Other automatic actions use the
configured delay. Unrelated events and unchanged queries do not cancel that wait.

A successful RPC starts a wait of at most one second for the corresponding state
change. It does not always trigger an immediate query. Pause/Resume cannot confirm
Split/Skip, and a late Split cannot confirm Reset. Revision-only updates and
unchanged queries do not release confirmation waits.

The deadline uses monotonic time from RPC success and is processed even without
new input frames. At expiry, a query checks authoritative state before releasing
unconfirmed pending state and resetting its rule group. A later frame can decide
a fresh action. This second is separate from RPC response timeouts and condition
`elapsed` timing.

A rejected Reset RPC also triggers a query, clears both old waits, and resets the
Reset group and the group for the current phase/split index. Locally cancelling
an unsent Reset preserves a previously sent normal action's confirmation wait.
A failed query stops evaluation and enters connection recovery. See
[architecture](../development/architecture.en.md#bridge-and-controls) for
disconnect and unknown-result handling.

## State and reset lifecycle

Each Profile instance loads a fresh condition tree. Reusing an anchor creates
independent condition objects at each occurrence, not shared counters or clocks.
Every condition reset clears its status to `not_evaluated` and recursively resets
its children; each type's own cleared state is listed in [conditions](conditions.en.md).

The current runtime applies these resets:

| Event | Reset behavior |
| --- | --- |
| New session / initial Bridge baseline / reconnect | All groups start fresh. |
| Transition to Not running, or a change to run revision / LiveSplit segment count | All groups reset. |
| Move to another running/paused segment, including Undo | The destination segment's rules reset. |
| Transition to Ended | The Incomplete group resets. |
| Return from Ended to Running/Paused | Incomplete and Reset groups reset, and the destination segment resets. |
| Pause ↔ Resume at the same index | The split group normally retains its condition/sequence state. |
| Query/event within the same session | Resets follow the run/phase/index changes above. Unchanged queries and revision-only updates preserve groups and pending state. |
| Normal action not dispatched/rejected, or still unconfirmed after the expiry query | Start for `start`, Incomplete for `undo`, otherwise the current split group. |
| Reset not dispatched, or still unconfirmed after the expiry query | The Reset group resets. |
| Successful query after a rejected Reset RPC | Reset group plus Start if Not running, Incomplete if Ended, or the current split group if Running/Paused. Both old waits clear. |

Explicit [`reset_when`](conditions.en.md#reset_when) resets its own two child trees
when its reset condition is true. A `then.within` timeout is different: it restarts
step progress without resetting child condition state.

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

## YAML anchors and aliases

Anchors (`&name`) and aliases (`*name`) are YAML features provided by yaml-cpp,
not a DivergenceSplitter reference registry. Store reusable definitions at the
root and alias complete condition/detector mappings:

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

The unused `bright` root key only holds the anchor definition. Aliases are parsed
into independent runtime objects at their use sites. YAML merge keys (`<<`) are
not expanded by the application; in checked mappings they are unknown fields.
Alias a complete mapping rather than relying on merge-key inheritance. Avoid
cyclic aliases; the loader has no supported recursive-definition mechanism.
