"""Strict JSON document reading shared by the Profile and App Settings loaders.

Both on-disk documents use the same rules: duplicate keys, non-finite numbers,
unknown fields, missing required fields, invalid types, and invalid values are
all rejected. A partial parse is never returned, so a caller either gets a fully
validated document or an error.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import NoReturn


class ConfigurationFileError(Exception):
    """A configuration file could not be read or parsed."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        super().__init__(str(error))


class ConfigurationValidationError(Exception):
    """Parsed JSON does not match the expected schema."""


def load_json_document(path: str | Path) -> object:
    """Read and JSON-parse one document, rejecting duplicate/non-finite values."""

    try:
        with Path(path).open(encoding="utf-8") as stream:
            return json.load(
                stream,
                object_pairs_hook=unique_object,
                parse_constant=reject_constant,
            )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ConfigurationFileError(error) from error


def dump_json_document(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def object_value(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{path} must be an object")
    return value


def array_value(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{path} must be an array")
    return value


def check_keys(
    value: dict[str, object],
    *,
    required: set[str],
    optional: set[str] | frozenset[str] = frozenset(),
) -> None:
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing:
        raise ValueError(f"missing fields: {sorted(missing)!r}")
    if unknown:
        raise ValueError(f"unknown fields: {sorted(unknown)!r}")


def string_value(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{path} must be a string")
    return value


def integer_value(value: object, path: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{path} must be an integer")
    return value


def boolean_value(value: object, path: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{path} must be a boolean")
    return value


def number_value(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{path} must be a number")
    return float(value)


def enum_value[E: Enum](value: object, enum_type: type[E], path: str) -> E:
    if not isinstance(value, str):
        raise TypeError(f"{path} must be a string")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ValueError(f"unsupported {path}: {value!r}") from error
