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

## Development

The workspace has one shared `uv.lock`. Commands can target either package:

```console
uv sync
uv run pytest
uv run --package divergencesplitter pytest packages/divergencesplitter/tests
uv run --package divergencesplitter-runtime pytest packages/divergencesplitter-runtime/tests
```
