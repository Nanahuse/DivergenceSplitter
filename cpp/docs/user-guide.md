# User guide

[Documentation home](../README.md) · [First run](getting-started.md)

## Monitor

Monitor shows the normalized input image: the same Crop/Resize output used by all
scenario instances. The input line shows published frames, measured capture FPS,
and whether capture is running. The table shows each scenario's connection state,
timer phase, split index, last requested action, and error or action result.
Scenario and split indexes in diagnostics are zero-based.

**Ready** means that the instance has synchronized with Bridge. Check input and
Diagnostics as well; Ready alone does not mean that a condition is true or that
the configured split count is valid. While disconnected, that instance cannot
evaluate actions. Other instances have independent connections.

### Reset All

Hold **Reset All** for two seconds. Releasing early or moving the pointer outside
the button cancels the hold. On completion, the application queues a manual Reset
for each instance. It sends Reset for running, paused, or ended timers once the
instance can process the request. A stopped timer needs no reset. Check each
instance's result; this is not an atomic operation across LiveSplit processes.

Reset All resets timers, rather than clearing a draft or deleting a profile.
After a reset, a start condition that becomes true can start the run again.

## Profile: draft, active configuration, and file

Profile selects one input, optional transforms, and a table of Bridge ports and
scenario paths. Use **Add instance**, **Remove instance**, and
**Browse scenario...** to edit that table. Input options and the JSON schema are
defined in the [configuration reference](configuration.md).

| Operation | Effect |
| --- | --- |
| Edit fields | Changes the draft; the active runtime continues with its applied values. |
| Apply | Validates scenario/reference loading and source selection, then replaces the session with the draft. Capture and instance state restart; video files reopen from the beginning. It does not save the profile JSON. |
| Revert draft | Replaces the draft with the active profile. It does not reload the file or undo actions already sent to LiveSplit. |
| File > Open Profile... | Loads a JSON file and immediately applies it, then replaces the draft. |
| File > Save Profile As... | Writes the current draft to JSON and remembers its path. It does not apply or fully validate that draft. |

Saving a draft before Apply can therefore save settings that are not yet active
or valid. For a repeatable workflow, edit, Apply, check Monitor, then save. Apply
may succeed before an asynchronous capture-open error appears; check Monitor
afterwards. Correct a reported error and Apply again.

YAML and image edits on disk are not watched. Reapply or reopen the profile to
reload them. The last opened or saved profile path is remembered; if that file
exists at the next startup, the application attempts to open and apply it.

## Diagnostics

Expand the scenario tree to inspect Run, Start, Reset, Incomplete, and each Split.
Rules show their action; a sequence shows its active step. Condition rows show
status and, for `detected`, the latest score, maximum score since reset, and
threshold. Evaluation details include evaluation count, last evaluation time in
milliseconds, and rule error count.

| Status | Meaning |
| --- | --- |
| `not_evaluated` | Newly loaded or reset; no evaluation since then. |
| `true` / `false` | Most recent normal evaluation result. |
| `skipped` | Result not used at that point in evaluation. Stateful nodes can still update during short-circuit evaluation; see [conditions](scenarios/conditions.md). |
| `error` | Evaluation threw an error, such as an incompatible reference shape. |

Only the active rule groups are evaluated. Inactive groups may retain their last
status; a displayed score is not necessarily from the newest frame. The
[YAML reference](scenarios/yaml-reference.md) explains phase selection and resets.

## Settings

- **Log level**: `OFF`, `DEBUG`, `INFO` (default), `WARNING`, or `ERROR`. This filters
  existing log events; DEBUG does not add per-frame detector score logging.
- **Reaction time**: non-negative milliseconds, `0` by default; the UI permits up
  to `5000`. Automatic actions wait until the triggering frame's capture time plus
  this delay. Time already spent processing counts toward the delay. This is not a
  detector threshold or a guarantee of exact timer timing.
- **Theme**: Light or Dark; saved changes update the theme immediately.

Click **Save** to persist settings. **Reload** restores the controller's saved
values into the Settings fields. Reapply the profile for runtime settings
(reaction time and logging level) to take effect. Settings are stored separately
from profiles in `%APPDATA%/DivergenceSplitter/settings.json`; the complete schema
is in [configuration](configuration.md#application-settings).

## About and command line

About shows the application version and project/license links. For headless
validation and execution, see [troubleshooting](troubleshooting.md#command-line-checks).
