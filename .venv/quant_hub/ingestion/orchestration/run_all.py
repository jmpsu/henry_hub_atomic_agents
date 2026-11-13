"""Entry point matching the planned layout: runs every implemented collector (see collectors/README.md)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from collectors.run_all import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
