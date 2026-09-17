"""Strict App Settings JSON loading and saving.

App Settings are managed by the application rather than opened/saved by the
user. The document is strict: a single bad field rejects the whole file, so a
partially valid file never contributes a salvageable ``last_profile``. The store
location is resolved in one place and can be overridden for tests.
"""

from __future__ import annotations

import os
from pathlib import Path

from divergencesplitter_runtime.configuration.models import (
    APP_SETTINGS_VERSION,
    AppSettings,
)
from divergencesplitter_runtime.configuration.strict_json import (
    ConfigurationFileError,
    ConfigurationValidationError,
    check_keys,
    dump_json_document,
    integer_value,
    load_json_document,
    object_value,
    string_value,
)

SETTINGS_DIRECTORY = "DivergenceSplitter"
SETTINGS_FILE_NAME = "settings.json"


def default_app_settings() -> AppSettings:
    return AppSettings(
        version=APP_SETTINGS_VERSION,
        log_level="OFF",
        reaction_time_ms=0,
        last_profile=None,
    )


def default_app_settings_path() -> Path:
    """Return the per-user location of the application settings file."""

    if os.name == "nt":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        root = Path(base) if base else Path.home() / ".config"
    return root / SETTINGS_DIRECTORY / SETTINGS_FILE_NAME


def load_app_settings(path: str | Path) -> AppSettings:
    """Load one versioned App Settings file, rejecting any invalid field."""

    value = load_json_document(path)
    try:
        root = object_value(value, "app settings")
        check_keys(
            root,
            required={"version", "log_level", "reaction_time_ms"},
            optional={"last_profile"},
        )
        version = integer_value(root["version"], "version")
        if version != APP_SETTINGS_VERSION:
            raise ValueError(f"unsupported app settings version: {version!r}")
        last_profile = root.get("last_profile")
        if last_profile is not None:
            last_profile = string_value(last_profile, "last_profile")
        return AppSettings(
            version=version,
            log_level=string_value(root["log_level"], "log_level"),
            reaction_time_ms=integer_value(
                root["reaction_time_ms"], "reaction_time_ms"
            ),
            last_profile=last_profile,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ConfigurationValidationError(str(error)) from error


def load_app_settings_or_default(path: str | Path) -> AppSettings:
    """Return the stored settings, or defaults when missing or invalid.

    A missing file is the normal first-run case; an invalid file is discarded as
    a whole. Either way a default :class:`AppSettings` is returned and nothing
    is written back, so a broken file is never silently overwritten.
    """

    settings_path = Path(path)
    if not settings_path.exists():
        return default_app_settings()
    try:
        return load_app_settings(settings_path)
    except ConfigurationFileError, ConfigurationValidationError:
        return default_app_settings()


def save_app_settings(path: str | Path, settings: AppSettings) -> None:
    """Write one App Settings document, creating its parent directory."""

    settings_path = Path(path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        dump_json_document(
            {
                "version": settings.version,
                "log_level": settings.log_level,
                "reaction_time_ms": settings.reaction_time_ms,
                "last_profile": settings.last_profile,
            }
        ),
        encoding="utf-8",
    )
