# Sample files

[日本語（正本）](README.md) | [English](README.en.md)

[Documentation home](../README.en.md) · [More scenarios](../docs/scenarios/examples.en.md)

- [minimal-scenario.yaml](minimal-scenario.yaml): starts after 2s of evaluation,
  then splits segment 0 after 3s. No images needed; use a one-segment test run.
- [profile.example.json](profile.example.json): v2 Video profile for that scenario.
  Replace **both** absolute paths with your recording and saved YAML location.
  A playable recording longer than ten seconds gives time to observe the test.
- [image-scenario.yaml](image-scenario.yaml) and [reference.ppm](reference.ppm):
  loadable template-detection example with a tiny nonconstant image. Keep these
  files together; replace the demo pattern with an actual game reference before
  using the scenario with game video. This is also a one-segment example.

Use [Getting started](../docs/getting-started.en.md) for the GUI walkthrough, or check
a customized profile without opening input or connecting to Bridge:

```powershell
.\divergencesplitter-cli.exe --profile C:/DivergenceSplitter/profile.json --check
```

The JSON template's example paths are syntactically valid Windows paths, but the
files must exist at your chosen locations for scenario validation and playback.
To validate the image example, change the instance's `scenario` path to its
absolute path. Image paths in that YAML stay relative to its own directory.
