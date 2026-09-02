# DivergenceSplitter

An automatic splitter configured with Python scenario modules.

## Packages

This repository is managed as a uv workspace with two independently installable
packages:

- `divergencesplitter` contains the public scenario-authoring API, detectors,
  conditions, rules, frame sources, and shared models.
- `divergencesplitter-runtime` contains scenario loading and the runtime state
  machines. It depends on `divergencesplitter`.

The desktop UI will be added later as its own workspace package. It is not
included until a UI is implemented.

Scenario modules only depend on the authoring library:

```python
import divergencesplitter as ds

scenarios = (
    ds.Scenario(
        connection=ds.LiveSplitConnection("rpc", "events"),
        reset_conditions=(reset_condition,),
        splits=(None,),
    ),
)
frame_source = ds.VideoFileSource("run.mp4")
```

The host application loads that module through the runtime package:

```python
from divergencesplitter_runtime import load_scenario_module

scenarios, frame_source = load_scenario_module("scenario.py")
```

Camera sources use OpenCV's resolved device index and backend:

```python
import cv2
import divergencesplitter as ds

frame_source = ds.OpenCvCameraSource(
    device_index=0,
    backend=cv2.CAP_ANY,
    width=1280,
    height=720,
    fps=60.0,
)
```

Device display names and enumeration belong to the UI or configuration-loading
layer. Resolve them to the OpenCV-specific `device_index` and `backend` before
constructing the source.

Before using a camera/backend combination in production, manually confirm that
it opens, continuously captures frames, releases the device on shutdown, and
reopens after a disconnect. Record the effective resolution and frame rate;
requested OpenCV properties are not a guarantee of exact effective values. The
selected backend must also return from synchronous `read()` in finite time,
because stopping waits for an in-progress read and the source does not add a
reader thread or a generic read timeout.

## Development

The workspace has one shared `uv.lock`. Commands can target either package:

```console
uv sync
uv run pytest
uv run --package divergencesplitter pytest packages/divergencesplitter/tests
uv run --package divergencesplitter-runtime pytest packages/divergencesplitter-runtime/tests
```
