import pytest
from divergencesplitter_ui.frame_preview import PreviewSize, fit_preview


def test_fit_preview_preserves_aspect_ratio() -> None:
    assert fit_preview(1920, 1080, 700, 500) == PreviewSize(700, 394, 700 / 1920)


def test_fit_preview_handles_empty_region() -> None:
    assert fit_preview(1920, 1080, 0, 500) == PreviewSize(0, 0, 0.0)


@pytest.mark.parametrize("frame_size", [(1920, 1080), (1280, 720), (640, 360)])
def test_fit_preview_16_by_9_fills_fixed_preview(frame_size: tuple[int, int]) -> None:
    assert fit_preview(*frame_size, 480, 270) == PreviewSize(
        480, 270, 480 / frame_size[0]
    )


def test_fit_preview_4_by_3_fits_inside_fixed_preview() -> None:
    result = fit_preview(640, 480, 480, 270)

    assert result == PreviewSize(360, 270, 270 / 480)
