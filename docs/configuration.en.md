# Configuration reference

[日本語（正本）](configuration.md) | [English](configuration.en.md)

[Documentation home](../README.en.md) · [Profile workflow](user-guide.en.md#profile-draft-active-configuration-and-file)

## Profile JSON v2

A profile contains one shared input and a list of independent scenario/Bridge
connections. Start with [profile.example.json](../examples/profile.example.json)
and replace its absolute paths. JSON does not support comments or trailing commas.
Unknown keys are rejected in profile objects, including nested objects. Keys and
enum strings are case-sensitive.

| Field | Required | Value |
| --- | --- | --- |
| `version` | Yes | Integer `2`. |
| `source` | Yes | One Camera, Video, or NDI source object below. |
| `instances` | Yes | Array of instance objects. The JSON loader accepts an empty array; GUI Apply requires at least one. |
| `instances[].connection` | Yes | Object containing only `port`. |
| `instances[].connection.port` | Yes | Integer `1`–`65535`; use the corresponding local Bridge's WebSocket port, normally `54000`. |
| `instances[].scenario` | Yes | Non-empty absolute path to a `.yaml` or `.yml` file. |

The host is fixed to `127.0.0.1`; there is no profile host/URL field. Absolute video
and scenario paths are independent of where the profile JSON is saved. On Windows,
use `C:/folder/file` or escape backslashes as `C:\\folder\\file`. Reference-image
paths inside YAML follow [different rules](scenarios/yaml-reference.en.md#paths).

## Camera / capture card

```json
{
  "type": "camera",
  "device": {
    "backend": "direct_show",
    "name": "USB Video",
    "index": 0
  },
  "mode": {
    "width": 1920,
    "height": 1080,
    "fps": 60.0,
    "subtype_guid": "47504A4D-0000-0010-8000-00AA00389B71"
  },
  "request_60_fps": false,
  "transform": { "crop": null, "resize": null }
}
```

This is a source-object example; names and modes must come from your own device
enumeration. Prefer **Detect cameras** and select a mode in Profile.

| Field | Required | Value |
| --- | --- | --- |
| `type` | Yes | `"camera"`. |
| `device.backend` | Yes | `"direct_show"` or `"media_foundation"`. |
| `device.name` | Yes | Exact non-empty enumerated name. |
| `device.index` | Yes | Non-negative device enumeration index; disambiguates duplicate names. If only one device matches the name/backend, it can resolve despite an index change. |
| `mode.width`, `mode.height` | Yes | Positive integer dimensions from the device's mode list. |
| `mode.fps` | Yes | Positive number matching an enumerated mode. |
| `mode.subtype_guid` | Yes | Non-empty enumerated media subtype GUID. |
| `request_60_fps` | Yes | Boolean; makes an additional best-effort 60 FPS request after mode configuration. This disables the normal configured-FPS mismatch check, and does not guarantee 60 FPS delivery. |
| `transform` | No | Transform object below; omitted means no Crop/Resize. |

Device identity uses backend and name, with index for duplicate names. Modes must
match enumerated width, height, FPS, and subtype. DirectShow sets and verifies
selectable FourCC subtypes; unsupported exact subtype selection is rejected at
Apply. Media Foundation validates enumeration and checks size/FPS when opening,
but OpenCV cannot select its exact subtype. The UI labels those modes **size/FPS**.
Reported FPS is checked when available; measured capture FPS can differ.

## Video file

```json
{
  "type": "video",
  "path": "C:/recordings/run.avi",
  "transform": { "crop": null, "resize": null }
}
```

`type` and a non-empty absolute `path` are required; `transform` is optional.
The video plays at its reported FPS, with 30 FPS as the fallback when FPS is not
reported. File extensions alone do not guarantee decoder support: playback uses
the OpenCV video backends included in the build. End-of-file stops capture and
reports an error; there is no automatic looping. Apply reopens the file.

Opening a video first tries OpenCV's built-in AVI/MJPEG decoder
(`CAP_OPENCV_MJPEG`), then falls back to normal backend selection (`CAP_ANY`)
if it cannot open the file. There is no Profile option to choose the decoder.
MJPEG AVI through the built-in decoder needs no OS codec or GPU initialization.
Other formats depend on the OpenCV build and available backends.

## NDI®

```json
{
  "type": "ndi",
  "name": "CAPTURE-PC (Game)",
  "transform": { "crop": null, "resize": null }
}
```

`type` and a non-empty advertised source `name` are required; `transform` is
optional. This selects a source by name, not by IP or URL. Profile's editable list
retains saved names when a sender is offline. **Search again** refreshes discovery;
the list also refreshes while Profile is visible.

NDI requires an enabled build. The official ZIP includes its runtime beside the
executable. Sender pauses and ordinary receive timeouts keep the receiver alive;
the SDK reconnects when the named source returns. Fatal SDK/format errors stop
capture. Frames are converted to owned BGR images before normal processing.
See [NDI notices](../licenses/NDI.en.md) and [local NDI builds](development/building.en.md#ndi-enabled-builds).

## Crop, resize, and reference images

All three source types accept the same optional `transform` object. When present,
both `crop` and `resize` keys are required; either can be `null` to disable it.

```json
{
  "crop": { "left": 8, "right": 8, "top": 0, "bottom": 0 },
  "resize": {
    "width": 1280,
    "height": 720,
    "interpolation": "area",
    "resize_references": false
  }
}
```

| Field | Value |
| --- | --- |
| `crop.left`, `right`, `top`, `bottom` | All required, non-negative integers in source pixels. Combined horizontal/vertical margins must leave at least one pixel in each dimension. |
| `resize.width`, `height` | Required positive integers. Resizing uses exactly these dimensions, without automatic aspect-ratio preservation or letterboxing. |
| `resize.interpolation` | Optional: `area` (default), `nearest`, `linear`, `cubic`, or `lanczos4`. |
| `resize.resize_references` | Optional Boolean, default `false`. Only takes effect when resize is enabled. |

The input pipeline is **source image → Crop → Resize → detector ROI**. For example,
a 1920×1080 source cropped by 8 pixels on both sides becomes 1904×1080, then is
resized to 1280×720. A YAML ROI is expressed in that final 1280×720 coordinate space.
The same normalized image appears in Monitor and feeds every instance.

**Resize reference images** controls a separate load-time operation on scenario
images. When enabled, the selected interpolation resizes every reference to:

- the profile's output width/height when its detector has no ROI;
- the detector ROI's width/height when it has an ROI.

Reference resizing does not crop reference images, scale ROI coordinates, or
modify YAML/image files. With resizing disabled or `resize_references: false`,
references retain their original dimensions. Keep it off for a small template that should be
searched inside a larger frame; enabling it enlarges that template to the whole
output or ROI. Interpolating transparent images may create partial alpha values
that fail binary-mask validation; use `nearest` or prepare a suitable reference.
Detector-specific size, channel, and alpha restrictions are in the
[detector reference](scenarios/detectors.en.md).

Scenario/reference construction is checked on Apply, including transformed
reference validity. Errors that depend on an actual incoming frame (ROI bounds,
frame/reference shape, channel count) are detected during evaluation.

## Multiple instances

Add one row per LiveSplit process. Configure a distinct Bridge port in each
LiveSplit layout (for example `54000` and `54001`) and use the matching ports in
the profile. Each row can load a different YAML scenario. Rows share capture and
normalization but have independent condition state and timer connections.

The loader does not enforce unique ports. Repeating a port makes multiple
scenarios control the same timer; avoid that for independent runs. Crop/Resize
belongs to the shared source, so per-instance transforms cannot be configured.

## Application settings

The GUI writes `%APPDATA%/DivergenceSplitter/settings.json` separately from profiles:

```json
{
  "version": 1,
  "log_level": "INFO",
  "reaction_time_ms": 0,
  "last_profile": null,
  "ui": { "theme": "light" }
}
```

Required fields are `version` (`1`), `log_level` (`OFF`, `DEBUG`, `INFO`, `WARNING`,
`ERROR`), and `reaction_time_ms` (non-negative integer). `last_profile` is optional,
null or an absolute profile path. `ui` is optional; its only optional field,
`theme`, is `light` (default) or `dark`. Unknown fields are rejected. For the
effect and activation of settings, see [Settings](user-guide.en.md#settings).
