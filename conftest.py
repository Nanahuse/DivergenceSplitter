"""Test bootstrap for untracked generated sources.

``divergencesplitter_ui.about`` imports the generated ``_version`` module, which
is not tracked in git. Generating it here keeps ``uv run pytest`` working on a
fresh checkout without a separate generation step.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
TOOLS = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS))

_generator = importlib.import_module("generate_ui_version")
_generator.generate_ui_version(_generator.UI_PACKAGE)
