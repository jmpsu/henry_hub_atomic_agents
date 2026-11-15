"""Single source of truth for quant_hub and quant-gateway release version."""
from __future__ import annotations

import json
import os
from pathlib import Path

VERSION = "1.0.2"
_ROOT = Path(__file__).resolve().parent.parent


def get_release_info() -> dict[str, str]:
    meta_file = _ROOT / "release_metadata.json"
    if meta_file.is_file():
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            return {
                "version": str(data.get("version", VERSION)),
                "release_version": str(data.get("version", VERSION)),
                "release_commit": str(data.get("commit", "unknown")),
                "tag": str(data.get("tag", f"v{VERSION}")),
            }
        except Exception:
            pass
    ver = os.environ.get("RELEASE_VERSION", VERSION)
    commit = os.environ.get("RELEASE_COMMIT", "dev")
    return {
        "version": ver,
        "release_version": ver,
        "release_commit": commit,
        "tag": f"v{ver}",
    }
