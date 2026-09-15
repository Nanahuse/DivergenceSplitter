from __future__ import annotations

import cv2
import numpy as np
from divergencesplitter_ui.reference_image import reference_to_png_bytes

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def decode(data: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert image is not None
    return image


class TestReferenceToPngBytes:
    def test_normalized_grayscale_encodes_as_png(self) -> None:
        data = reference_to_png_bytes(((0.0, 1.0, 0.0), (1.0, 0.0, 1.0)))

        assert data.startswith(PNG_SIGNATURE)
        decoded = decode(data)
        assert decoded.shape[:2] == (2, 3)

    def test_eight_bit_color_matches_dpg_channel_order(self) -> None:
        decoded = decode(
            reference_to_png_bytes(
                (
                    ((255, 0, 0), (0, 255, 0)),
                    ((0, 0, 255), (255, 255, 255)),
                )
            )
        )

        assert decoded.shape[:2] == (2, 2)
        # Detectors use OpenCV BGR; the shared DPG path reverses to RGB for
        # display, so the decoded BGRA read back as RGB must match that order.
        displayed_rgb = decoded[:, :, [2, 1, 0]]
        assert tuple(displayed_rgb[0, 0]) == (0, 0, 255)
        assert tuple(displayed_rgb[0, 1]) == (0, 255, 0)
        assert tuple(displayed_rgb[1, 0]) == (255, 0, 0)
        assert tuple(displayed_rgb[1, 1]) == (255, 255, 255)

    def test_opaque_image_encodes_with_full_alpha(self) -> None:
        decoded = decode(reference_to_png_bytes(((255,),)))

        assert decoded.shape[:2] == (1, 1)
        assert tuple(decoded[0, 0]) == (255, 255, 255, 255)
