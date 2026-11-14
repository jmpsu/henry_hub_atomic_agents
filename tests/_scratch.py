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


_MINE: list = []   # directories created by THIS process; concurrent test runs share ROOT and must not delete each other's


def mkdtemp() -> str:
    d = ROOT / uuid.uuid4().hex
    d.mkdir(parents=True)
    _MINE.append(d)
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


def _cleanup():
    for d in _MINE:
        shutil.rmtree(d, ignore_errors=True)
    try:
        ROOT.rmdir()            # only when no other run still has directories here
    except OSError:
        pass


atexit.register(_cleanup)
