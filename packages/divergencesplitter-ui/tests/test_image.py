from __future__ import annotations

import numpy as np
import pytest
from divergencesplitter_ui.image import (
    TextureEvent,
    flatten,
    plan_texture,
    reference_to_rgba_float32,
    source_signature,
    to_rgba_float32,
)


def _signature(h: int, w: int, c: int):
    from divergencesplitter_ui.image import TextureSignature

    return TextureSignature(h, w, c)


class TestSourceSignature:
    def test_gray_2d_is_single_channel(self) -> None:
        image = np.zeros((4, 5), dtype=np.uint8)
        assert source_signature(image) == _signature(4, 5, 1)

    def test_bgr_3channel(self) -> None:
        image = np.zeros((4, 5, 3), dtype=np.uint8)
        assert source_signature(image) == _signature(4, 5, 3)

    def test_singleton_channel(self) -> None:
        image = np.zeros((4, 5, 1), dtype=np.uint8)
        assert source_signature(image) == _signature(4, 5, 1)

    def test_rejects_higher_dimensionality(self) -> None:
        with pytest.raises(ValueError):
            source_signature(np.zeros((2, 2, 2, 2), dtype=np.uint8))


class TestTexturePlan:
    def test_none_previous_creates(self) -> None:
        assert plan_texture(None, _signature(4, 5, 3)) is TextureEvent.CREATE

    def test_same_signature_updates(self) -> None:
        signature = _signature(4, 5, 3)
        assert plan_texture(signature, signature) is TextureEvent.UPDATE

    def test_shape_change_recreates(self) -> None:
        assert (
            plan_texture(_signature(4, 5, 3), _signature(5, 5, 3))
            is TextureEvent.RECREATE
        )

    def test_channel_change_recreates(self) -> None:
        assert (
            plan_texture(_signature(4, 5, 3), _signature(4, 5, 1))
            is TextureEvent.RECREATE
        )


class TestToRgbaFloat32:
    def test_bgr_swaps_red_and_blue(self) -> None:
        image = np.array(
            [[[10, 20, 30], [40, 50, 60]]],
            dtype=np.uint8,
        )
        rgba = to_rgba_float32(image)

        assert rgba.shape == (1, 2, 4)
        assert rgba.dtype == np.float32
        # BGR (10, 20, 30) -> RGBA (30, 20, 10, 255)
        np.testing.assert_allclose(rgba[0, 0], [30 / 255, 20 / 255, 10 / 255, 1.0])

    def test_gray_replicates_to_rgb_with_opaque_alpha(self) -> None:
        image = np.array([[0, 128, 255]], dtype=np.uint8)
        rgba = to_rgba_float32(image)

        assert rgba.shape == (1, 3, 4)
        np.testing.assert_allclose(rgba[0, 0], [0.0, 0.0, 0.0, 1.0])
        np.testing.assert_allclose(rgba[0, 1], [128 / 255, 128 / 255, 128 / 255, 1.0])
        np.testing.assert_allclose(rgba[0, 2], [1.0, 1.0, 1.0, 1.0])

    def test_bgra_swaps_rb_and_keeps_alpha(self) -> None:
        image = np.array(
            [[[10, 20, 30, 128]]],
            dtype=np.uint8,
        )
        rgba = to_rgba_float32(image)

        np.testing.assert_allclose(
            rgba[0, 0], [30 / 255, 20 / 255, 10 / 255, 128 / 255]
        )

    def test_singleton_channel_matches_gray(self) -> None:
        image = np.array([[[100], [200]]], dtype=np.uint8)
        rgba = to_rgba_float32(image)

        assert rgba.shape == (1, 2, 4)
        np.testing.assert_allclose(rgba[0, 0], [100 / 255, 100 / 255, 100 / 255, 1.0])

    def test_result_is_contiguous_float32(self) -> None:
        image = np.zeros((8, 8, 3), dtype=np.uint8)
        rgba = to_rgba_float32(image)

        assert rgba.dtype == np.float32
        assert rgba.flags["C_CONTIGUOUS"]


class TestReferenceToRgbaFloat32:
    def test_frozen_integer_values_use_eight_bit_range(self) -> None:
        rgba = reference_to_rgba_float32(((0, 255), (128, 64)))

        np.testing.assert_allclose(rgba[0, 0], [0.0, 0.0, 0.0, 1.0])
        np.testing.assert_allclose(rgba[0, 1], [1.0, 1.0, 1.0, 1.0])
        np.testing.assert_allclose(
            rgba[1, 0],
            [128 / 255, 128 / 255, 128 / 255, 1.0],
        )

    def test_normalized_float_values_are_preserved(self) -> None:
        rgba = reference_to_rgba_float32(((0.0, 0.5, 1.0),))

        np.testing.assert_allclose(rgba[0, 1], [0.5, 0.5, 0.5, 1.0])

    def test_frozen_bgr_values_are_scaled_and_swapped(self) -> None:
        rgba = reference_to_rgba_float32((((10, 20, 30),),))

        np.testing.assert_allclose(
            rgba[0, 0],
            [30 / 255, 20 / 255, 10 / 255, 1.0],
        )


class TestFlatten:
    def test_flatten_returns_contiguous_float32(self) -> None:
        rgba = to_rgba_float32(np.zeros((4, 5), dtype=np.uint8))
        flat = flatten(rgba)

        assert flat.ndim == 1
        assert flat.size == 4 * 5 * 4
        assert flat.dtype == np.float32
        assert flat.flags["C_CONTIGUOUS"]
