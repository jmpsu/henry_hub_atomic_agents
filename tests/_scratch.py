"""Scratch directories for tests, kept inside the project (runtime/test_scratch/) and removed when the run ends."""
import atexit
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime_paths import RUNTIME_DIR  # noqa: E402

ROOT = RUNTIME_DIR / "test_scratch"
import os  # noqa: E402
os.environ.setdefault("RAW_DIR", str(ROOT / "raw"))   # test payloads never land in the project's real raw/ archive


def mkdtemp() -> str:
    d = ROOT / uuid.uuid4().hex
    d.mkdir(parents=True)
    return str(d)


class TemporaryDirectory:
    def __init__(self):
        self.name = mkdtemp()

    def cleanup(self):
        shutil.rmtree(self.name, ignore_errors=True)

    def __enter__(self):
        return self.name

    def __exit__(self, *exc):
        self.cleanup()


atexit.register(lambda: shutil.rmtree(ROOT, ignore_errors=True))
