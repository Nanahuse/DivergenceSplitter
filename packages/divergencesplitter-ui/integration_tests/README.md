# UI integration tests

These tests mount the real `FletApplication` (real components, real Flet
controls, real event/update path) on a recording page with test doubles for the
external boundaries. They run in-process without Flutter or a display and are
executed by the `ui-integration` CI job:

```bash
uv run pytest integration_tests -q
```

## Known limitation: Flet device-mode integration tests

Flet's official device-mode integration testing (`flet test`, which runs the
packaged app with embedded Python) was evaluated. It builds and launches, but the
packaged embedded Python (serious_python) crashes with a `RecursionError` while
importing `cv2` -> `numpy` at startup. The same site-packages import fine under
the build's CPython, so this is an embedded-runtime constraint rather than an
application issue.

Because it cannot complete reliably, it is not used as a CI regression gate and
no smoke test or dependency for it is kept. It can be reconsidered if the Flet /
serious_python runtime or the runtime import layout changes.
