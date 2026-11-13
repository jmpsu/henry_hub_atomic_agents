"""Project-local runtime directory. Nothing this project writes at runtime goes outside the repository tree:
scratch files live under runtime/scratch/ and are removed as soon as they are no longer needed."""
import contextlib
import os
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.environ.get("QH_RUNTIME_DIR", BASE_DIR / "runtime"))
SCRATCH_DIR = RUNTIME_DIR / "scratch"


@contextlib.contextmanager
def scratch_file(suffix: str = "", data: bytes | None = None):
    """Yield the path of a uniquely named file under runtime/scratch/ (optionally pre-filled) and delete it afterwards."""
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    path = SCRATCH_DIR / f"{uuid.uuid4().hex}{suffix}"
    try:
        if data is not None:
            path.write_bytes(data)
        yield str(path)
    finally:
        with contextlib.suppress(OSError):
            path.unlink()
