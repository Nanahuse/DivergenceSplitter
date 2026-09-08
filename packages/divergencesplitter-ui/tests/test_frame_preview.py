from divergencesplitter_ui.frame_preview import PreviewSize, fit_preview


def test_fit_preview_preserves_aspect_ratio() -> None:
    assert fit_preview(1920, 1080, 700, 500) == PreviewSize(700, 394, 700 / 1920)


def test_fit_preview_handles_empty_region() -> None:
    assert fit_preview(1920, 1080, 0, 500) == PreviewSize(0, 0, 0.0)
