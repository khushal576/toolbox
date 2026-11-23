#!/usr/bin/env python3
"""Copy the AWS notes AND the MCQ files from the learn-aws-services repo into learn-aws/notes/ and learn-aws/mcq/.

    python3 learn-aws/sync.py [--source ../learn-aws-services] [--dry-run]

Notes: the root README.md + EXAM-COVERAGE.md, each category README.md, and every service's *.md. Never CLAUDE.md / PLAN.md / TEMPLATE.md.
MCQs: mcq/<category>/<service>.json (not mcq/README.md). Each file must parse and hold a "questions" list, or nothing is copied.
Mirrors the source: files removed there are removed here. The generated index.html / build.py / web/ of that repo are NOT used (this tool has its own reader).
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP = {"CLAUDE.md", "PLAN.md", "TEMPLATE.md"}


def wanted_notes(src: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in sorted(src.rglob("*.md")):
        rel = p.relative_to(src)
        if rel.parts[0].startswith(".") or rel.parts[0] in ("mcq", "web") or p.name in SKIP:
            continue
        if len(rel.parts) == 1 and p.name not in ("README.md", "EXAM-COVERAGE.md"):
            continue
        out["notes/" + rel.as_posix()] = p
    return out


def wanted_mcq(src: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in sorted((src / "mcq").rglob("*.json")) if (src / "mcq").is_dir() else []:
        data = json.loads(p.read_text(encoding="utf-8"))          # a broken file stops the sync here, before anything is copied
        if not isinstance(data.get("questions"), list):
            raise ValueError(f"{p} has no 'questions' list")
        out["mcq/" + p.relative_to(src / "mcq").as_posix()] = p
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(HERE.parent.parent / "learn-aws-services"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    src = Path(a.source)
    if not (src / "README.md").is_file():
        print(f"{src} does not look like the AWS notes repo.", file=sys.stderr)
        return 1
    try:
        files = {**wanted_notes(src), **wanted_mcq(src)}
    except ValueError as e:
        print(f"Refusing: {e}", file=sys.stderr)
        return 1
    notes = [k for k in files if k.startswith("notes/")]
    if len(notes) < 20:
        print(f"Only {len(notes)} notes found; refusing (looks wrong).", file=sys.stderr)
        return 1
    old = {p.relative_to(HERE).as_posix() for d in ("notes", "mcq") for p in (HERE / d).rglob("*") if p.is_file()}
    changed = [r for r, p in files.items() if r not in old or (HERE / r).read_bytes() != p.read_bytes()]
    removed = sorted(old - set(files))
    print(f"{len(notes)} notes, {len(files) - len(notes)} question files; {len(changed)} new/changed; {len(removed)} removed.")
    if a.dry_run:
        return 0
    for r in changed:
        (HERE / r).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(files[r], HERE / r)
    for r in removed:
        (HERE / r).unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
