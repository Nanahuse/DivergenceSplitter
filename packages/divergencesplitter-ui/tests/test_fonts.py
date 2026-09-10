from __future__ import annotations

from divergencesplitter_ui import fonts


def test_bundled_font_resource_exists() -> None:
    resource = fonts.font_resource()

    assert resource.is_file()
    assert resource.name == "NotoSansJP[wght].ttf"


def test_bundled_font_is_a_truetype_font() -> None:
    with fonts.font_resource().open("rb") as stream:
        assert stream.read(4) == b"\x00\x01\x00\x00"


def test_bundled_font_license_resource_exists() -> None:
    resource = fonts.font_license_resource()

    assert resource.is_file()
    text = resource.read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in text
    assert "Reserved Font Name" in text
