"""User-facing NDI branding shared by the Configuration and About views.

Only display strings live here. The internal API, configuration schema, and
``SourceType.NDI`` value are unchanged, so configuration files and scenario
modules keep using the plain ``ndi`` identifiers.
"""

from __future__ import annotations

NDI_WEBSITE_URL = "https://ndi.video/"
NDI_TRADEMARK_NOTICE = "NDI® is a registered trademark of Vizrt NDI AB."
