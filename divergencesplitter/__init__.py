"""DivergenceSplitter frame source foundation."""

from divergencesplitter.frame_source import (
    ErrorAction,
    FrameSource,
    FrameSourceState,
)
from divergencesplitter.models import Frame
from divergencesplitter.video_file import (
    VideoFileDecodeError,
    VideoFileEndOfFileError,
    VideoFileError,
    VideoFileOpenError,
    VideoFileReadBeforeReadyError,
    VideoFileSource,
)

__all__ = [
    "ErrorAction",
    "Frame",
    "FrameSource",
    "FrameSourceState",
    "VideoFileDecodeError",
    "VideoFileEndOfFileError",
    "VideoFileError",
    "VideoFileOpenError",
    "VideoFileReadBeforeReadyError",
    "VideoFileSource",
]
