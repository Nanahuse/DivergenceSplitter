# User guide

[日本語](user-guide.md) | [English (Translation)](user-guide.en.md)

This is an English translation. The Japanese version is the original and takes priority if there are differences.

[Documentation home](../README.en.md) · [First run](getting-started.en.md)

## Monitor

The Monitor toolbar combines Capture FPS, the history window, Preview and Reset All. Hover Capture for its state and received frame count. Preview opens a separate window only when needed and shows the shared input after Crop/Resize.

Instances appear in responsive cards: side by side when space permits, and in one column on narrow windows. Each card starts with connection state and Evaluation FPS. Open Details for its Bridge endpoint, timer state, split position, last action and average/maximum evaluation time. Instance indexes start at zero; Rule and Split numbers start at one.

Each Instance has a shared chart for Start, Split and other normal evaluations, plus a separate chart for the scenario's Reset Rules. Series stay in view for the selected time window across Rule and then step changes. A Condition keeps its color, and current series stand out from earlier ones. The summary below the charts shows current Rules and progress.

Numeric series show progress toward a common 100% target line, with a display range of 0–125%. Boolean Conditions and Conditions with a nonpositive target show dots for true and dashes for false below the baseline. A heavier orange line marks a timer Reset. Status icons before Condition names show a check for true, a circle for false, a square for not_evaluated, a dash for skipped and a cross for error.

Choose 15, 30 or 60 seconds for the shared time axis. Select a Condition name or a trace on a shared chart, or click Details, to open the inspector with axes, legend, current value, target and result timeline. Its structure tree includes merged child Conditions and every then step. The Rule selector includes past Splits and all Rules in a sequence. Compare detectors lets you select multiple scores within that Instance. The inspector stays open across Split changes. Use the wheel to zoom, drag to pan, or right-drag to select a range. Interaction pauses the time reference and links the value/result X ranges. Resume live, Reset view or a window-length change resumes live display. Retention still expires old data while paused. Display settings are not saved.

In the inspector, detected Conditions plot scores and thresholds; elapsed/hold plot seconds and target time; nth plots observed counts as stairs; then plots step progress. Nth counts true child evaluations, so it counts edges only when its child is an edge Condition. Boolean Conditions show state history. Blank intervals mean no measurement, rather than a zero score. Lines break at gaps and resets. Orange marks resets, green marks transitions, and red marks errors. Numeric state that actually updates during short-circuit evaluation is still recorded; skipped current values are labelled Last value.

History is collected at evaluation time even while Monitor is hidden. It stays in memory for 60 seconds, with at most 8192 samples per Condition. At capacity, thinning prioritizes extrema and state changes. Reconnects, Bridge session changes and Profile applies start fresh histories. Ready means the Bridge connection and timer synchronization succeeded; input, Conditions and split configuration must still be checked separately.

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
defined in the [configuration reference](configuration.en.md).

| Operation | Effect |
| --- | --- |
| Edit fields | Changes the draft; the active runtime continues with its applied values. |
| Apply | Validates scenario/reference loading and source selection, then replaces the session with the draft. Capture and instance state restart; video files reopen from the beginning. It does not save the profile JSON. |
| Revert draft | Replaces the draft with the active profile. It does not reload the file or undo actions already sent to LiveSplit. |
| the **Open** button in Profile | Loads a JSON file and immediately applies it, then replaces the draft. |
| the **Save As** button in Profile | Writes the current draft to JSON and remembers its path. It does not apply or fully validate that draft. |

Saving a draft before Apply can therefore save settings that are not yet active
or valid. Edit, check the draft preview, Apply, check Monitor, then save. Capture
opens asynchronously, so an input error may appear after Apply succeeds. Check
Monitor afterwards, correct any reported error, and Apply again.

YAML and image edits on disk are not watched. Reapply or reopen the profile to
reload them. The last opened or saved profile path is remembered; if that file
exists at the next startup, the application attempts to open and apply it.

### Draft input preview

Enable **Preview input** under **Draft input preview** to inspect the draft
Camera, Video, or NDI input while no Session is active. The status shows opened
input dimensions, backend-reported FPS when available, measured received FPS,
and transformed output dimensions. Crop/Resize edits update without reopening
the same source, including transforms of the last image while a sender is paused.

This preview checks input and image transforms. It does not evaluate scenarios or
send Bridge controls. It also does not preview reference-image conversion by
**Resize reference images**; check detection in Monitor after Apply.

The draft preview does not open an input while a Session is running. Click
**Stop Session and preview draft** to stop it and inspect edits, then Apply to
resume scenario execution. Leaving Profile, disabling Preview input, or starting
a Session releases the preview source. Videos also play in preview; Apply reopens
them from the beginning. After a preview error, edit the source or toggle Preview
input to retry.

## Settings

- **Log level**: `OFF`, `DEBUG`, `INFO` (default), `WARNING`, or `ERROR`. This filters
  existing log events; DEBUG does not add per-frame detector score logging.
- **Reaction time**: non-negative milliseconds, `0` by default; the UI permits up
  to `5000`. Automatic actions normally wait until the triggering frame's capture
  time plus this delay. Time already spent processing counts toward the delay.
  See [pending actions and confirmation](scenarios/yaml-reference.en.md#pending-actions-and-confirmation)
  for Reset interruption and delay exceptions. This is not a
  detector threshold or a guarantee of exact timer timing.
- **Theme**: Light or Dark; saved changes update the theme immediately.

Click **Apply** to persist settings and apply the theme. **Reload** restores the controller's saved
values into the Settings fields. Reapply the profile for runtime settings
(reaction time and logging level) to take effect. Settings are stored separately
from profiles in `%APPDATA%/DivergenceSplitter/settings.json`; the complete schema
is in [configuration](configuration.en.md#application-settings).

## About

About shows the application version and project/license links. The license tables list bundled third-party components with their license names and links to the original notices. Additional license notices appear in a separate table. Full license texts and notices are included in licenses/ and DISTRIBUTION-NOTICE.txt. NDI Runtime is shown as an external component and is not bundled; check its detection status in Profile's NDI input settings.
