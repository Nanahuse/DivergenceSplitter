import numpy as np

from divergencesplitter.models import Frame

IMAGE = np.zeros((2, 2, 3), dtype=np.uint8)


def test_frame_holds_image_only():
    image = np.full((2, 2, 3), 7, dtype=np.uint8)
    frame = Frame(image=image)
    assert frame.image is image


def test_frame_is_frozen():
    assert Frame.__dataclass_params__.frozen


def test_frame_has_no_time_or_sequence():
    frame = Frame(image=IMAGE)
    assert not hasattr(frame, "timestamp")
    assert not hasattr(frame, "time")
    assert not hasattr(frame, "sequence")
    assert not hasattr(frame, "now")
