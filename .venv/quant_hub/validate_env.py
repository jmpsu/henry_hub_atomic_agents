"""Validate .env: required keys, chmod 600, listed in .gitignore. Never prints values."""
import os
import stat
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQUIRED = ["CF_ACCESS_CLIENT_ID", "CF_ACCESS_CLIENT_SECRET", "MOBILE_COMMAND_SECRET"]


def parse(path: Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            out[k.strip()] = v
    return out


def validate(env_path: Path = HERE / ".env") -> list:
    problems = []
    if not env_path.exists():
        return [f"{env_path} missing"]
    mode = stat.S_IMODE(env_path.stat().st_mode)
    if mode != 0o600:
        problems.append(f".env mode is {oct(mode)}, must be 0o600")
    env = parse(env_path)
    for k in REQUIRED:
        if not env.get(k):
            problems.append(f"{k} missing or empty")
    gi = env_path.parent / ".gitignore"
    if not gi.exists() or ".env" not in [l.strip() for l in gi.read_text().splitlines()]:
        problems.append(".env not listed in .gitignore")
    return problems


if __name__ == "__main__":
    probs = validate()
    for p in probs:
        print("FAIL:", p)
    print("OK" if not probs else f"{len(probs)} problem(s)")
    sys.exit(1 if probs else 0)
