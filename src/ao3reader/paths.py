"""Where downloaded voice models and finished chapter audio are kept."""

import os
import sys
from pathlib import Path


def cache_dir() -> Path:
    if override := os.environ.get("AO3_READER_CACHE"):
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "ao3-reader"
