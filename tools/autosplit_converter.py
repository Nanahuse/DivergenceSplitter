"""AutoSplit settings/image sequence converter.

The conversion model is deliberately independent from the desktop UI so it
can later be exposed by a CLI without changing conversion semantics.
"""

from __future__ import annotations

import re
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

_DIRECTIVE = re.compile(
    r"(?P<threshold>\([^)]*\))|(?P<pause>\[[^]]*\])|(?P<delay>#\d+(?:\.\d+)?#)|(?P<loop>@\d+@)|(?P<method>\^\d+\^)|(?P<flags>\{[^}]*\})"
)


@dataclass(frozen=True)
class AutoSplitImageDefinition:
    source_path: Path
    threshold: float
    comparison_method: int
    delay_ms: float = 0.0
    pause_seconds: float = 0.0
    loop_count: int = 1
    dummy: bool = False
    below_threshold: bool = False
    pause_action: bool = False


@dataclass(frozen=True)
class ConversionAnalysis:
    settings_path: Path
    image_directory: Path
    start: AutoSplitImageDefinition | None
    reset: AutoSplitImageDefinition | None
    images: tuple[AutoSplitImageDefinition, ...]
    loop_splits: bool
    start_also_resets: bool
    enable_auto_reset: bool
    not_converted: tuple[str, ...] = ()
    compatibility_notes: tuple[str, ...] = (
        "AutoSplit comparison resize preprocessing is not reproduced.",
    )


@dataclass(frozen=True)
class ConversionResult:
    status: str
    output_path: Path
    assets_directory: Path
    converted: tuple[str, ...]
    not_converted: tuple[str, ...]
    manual_fixes: tuple[str, ...]
    compatibility_notes: tuple[str, ...]
    not_imported: tuple[str, ...] = ()


def _setting(settings: dict, *names: str, default):
    for name in names:
        if name in settings:
            return settings[name]
    return default


def _parse(path: Path, settings: dict) -> AutoSplitImageDefinition:
    stem = path.stem
    threshold = _setting(settings, "default_similarity_threshold", default=0.95)
    method = int(_setting(settings, "default_comparison_method", default=0))
    delay = float(_setting(settings, "default_delay_time", default=0))
    pause = float(_setting(settings, "default_pause_time", default=0))
    loop_count = 1
    dummy = below = pause_action = False
    for match in _DIRECTIVE.finditer(stem):
        value = match.group(0)
        if value.startswith("("):
            threshold = float(value[1:-1])
        elif value.startswith("["):
            pause = float(value[1:-1])
        elif value.startswith("#"):
            delay = float(value[1:-1])
        elif value.startswith("@"):
            loop_count = int(value[1:-1])
        elif value.startswith("^"):
            method = int(value[1:-1])
        else:
            flags = value[1:-1].lower()
            dummy = "d" in flags
            below = "b" in flags
            pause_action = "p" in flags
    return AutoSplitImageDefinition(
        path, threshold, method, delay, pause, loop_count, dummy, below, pause_action
    )


def analyze(settings_path: str | Path) -> ConversionAnalysis:
    """Read settings and inspect its image directory without writing files."""
    path = Path(settings_path)
    try:
        with path.open("rb") as stream:
            settings = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"could not read settings.toml: {error}") from error
    directory_value = _setting(settings, "split_image_directory", default=None)
    if directory_value is None:
        raise ValueError("settings.toml has no split_image_directory")
    directory = Path(directory_value)
    if not directory.is_absolute():
        directory = path.parent / directory
    if not directory.is_dir():
        raise ValueError(f"split image directory does not exist: {directory}")
    files = tuple(
        sorted(
            (item for item in directory.iterdir() if item.is_file()),
            key=lambda item: item.name,
        )
    )
    starts = tuple(item for item in files if "start_auto_splitter" in item.name.lower())
    resets = tuple(item for item in files if "reset" in item.name.lower())
    if len(starts) > 1 or len(resets) > 1:
        raise ValueError(
            "split image directory contains multiple Start or Reset images"
        )
    reserved = set(starts) | set(resets)
    definitions = tuple(
        _parse(item, settings) for item in files if item not in reserved
    )
    return ConversionAnalysis(
        path,
        directory,
        _parse(starts[0], settings) if starts else None,
        _parse(resets[0], settings) if resets else None,
        definitions,
        bool(_setting(settings, "loop_splits", default=False)),
        bool(_setting(settings, "start_also_resets", default=False)),
        bool(_setting(settings, "enable_auto_reset", default=True)),
        not_converted=("loop_splits=true: only one pass was generated.",)
        if _setting(settings, "loop_splits", default=False)
        else (),
    )


def _duration(milliseconds: float) -> str:
    return f"{milliseconds:g}ms"


def _pause_duration(seconds: float) -> str:
    return f"{seconds:g}s"


def _detector(
    definition: AutoSplitImageDefinition, reference: str
) -> tuple[str, float]:
    method = definition.comparison_method
    if method == 0:
        return "root_mean_square_similarity", definition.threshold
    if method == 1:
        return "histogram_similarity", definition.threshold
    if method == 2:
        return "perceptual_hash_similarity", definition.threshold
    raise ValueError(f"unsupported comparison method: {method}")


def _condition(definition: AutoSplitImageDefinition, reference: str) -> list[str]:
    detector, threshold = _detector(definition, reference)
    lines = [
        "condition:",
        "  type: detected",
        f"  minimum_score: {threshold:g}",
        "  detector:",
        f"    type: {detector}",
        f"    reference: {reference}",
    ]
    if definition.below_threshold:
        lines = ["condition:", "  type: falling_edge", "  condition:"] + [
            "  " + line for line in lines
        ]
    return lines


def _top_condition(definition: AutoSplitImageDefinition, reference: str) -> list[str]:
    lines = _condition(definition, reference)
    return [line[2:] for line in lines[1:]]


def _stage(definition: AutoSplitImageDefinition, reference: str) -> list[list[str]]:
    """Return condition stages, retaining pause semantics and edge flags."""
    stages = [_top_condition(definition, reference)]
    if definition.pause_seconds:
        stages.append(
            ["type: elapsed", f"duration: {_pause_duration(definition.pause_seconds)}"]
        )
    return stages


def _then(stages: list[list[str]]) -> list[str]:
    if len(stages) == 1:
        return stages[0]
    lines = ["type: then", "conditions:"]
    for stage in stages:
        lines += ["  - " + stage[0]] + ["    " + line for line in stage[1:]]
    return lines


def convert(analysis: ConversionAnalysis, output_path: str | Path) -> ConversionResult:
    """Copy references and write a Scenario YAML conversion artifact."""
    output = Path(output_path)
    assets = output.with_name(output.stem + "_assets")
    output.parent.mkdir(parents=True, exist_ok=True)
    assets.mkdir(exist_ok=True)
    converted: list[str] = []
    not_converted = list(analysis.not_converted)
    manual: list[str] = []
    if analysis.start is None:
        manual.append(
            "AutoSplit has no Start Image; start_condition requires manual fixing."
        )
    if analysis.start_also_resets:
        not_converted.append(
            "start_also_resets=true: reset immediately before start is not represented."
        )
    if analysis.start and analysis.start.dummy:
        manual.append("Dummy Start Image is not representable as start_condition.")
    if analysis.loop_splits:
        not_converted.append(
            "loop_splits=true: only one pass of the split image sequence was generated."
        )
    asset_names: dict[Path, str] = {}

    def asset(path: Path, kind: str, index: int | None = None) -> str:
        if path not in asset_names:
            name = path.name if index is None else f"{index:03d}_{path.name}"
            shutil.copy2(path, assets / name)
            asset_names[path] = f"{assets.name}/{name}"
        return asset_names[path]

    lines = [
        "# Generated from AutoSplit.",
        f"# Import result: {'Incomplete' if manual else 'Partial' if not_converted else 'Success'}",
    ]
    if analysis.start:
        try:
            reference = asset(analysis.start.source_path, "start")
            lines += ["start_condition:"] + [
                "  " + line for line in _top_condition(analysis.start, reference)
            ]
            converted.append("Start Image")
        except ValueError as error:
            manual.append(str(error))
    else:
        lines += [
            "# Manual fix required: add start_condition",
            "# start_condition: TODO",
        ]
    if analysis.reset and analysis.enable_auto_reset:
        reference = asset(analysis.reset.source_path, "reset")
        lines += ["reset_condition:"] + [
            "  " + line for line in _top_condition(analysis.reset, reference)
        ]
    lines += ["splits:"]
    pending: list[list[str]] = []
    slot: list[tuple[list[str], str, str]] = []
    pause_state = False

    def emit_slot() -> None:
        nonlocal slot
        if not slot:
            return
        lines.extend(["  - rules:", "      -"])
        if len(slot) == 1:
            condition, action, _ = slot[0]
            lines.extend(
                "        " + value
                for value in ["condition:"] + ["  " + v for v in condition]
            )
            lines.append(f"        action: {action}")
        else:
            lines.append("        sequence:")
            for condition, action, _ in slot:
                lines.append("          - condition:")
                lines.extend("              " + value for value in condition)
                lines.append(f"            action: {action}")
        slot = []

    for index, definition in enumerate(analysis.images, 1):
        try:
            reference = asset(definition.source_path, "split", index)
            for _ in range(definition.loop_count):
                pending.extend(_stage(definition, reference))
                if definition.dummy:
                    if definition.delay_ms:
                        not_converted.append(
                            f"{definition.source_path.name}: ignored delay on dummy image"
                        )
                    continue
                if definition.delay_ms:
                    pending.append(
                        ["type: elapsed", f"duration: {_duration(definition.delay_ms)}"]
                    )
                action = "pause" if definition.pause_action else "split"
                if definition.pause_action:
                    action = "resume" if pause_state else "pause"
                    pause_state = not pause_state
                slot.append((_then(pending), action, definition.source_path.name))
                pending = []
                converted.append(definition.source_path.name)
                if action == "split":
                    emit_slot()
        except ValueError as error:
            not_converted.append(f"{definition.source_path.name}: {error}")
    if pending:
        not_converted.append("Terminal dummy sequence was not emitted.")
    emit_slot()
    if not_converted:
        lines[1] = "# Import result: Partial"
    if manual:
        lines[1] = "# Import result: Incomplete"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ConversionResult(
        lines[1].split(": ", 1)[1],
        output,
        assets,
        tuple(converted),
        tuple(not_converted),
        tuple(manual),
        analysis.compatibility_notes,
    )
