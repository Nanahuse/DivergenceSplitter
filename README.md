# DivergenceSplitter

An automatic splitter configured with JSON and Python scenario modules.

## Installation

Scenario repositories that only define rules install the authoring library:

```console
uv add "divergencesplitter @ git+https://github.com/Nanahuse/DivergenceSplitter.git#subdirectory=packages/divergencesplitter"
```

An application that loads and runs scenarios installs the runtime. It includes
the authoring library transitively, plus the LiveSplit Bridge client:

```console
uv add "divergencesplitter @ git+https://github.com/Nanahuse/DivergenceSplitter.git#subdirectory=packages/divergencesplitter" "divergencesplitter-runtime @ git+https://github.com/Nanahuse/DivergenceSplitter.git#subdirectory=packages/divergencesplitter-runtime"
```

Pin a tag or commit in production. Both direct references are needed until the
packages are published to a package index.

## Packages

This repository is managed as a uv workspace with two independently installable
packages:

- `divergencesplitter` contains the public scenario-authoring API, detectors,
  conditions, rules, frame sources, and shared models.
- `divergencesplitter-runtime` contains scenario loading and the runtime state
  machines. It depends on `divergencesplitter`.

The desktop UI will be added later as its own workspace package. It is not
included until a UI is implemented.

Scenario modules only import the authoring library and export `scenarios`. A
minimal `scenario.py` is:

```python
import divergencesplitter as ds

brightness = ds.MeanBrightnessDetector()
split_condition = ds.Detected(brightness, minimum_score=200.0)
reset_condition = ds.Not(ds.Detected(brightness, minimum_score=10.0))

scenarios = (
    ds.Scenario(
        connection=ds.LiveSplitConnection(
            "tcp://127.0.0.1:54000",
            "tcp://127.0.0.1:54001",
        ),
        reset_conditions=(reset_condition,),
        splits=((ds.Rule(split_condition, ds.Action("split")),),),
    ),
)
```

The JSON configuration selects the scenario and frame source independently:

```json
{
  "version": 1,
  "source": {
    "type": "video",
    "path": "./run.mp4"
  },
  "scenario": {
    "script": "./scenario.py"
  },
  "runtime": {
    "log_level": "INFO"
  }
}
```

Run it with the runtime CLI:

```console
uv run divergencesplitter config.json
```

Press Ctrl+C to request cooperative shutdown. The process distinguishes normal
completion, invalid CLI use, scenario-module errors, startup validation errors,
runtime errors, and user interruption with separate exit codes. While running,
`runtime.fps` is logged once per second. UI code can read the same non-consuming
values from `OperationalDiagnostics.metrics_snapshot()` without parsing logs.

Scenario modules are trusted Python code and execute with the runner's process
permissions. Only load modules you trust.

Camera configuration stores the device name as the primary identifier and its
enumeration ID to disambiguate devices with the same name:

```json
{
  "version": 1,
  "source": {
    "type": "camera",
    "device": {
      "name": "USB Video Device",
      "id": 2
    },
    "width": 1280,
    "height": 720,
    "fps": 60
  },
  "scenario": {
    "script": "./scenario.py"
  },
  "runtime": {
    "log_level": "INFO"
  }
}
```

On Windows, the runtime enumerates devices with
`windows-capture-device-list`. A unique name match is accepted even if its ID
changed. If several devices have the same name, the saved ID must match one of
them. Relative scenario and video paths are resolved from the configuration
file's directory.

Before using a camera/backend combination in production, manually confirm that
it opens, continuously captures frames, releases the device on shutdown, and
reopens after a disconnect. Record the effective resolution and frame rate;
requested OpenCV properties are not a guarantee of exact effective values. The
selected backend must also return from synchronous `read()` in finite time,
because stopping waits for an in-progress read and the source does not add a
reader thread or a generic read timeout.

## LiveSplit Bridge constraints

Run a compatible LiveSplit.Bridge instance at the endpoints configured by each
scenario. The runtime uses synchronous Bridge calls on a dedicated worker per
connection, so capture and processing do not wait for network responses.
Actions are checked against a fresh snapshot and are never blindly retried.
The current protocol does not provide atomic compare-and-act, so an external
LiveSplit operation can still race between that snapshot and the action. A
timeout after sending an action is reported as an unknown result, not retried.

## Performance

The reproducible 360p/720p, 60 fps baseline and initial SLO are in
[`PERFORMANCE.md`](PERFORMANCE.md).

## Development

The workspace has one shared `uv.lock`. Commands can target either package:

```console
uv sync
uv run pytest
uv run --package divergencesplitter pytest packages/divergencesplitter/tests
uv run --package divergencesplitter-runtime pytest packages/divergencesplitter-runtime/tests
```
