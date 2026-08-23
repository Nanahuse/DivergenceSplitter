from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

sys.path.insert(0, str(Path(__file__).resolve().parent))

from proto_codegen import (  # noqa: E402
    EMBEDDED_PROTO_DIRECTORY,
    find_proto_root,
    generate_proto,
)


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        project_root = Path(self.root)
        proto_root = find_proto_root(project_root)

        if self.target_name == "sdist":
            force_include: dict[str, str] = build_data["force_include"]
            for proto_file in sorted(proto_root.rglob("*.proto")):
                relative_path = proto_file.relative_to(proto_root).as_posix()
                force_include[str(proto_file)] = (
                    f"{EMBEDDED_PROTO_DIRECTORY}/{relative_path}"
                )
            return

        if self.target_name != "wheel":
            return

        generated_root = Path(self.directory) / "livesplit-bridge-protobuf"
        if generated_root.exists():
            shutil.rmtree(generated_root)
        generate_proto(proto_root, generated_root)
        build_data["force_include"][str(generated_root / "livesplit")] = "livesplit"
