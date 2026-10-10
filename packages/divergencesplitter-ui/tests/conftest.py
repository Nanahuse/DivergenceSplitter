from __future__ import annotations

import pytest
from divergencesplitter_ui.licenses import (
    ApplicationLicense,
    AssetLicense,
    LicenseEntry,
    LicenseInventory,
)


@pytest.fixture
def license_inventory() -> LicenseInventory:
    return LicenseInventory(
        schema_version=7,
        application=ApplicationLicense("DivergenceSplitter", "MIT", "MIT License"),
        packages=(
            LicenseEntry("sample-package", "test-version", "MIT", "MIT License"),
        ),
        assets=(AssetLicense("sample-runtime", None, "MIT", "MIT License"),),
    )
