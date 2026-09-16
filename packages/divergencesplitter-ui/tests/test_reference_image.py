from __future__ import annotations

import cv2
import numpy as np
import pytest
from divergencesplitter_ui.reference_image import (
    reference_to_png_bytes,
    reference_to_rgba_uint8,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def decode(data: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert image is not None
    return image


class TestReferenceToRgbaUint8:
    def test_normalized_values_are_preserved(self) -> None:
        rgba = reference_to_rgba_uint8(((0.0, 1.0), (1.0, 0.0)))

        assert rgba.shape == (2, 2, 4)
        assert rgba.dtype == np.uint8
        assert tuple(rgba[0, 0]) == (0, 0, 0, 255)
        assert tuple(rgba[0, 1]) == (255, 255, 255, 255)

    def test_three_channel_bgr_is_reversed_for_display(self) -> None:
        rgba = reference_to_rgba_uint8((((255, 0, 0),),))

        assert tuple(rgba[0, 0]) == (0, 0, 255, 255)

    def test_four_channel_keeps_alpha(self) -> None:
        rgba = reference_to_rgba_uint8((((0.0, 0.0, 1.0, 0.5),),))

        assert tuple(rgba[0, 0]) == (255, 0, 0, 127)

    def test_rejects_unsupported_shape(self) -> None:
        with pytest.raises(ValueError, match="unsupported reference image shape"):
            reference_to_rgba_uint8((((1.0, 2.0, 3.0, 4.0, 5.0),),))


class TestReferenceToPngBytes:
    def test_normalized_grayscale_encodes_as_png(self) -> None:
        data = reference_to_png_bytes(((0.0, 1.0, 0.0), (1.0, 0.0, 1.0)))

        assert data.startswith(PNG_SIGNATURE)
        decoded = decode(data)
        assert decoded.shape[:2] == (2, 3)

    def test_eight_bit_color_is_reversed_for_display(self) -> None:
        decoded = decode(
            reference_to_png_bytes(
                (
                    ((255, 0, 0), (0, 255, 0)),
                    ((0, 0, 255), (255, 255, 255)),
                )
            )
        )

        assert decoded.shape[:2] == (2, 2)
        # Detectors use OpenCV BGR; reference display reverses to RGB, so the
        # decoded BGRA read back as RGB must match that order.
        displayed_rgb = decoded[:, :, [2, 1, 0]]
        assert tuple(displayed_rgb[0, 0]) == (0, 0, 255)
        assert tuple(displayed_rgb[0, 1]) == (0, 255, 0)
        assert tuple(displayed_rgb[1, 0]) == (255, 0, 0)
        assert tuple(displayed_rgb[1, 1]) == (255, 255, 255)

    def test_opaque_image_encodes_with_full_alpha(self) -> None:
        decoded = decode(reference_to_png_bytes(((255,),)))

        assert decoded.shape[:2] == (1, 1)
        assert tuple(decoded[0, 0]) == (255, 255, 255, 255)
