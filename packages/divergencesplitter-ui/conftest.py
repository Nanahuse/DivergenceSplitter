from __future__ import annotations

import pytest
from divergencesplitter_ui import license_page
from divergencesplitter_ui.licenses import (
    ApplicationLicense,
    AssetLicense,
    LicenseEntry,
    LicenseInventory,
)


@pytest.fixture
def license_inventory() -> LicenseInventory:
    return LicenseInventory(
        schema_version=4,
        application=ApplicationLicense("DivergenceSplitter", "MIT", "MIT License"),
        packages=(
            LicenseEntry("sample-package", "test-version", "MIT", "MIT License"),
        ),
        assets=(AssetLicense("sample-runtime", None, "MIT", "MIT License"),),
    )


@pytest.fixture
def packaged_license_inventory(
    monkeypatch: pytest.MonkeyPatch, license_inventory: LicenseInventory
) -> LicenseInventory:
    monkeypatch.setattr(license_page, "is_packaged_distribution", lambda: True)
    monkeypatch.setattr(license_page, "bundled_inventory", lambda: license_inventory)
    return license_inventory
