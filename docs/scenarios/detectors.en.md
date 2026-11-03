# Detector reference

[日本語（正本）](detectors.md) | [English](detectors.en.md)

[Scenario authoring](README.en.md) · [Conditions](conditions.en.md#detected) · [Examples](examples.en.md)

Detectors return a numeric score; a [`detected`](conditions.en.md#detected) condition
compares it with `minimum_score` using `>=`. All nine supported detectors return
scores clamped to `[0, 1]`. Larger means a stronger match, greater brightness, or
more color coverage, depending on the detector. Scores are not probabilities and
thresholds are not interchangeable across methods. Inspect desired and undesired
frames in Diagnostics before choosing a threshold.

## Common settings and ROI

Every detector requires `type` and accepts optional `roi`. Reference-based types
also require `reference`. Only `difference_hash_similarity` accepts `hash_size`;
only `color_range` accepts `lower`/`upper`. There are no other detector settings.

```yaml
type: template_match
reference: images/title.png
roi: {x: 100, y: 50, width: 320, height: 180}
```

`roi` can be omitted or `null` for the full normalized frame. If provided, all four
fields are required integers: non-negative `x`/`y` and positive `width`/`height`.
The origin is the top-left of the image **after** input Crop/Resize. The rectangle
must fit inside each incoming frame; it is not clipped automatically. The ROI
selects the input region, not a region in the reference image. All dimensional
constraints below compare the reference with this selected input region.

## Reference images and channels

Reference paths resolve [relative to the YAML file](yaml-reference.en.md#paths).
Images are decoded without forcing channels or bit depth. PNG with 8-bit BGR or
BGRA data is a practical format. A grayscale PNG remains single-channel; it is
not automatically converted to BGR for color/pixel detectors.

The shared reference preparation accepts 1-channel grayscale, 3-channel BGR, or
4-channel BGRA. For BGRA it extracts BGR and validates alpha: every value must be
0 or 255, with at least one opaque pixel. Partial alpha and fully transparent
images are rejected. Fully opaque alpha is removed and treated as unmasked.
Mask application depends on the detector:

| Detector | Input/reference shape and channels | Transparent reference pixels |
| --- | --- | --- |
| `template_match` | Reference width/height must not exceed region; channel count must match after alpha removal. | Binary mask used in template correlation. |
| `mean_absolute_similarity`, `root_mean_square_similarity` | Exact width/height and channel-count match after alpha removal. | Excluded from error and component count. |
| `histogram_similarity`, `perceptual_hash_similarity` | 8-bit BGR input and 8-bit BGR/BGRA reference. Unmasked sizes may differ; masked reference requires exact region dimensions. | Histogram excludes them; perceptual hash blacks them out in both images. |
| `difference_hash_similarity` | Reference and input can differ in size and use grayscale/BGR/BGRA layouts converted to grayscale. | Alpha is validated and removed, but the resulting mask is **not used**. |
| `phase_correlation` | Exact width/height match; grayscale/BGR/BGRA converted to float grayscale. | Alpha is validated and removed, but the mask is **not used**. |

Template and pixel-error detectors do not implicitly convert grayscale references
to match a normal BGR capture. For those methods, use a BGR reference for BGR
input. Pixel-error arithmetic converts values to floating point but still uses
255 for normalization, so 8-bit references are the appropriate scale. Template
matching converts reference and frame to compatible 8-bit or float data; it does
not normalize 16-bit intensity ranges to 0–255. Histogram and perceptual hash
explicitly reject non-8-bit references. Grayscale hash/phase processing uses float
conversion internally. Empty images and incompatible layouts fail validation or
evaluation rather than producing a successful detection.

Profile's [`resize_references`](../configuration.en.md#crop-resize-and-reference-images)
can alter these dimensions at load time. Apply validates reference construction;
actual region bounds and frame shape/channel compatibility require a frame.

## Choosing a method

| Need | Starting point |
| --- | --- |
| Find a distinctive small image at different positions inside a region | `template_match` |
| Compare a fixed screen/ROI pixel by pixel | `mean_absolute_similarity` |
| Penalize large pixel errors more strongly | `root_mean_square_similarity` |
| Compare color distributions with little concern for position | `histogram_similarity` |
| Compare coarse visual structure at different image sizes | `perceptual_hash_similarity` or `difference_hash_similarity` |
| Detect a bright/dark transition without a reference | `mean_brightness` |
| Detect how much of an area has a chosen color | `color_range` |
| Measure correlation of same-size images despite translation | `phase_correlation` |

These are starting points, not accuracy guarantees. Hashes and histograms can
give high scores to unrelated scenes. Use a meaningful ROI, additional conditions,
and representative test frames.

## template_match

```yaml
type: template_match
reference: images/title.png
```

Required: `reference`; optional: `roi`. Searches every position where the template
fits inside the region, then takes the highest normalized correlation.

- Unmasked: OpenCV `TM_CCOEFF_NORMED`, which subtracts per-channel means. If the
  maximum correlation is `r` in `[-1, 1]`, the score is `clamp((r + 1) / 2)`.
  Zero correlation therefore scores about `0.5`, not zero.
- Masked: OpenCV `TM_CCORR_NORMED` over opaque template pixels, without the same
  mean subtraction. The maximum correlation is directly clamped to `[0, 1]`.

The reference must have spatial variation in at least one channel; a constant
template is rejected. A reference larger than the region or with mismatched
channels fails evaluation. Non-finite correlation is an error. Use this for
distinctive symbols or text with stable scale; it does not search arbitrary scales
or rotations and does not expose the matched location to conditions.

## mean_absolute_similarity

```yaml
type: mean_absolute_similarity
reference: images/screen.png
```

Required: `reference`; optional: `roi`. Let `N` be the number of selected pixel
components (opaque pixels × channels), and `d_i` each input minus reference
component. Score: `clamp(1 - (sum(abs(d_i)) / N) / 255)`.

Identical images score 1; large average pixel error lowers the score. Requires
exact dimensions and matching channel counts. Use for fixed-position UI regions
or screens; movement, compression noise, and brightness changes affect the result.

## root_mean_square_similarity

```yaml
type: root_mean_square_similarity
reference: images/screen.png
```

Required: `reference`; optional: `roi`. With the same component selection as above,
score: `clamp(1 - sqrt(sum(d_i * d_i) / N) / 255)`.

Requires exact dimensions/channels. Squaring emphasizes a few large errors more
than mean absolute error does. Use when localized mismatches should reduce the
score strongly.

## histogram_similarity

```yaml
type: histogram_similarity
reference: images/screen.png
```

Required: `reference`; optional: `roi`. Builds an RGB color histogram with 8 bins
per channel (512 joint bins, intensities `[0, 256)`) and L2-normalizes it. Score:
`clamp(1 - D)`, where `D` is OpenCV's Bhattacharyya histogram distance. The distance
normalizes the histogram coefficient by histogram totals before its square-root
distance calculation. Matching color distributions score 1.

Requires 8-bit BGR; an 8-bit BGRA reference supplies a binary mask. With no mask,
image sizes may differ. With a mask, the input region must match its dimensions
so the same selected locations can be used. Spatial arrangement is discarded:
reordered pixels with the same distribution can score 1. Useful for broad scene
color changes; unsuitable alone for distinguishing similar-colored layouts.

## perceptual_hash_similarity

```yaml
type: perceptual_hash_similarity
reference: images/screen.png
```

Required: `reference`; optional: `roi`. For each image, black out masked locations
when a mask exists, resize to 8×8 with area interpolation, then expand to 32×32
with exact linear interpolation. Convert to 8-bit grayscale, then float, perform
a DCT, take the top-left 8×8 coefficients, set its DC coefficient to zero, and
compare each coefficient to the mean of that block to form 64 bits.

Score: `clamp(1 - HammingDistance / 64)`. Identical hashes score 1, even if the
original images differ. Input/reference must be 8-bit BGR (reference may include
validated alpha). Unmasked sizes may differ; masked dimensions must match. Useful
for coarse structure with size changes; a small hash can miss fine differences.

## difference_hash_similarity

```yaml
type: difference_hash_similarity
reference: images/screen.png
hash_size: 8
```

Required: `reference`; optional: `roi`, `hash_size` (positive integer, default 8).
Converts each image to float grayscale, area-resizes to
`(hash_size + 1) × hash_size`, and sets a bit for each horizontal pair whose right
value exceeds its left value. There are `hash_size²` bits. Score:
`clamp(1 - differing_bits / hash_size²)`.

Different source sizes and grayscale/color layouts are allowed. Reference alpha
is validated, but its mask is ignored. This measures horizontal intensity
structure rather than color or exact pixels. Increasing `hash_size` retains more
detail and increases work; it does not eliminate hash collisions.

## mean_brightness

```yaml
type: mean_brightness
roi: {x: 0, y: 0, width: 100, height: 100}
```

No required fields beyond `type`; optional: `roi`. No reference image. Score:
`clamp(mean_of_all_pixel_components / 255)`. This is the equal average of channel
means, not perceptually weighted grayscale luminance. Black scores 0, white 1
for normal 8-bit input. Grayscale and BGR work; if supplied with BGRA data its
alpha channel also contributes. Normal NDI capture discards alpha before detection.
Useful for fades and bright/dark transitions; it does not identify a particular
screen. Wrap `detected` in `not` to test brightness below a threshold.

## color_range

```yaml
type: color_range
lower: [0, 0, 180]
upper: [80, 80, 255]
```

Required: `lower`, `upper`; optional: `roi`. Bounds are equally sized lists of
either one component (grayscale) or three components (**B, G, R**, not RGB or HSV).
Each bound must be finite and each lower value must be at most its upper value.
They must match input channel count. The loader does not impose a 0–255 bound,
though that is the scale for normal input.

A pixel matches only when every channel lies within its inclusive interval.
Score: `matching_pixels / total_pixels` in the region. The example measures the
fraction of predominantly red pixels. No color-space conversion or reference
image is involved. Useful for solid indicators or overlays.

## phase_correlation

```yaml
type: phase_correlation
reference: images/screen.png
```

Required: `reference`; optional: `roi`. Converts both same-size images to float
grayscale and uses OpenCV `phaseCorrelate` without a window. Score is its response
(the normalized correlation peak response), clamped to `[0, 1]`. The returned
translation vector is discarded; the score is not a displacement or a direct
pixel-error similarity.

Reference/input channel counts can differ if both support grayscale conversion.
Alpha masks are validated but ignored. Requires equal dimensions. Use textured
images with a distinct correlation peak; flat or ambiguous patterns are poor
references. A non-finite response is an evaluation error.
