# Video fallback fixture

`fallback-h264.mp4` is a generated two-frame, 128x128 gray H.264 baseline
recording. It contains no third-party media. The Windows source regression uses
it to verify platform-decoder fallback after the built-in MJPEG reader declines
the input. It does not require FFmpeg to be installed when tests run.

Generated with:

```sh
ffmpeg -f lavfi -i color=gray:s=128x128:r=30 -frames:v 2 -c:v libx264 -profile:v baseline -pix_fmt yuv420p fallback-h264.mp4
```
