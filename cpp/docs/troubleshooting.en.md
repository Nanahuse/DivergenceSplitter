# Troubleshooting

[日本語（正本）](troubleshooting.md) | [English](troubleshooting.en.md)

[Documentation home](../README.en.md)

Start in Monitor: check whether frames arrive, whether each instance is Ready,
and whether a last action/error is shown. Then inspect Diagnostics for the active
phase, split, condition status, and score.

## Input problems

| Symptom | Check and recovery |
| --- | --- |
| No camera or configured camera not connected | Reconnect it, close other applications using it, click Detect cameras, and select the correct backend/device/mode. Duplicate names need the correct index. |
| DirectShow subtype cannot be selected or confirmed | Choose another selectable enumerated mode or Media Foundation. Do not invent a subtype GUID. See [camera constraints](configuration.en.md#camera--capture-card). |
| Configured capture mode rejected | Re-enumerate modes, disable Request 60 fps, select an available size/FPS, and Apply. |
| Video cannot open or decode | Check the absolute path and permissions, and try a recording using a codec supported by this OpenCV build. A file-picker extension is not a decoder guarantee. |
| Reached end of video | Expected at EOF: playback does not loop. Apply to start again. |
| Crop margins do not fit | Reduce margins relative to the raw input dimensions, before Resize. |
| NDI input not available in this build | Use the official NDI-enabled ZIP or [enable the SDK at build time](development/building.en.md#ndi-enabled-builds). |
| NDI source absent or no frames | Start the sender; check its advertised name, network reachability, and firewall rules; Search again. A saved offline name is retained. An ordinary timeout is not fatal and the receiver can recover when the sender returns. |
| NDI runtime initialization fails | Extract the entire ZIP and keep its DLL beside the executable. The loader uses the application directory, not PATH or the working directory. Use `--ndi-check` below. |

Camera open/read errors marked retryable are retried by capture. Mode, decoding,
normalization, and fatal SDK errors can stop capture. Correct the profile and
Apply; watch frame count rather than a static last preview.

## Bridge connection problems

- Confirm that the current LiveSplit layout includes LiveSplit Bridge and its
  status is Running. Match its WebSocket port to the Profile row.
- Use a Bridge release supporting Protocol v4 on the same PC. The application
  connects to `127.0.0.1`; remote-host settings are not available.
- For multiple LiveSplit processes, give their Bridge components distinct ports
  and save each layout. A port already in use can prevent Bridge startup.
- Connecting may recover automatically after a transient disconnect. A protocol
  error or Failed state needs correction of the reported cause and a new Apply.

An **unknown** control outcome means the request may already have reached
LiveSplit. The runtime resynchronizes and suppresses the same automatic operation
against the same authoritative state. Inspect LiveSplit before manually repeating
an action. Connection recovery is not proof that a previous control failed.

## Control confirmation and Reset failures

If Monitor's Current evaluation shows Pending or Waiting for Reset confirmation,
check the last action and LiveSplit's actual phase/split index. An action result
of ok means RPC success; confirmation of the corresponding state change is
separate. Normal actions and Reset have separate pending state: Pause/Resume
cannot confirm Split/Skip, and a late Split cannot confirm Reset.

After RPC success, confirmation waits at most one second before querying state.
The deadline is processed even if input frames stop. If still unconfirmed after
the query, pending state clears and the relevant rules reset, but deciding the
next automatic action requires a fresh frame. Check both input and connection.
See the [YAML reference](scenarios/yaml-reference.en.md#pending-actions-and-confirmation)
for confirmation, reaction delay, and rule behavior.

If a Reset RPC is rejected, check the displayed error. The application queries
current state, clears both old normal/Reset waits, and resets the Reset group and
the group for the current phase/index. If the query fails, evaluation stops for
connection recovery. For persistent Connecting or Failed states, check Bridge
Status, ports, and logs. After Reset All, check every instance's result separately.

## Detection does not fire, or fires unexpectedly

1. Verify the normalized image in Monitor. ROI coordinates refer to the image
   after Crop/Resize, not raw capture coordinates.
2. In Diagnostics, inspect the active phase and zero-based split index. A `null`
   split has no automatic rules. A YAML split list longer than the LiveSplit run
   invalidates evaluation (with a special allowance for an empty stopped run).
3. Check rule errors and condition status. An out-of-bounds ROI, incompatible
   channels, or reference dimensions can fail at evaluation even when YAML loaded.
   Consult [detector constraints](scenarios/detectors.en.md).
4. Compare the latest and maximum score with `minimum_score`. Higher scores mean
   a stronger match (or more brightness/color coverage). There is no universal
   threshold across detectors. Test both desired and undesired game frames.
5. Check [condition behavior](scenarios/conditions.en.md): edges need an earlier
   baseline sample; `nth` counts true evaluations; `once` stays true; `hold`
   restarts on false; a `then` step begins on a later evaluation.
6. Reapply after editing YAML or images. Apply and runtime resets clear relevant
   condition state and diagnostic maxima; a saved file alone is not reloaded.

For repeated actions, avoid a condition that remains true indefinitely on a
non-advancing action such as pause/resume. Use a sequence or suitable stateful
conditions and account for the [rule reset lifecycle](scenarios/yaml-reference.en.md#state-and-reset-lifecycle).

## Logs

On Windows, logs are appended to
`%APPDATA%/DivergenceSplitter/diagnostics.log`; rotated files use `.1`, `.2`, and
`.3` suffixes. Settings and the log directory are created as needed. In Settings,
select INFO or DEBUG, Save, and reapply the profile before reproducing the issue.
OFF disables logging; changing the level does not add events that the application
does not emit.

Useful events include `profile.apply`, `capture.error`, `instance.state`,
`instance.ready`, and `instance.action`. Condition evaluation errors are counted
in Diagnostics; detailed detector exception messages are not guaranteed in the
log. When reporting a problem, include the application revision/build, relevant
profile/YAML, input type, normalized dimensions, diagnostic status/score, and the
log around the event. Remove private paths or source names if necessary.

## Command-line checks

From the extracted application directory, with a customized profile:

```powershell
.\divergencesplitter-cli.exe --profile C:/DivergenceSplitter/profile.json --check
.\divergencesplitter-cli.exe --profile C:/DivergenceSplitter/profile.json --seconds 10
.\divergencesplitter-cli.exe --ndi-check
.\divergencesplitter-cli.exe --ndi-list
```

`--check` loads the profile and every scenario/reference, applying reference
resize options. It does **not** open input, check frame/ROI compatibility, connect
to Bridge, or send controls. The timed command runs a real session and can control
LiveSplit. Without a positive `--seconds`, it runs until interrupted with Ctrl+C.
`--ndi-check` initializes the runtime; `--ndi-list` also performs source discovery.

The CLI accepts `--settings C:/DivergenceSplitter/settings.json`. Without this
option it uses default settings rather than automatically loading the GUI's
settings file. Exit codes are `0` for successful completion/check, `2` for usage
errors, `3` for caught configuration/startup/NDI failures, and `4` for a reported
session runtime error. Inspect printed instance states too: a failed Bridge
instance need not make the timed command exit nonzero.
