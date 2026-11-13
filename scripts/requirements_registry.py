#!/usr/bin/env python3
"""Deterministic atomic requirement registry for artifacts/Ultimate_Goal.md.

Every list item, and every prose sentence containing a normative word (must, shall, required, never, do not, only),
becomes one requirement with:
  id        R<section>-<8 hex of sha256(normalised text)>   stable while the wording is unchanged
  text      the exact wording from the specification
  section   heading path, e.g. "6. Architecture 4 > 6.4 Performance evaluation"
  line      1-based line number in Ultimate_Goal.md
List items that only introduce a sub-list (ending in ':') are kept as context and not counted.

Writes requirements/registry.json. Re-running on an unchanged specification produces a byte-identical file.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "artifacts" / "Ultimate_Goal.md"
OUT = ROOT / "requirements" / "registry.json"
NORMATIVE = re.compile(r"\b(must|shall|required|requires|never|do not|don't|only promote|mandatory)\b", re.I)
LIST = re.compile(r"^(\s*)(?:[-*]|\d+\.)\s+(.*)$")


def norm(t: str) -> str:
    t = re.sub(r"[*`]", "", t)          # strip markdown emphasis/code marks only; underscores are part of identifiers
    return re.sub(r"\s+", " ", t).strip()


def sentences(par: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z`*\"(])", par) if s.strip()]


def parse(text: str) -> list[dict]:
    reqs, heads, para, para_line, last_lead = [], [], [], 0, None
    lines = text.splitlines()

    def section_no():
        for h in heads:
            m = re.match(r"(\d+(?:\.\d+)*)", h)
            if m:
                num = m.group(1)
        return num if any(re.match(r"\d", h) for h in heads) else "0"

    def emit(t, ln, kind, lead=None):
        raw = norm(t)
        if len(raw) < 4:
            return
        sec = " > ".join(heads) or "(preamble)"
        num = "0"
        for h in heads:
            m = re.match(r"(\d+(?:\.\d+)*)", h)
            if m:
                num = m.group(1)
        key = raw if not lead else f"{norm(lead)} :: {raw}"
        rid = f"R{num}-{hashlib.sha256(key.encode()).hexdigest()[:8]}"
        reqs.append({"id": rid, "section": sec, "section_no": num, "line": ln, "kind": kind, "text": raw, "context": norm(lead) if lead else None})

    def flush():
        nonlocal para
        if para:
            joined = " ".join(p for p, _ in para)
            for s in sentences(joined):
                if NORMATIVE.search(s):
                    emit(s, para[0][1], "prose")
        para = []

    for i, line in enumerate(lines, 1):
        st = line.strip()
        if st.startswith("#"):
            flush()
            level = len(st) - len(st.lstrip("#"))
            title = norm(st.lstrip("#"))
            heads[:] = heads[: level - 1] + [title] if level > 1 else [title]
            heads[:] = [h for h in heads if h]
            last_lead = None
            continue
        m = LIST.match(line)
        if m:
            flush()
            item = m.group(2).strip()
            if item.endswith(":"):
                if NORMATIVE.search(item):
                    emit(item, i, "list_item", last_lead)
                last_lead = item
                continue
            emit(item, i, "list_item", last_lead if m.group(1) or last_lead else None)
            continue
        if not st:
            flush()
            continue
        if st.endswith(":"):                      # a lead-in for the list that follows (emitted itself only if normative)
            flush()
            if NORMATIVE.search(st):
                emit(st, i, "prose")
            last_lead = st
            continue
        if not para:
            last_lead = None if not st.endswith(":") else last_lead
        para.append((st, i))
    flush()
    seen, out = set(), []
    for r in reqs:                               # identical wording in the same section counts once
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(r)
    return out


def main() -> int:
    text = SPEC.read_text()
    reqs = parse(text)
    OUT.parent.mkdir(exist_ok=True)
    doc = {"schema": "requirements/1", "source": "artifacts/Ultimate_Goal.md", "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
           "count": len(reqs), "requirements": reqs}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    by = {}
    for r in reqs:
        top = r["section_no"].split(".")[0]
        by[top] = by.get(top, 0) + 1
    print(json.dumps({"requirements": len(reqs), "by_top_section": dict(sorted(by.items(), key=lambda kv: int(kv[0]))), "out": str(OUT.relative_to(ROOT))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
