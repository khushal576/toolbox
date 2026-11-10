#!/usr/bin/env python3
"""
scripts/remove_tool.py — remove a Toolbox tool cleanly (roadmap P3; the mirror of scripts/new_tool.py).

    python3 scripts/remove_tool.py my-tool                       # DRY RUN (the default): prints the plan, changes nothing
    python3 scripts/remove_tool.py my-tool --apply --confirm my-tool   # does it
    ... --remove-volumes                                         # also deletes the tool's Docker volume(s) — its stored files are gone for good

What it removes (all-or-nothing, with rollback if anything fails):
  * the tool's folder;
  * its Dockerfile `COPY <folder>/…` lines and its package's `__init__.py` on the `RUN touch` line;
  * its `API_CHECKS` line / `PAGE_ONLY` entry in tests/smoke/test_api.py, its own tests (tests/smoke|unit/test_<package>*.py);
  * its row in the KNOWLEDGE_MAP.md tool index;
  * its docker-compose volume mounts (`<vol>:/app/data/<folder>`) and the top-level volume key when nothing else mounts it.

What it NEVER does (it lists these as "left in place" and prints what you could run yourself):
  * touch Postgres schemas, Vault secrets, S3 objects or workspace.yaml;
  * delete a Docker volume unless you pass --remove-volumes AND the typed confirmation;
  * rewrite prose in docs: mentions in *.md are listed for you to review.

It refuses when other code still uses the tool (imports of its package, `/tools/<name>/` URLs, `depends_on`) unless --ignore-references,
and always refuses the hard-protected core tools. --apply needs `--confirm <name>` when the tool is enabled, when that cannot be checked
(the stack is not reachable) or when it has stored data. Standard library only (+ PyYAML, which Toolbox already requires).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
HARD_PROTECTED = {"vault", "datadiff-pro"}                 # the platform depends on these; removing them is a redesign, not a cleanup
SKIP_DIRS = {".git", "node_modules", "__pycache__", "wheelhouse", "backups", "data", "docs", "tests", "models", "certs", ".venv", "venv"}
CODE_SUFFIXES = {".py", ".js", ".html", ".yaml", ".yml", ".sh", ".toml", ".cfg"}


class Refused(Exception):
    """Nothing has been changed."""


@dataclass
class Plan:
    name: str
    folder: Path
    is_plugin: bool
    package: str = ""
    edits: dict[Path, str] = field(default_factory=dict)        # new full text of a file that stays
    deletes: list[Path] = field(default_factory=list)            # extra files to delete (own tests)
    volumes: list[str] = field(default_factory=list)             # compose volume keys that only this tool used
    blockers: list[str] = field(default_factory=list)
    left: list[str] = field(default_factory=list)                # data left in place (never touched)
    review: list[str] = field(default_factory=list)              # things for the owner to look at
    notes: list[str] = field(default_factory=list)
    has_data: bool = False


# ---- finding the tool -----------------------------------------------------------------------------------------------------

def _manifest_name(path: Path) -> str:
    try:
        return str((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("name", ""))
    except Exception:  # noqa: BLE001 - a broken manifest must not hide the other tools
        return ""


def resolve(repo: Path, ident: str) -> tuple[str, Path, bool]:
    """(manifest name, folder, lives in plugins/). `ident` is the manifest name or the folder name."""
    found = []
    for m in sorted(repo.glob("*/manifest.yaml")):
        found.append((_manifest_name(m), m.parent, False))
    for m in sorted((repo / "plugins").glob("*/manifest.yaml")) if (repo / "plugins").is_dir() else []:
        found.append((_manifest_name(m), m.parent, True))
    hits = [(n, f, p) for n, f, p in found if ident in (n, f.name)]
    if not hits:
        raise Refused(f"no tool named '{ident}' (tools are found by manifest name or folder name; try: {', '.join(sorted({n for n, _, _ in found if n})[:12])} …).")
    if len(hits) > 1:
        raise Refused(f"'{ident}' is ambiguous: " + ", ".join(str(f.relative_to(repo)) for _, f, _ in hits))
    return hits[0]


# ---- scanning for what else mentions the tool -------------------------------------------------------------------------------------

def _files(repo: Path, suffixes: set[str], skip: Path):
    for p in repo.rglob("*"):
        if not p.is_file() or p.suffix not in suffixes:
            continue
        rel = p.relative_to(repo)
        if any(part in SKIP_DIRS for part in rel.parts) or (rel.parts[0] == "tools" and len(rel.parts) > 1 and rel.parts[1] == "_template"):
            continue
        if skip in p.parents or p.name in ("docker-compose.yml", "Dockerfile"):
            continue
        yield p


def find_blockers(repo: Path, name: str, folder: Path, pkgs: set[str]) -> list[str]:
    out: list[str] = []
    imp = [re.compile(rf"^\s*(from|import)\s+{re.escape(p)}(\.|\s|$)") for p in pkgs if p]
    url = re.compile(rf"/tools/{re.escape(name)}(/|\"|'|\b)")
    for p in _files(repo, CODE_SUFFIXES, folder):
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").split("\n")
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if p.suffix == ".py" and any(rx.search(line) for rx in imp):
                out.append(f"{p.relative_to(repo)}:{i}: imports the tool's package — {line.strip()[:80]}")
            elif url.search(line) and not line.strip().startswith(("#", "//")):
                out.append(f"{p.relative_to(repo)}:{i}: calls /tools/{name}/ — {line.strip()[:80]}")
    for m in sorted(repo.glob("*/manifest.yaml")):
        if m.parent == folder:
            continue
        try:
            deps = (yaml.safe_load(m.read_text(encoding="utf-8")) or {}).get("depends_on") or []
        except Exception:  # noqa: BLE001
            deps = []
        if name in deps:
            out.append(f"{m.relative_to(repo)}: depends_on lists '{name}'")
    return out


def doc_mentions(repo: Path, name: str, folder: Path, limit: int = 15) -> list[str]:
    rx = re.compile(rf"(`|\b){re.escape(folder.name)}/|/tools/{re.escape(name)}/")
    out = []
    for p in sorted(repo.rglob("*.md")):
        rel = p.relative_to(repo)
        if folder in p.parents or any(part in SKIP_DIRS - {"docs"} for part in rel.parts) or rel.as_posix() == "docs/roadmap/ROADMAP.md" or "_template" in rel.parts:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
            if line.startswith("|") and f"`/tools/{name}/`" in line:
                continue                                  # the tool-index row is removed by the script itself
            if rx.search(line):
                out.append(f"{rel}:{i}: {line.strip()[:90]}")
                if len(out) >= limit:
                    return out + ["… (more)"]
    return out


# ---- the edits ---------------------------------------------------------------------------------------------------------------------

def edit_dockerfile(text: str, folder: str) -> tuple[str, set[str]]:
    lines = text.split("\n")
    copy_idx = [i for i, l in enumerate(lines) if re.match(rf"^COPY\s+{re.escape(folder)}/", l)]
    pkgs = set()
    for i in copy_idx:
        m = re.search(r"\s\./([A-Za-z0-9_]+)(/|\s|$)", lines[i])
        if m:
            pkgs.add(m.group(1))
    keep = [l for i, l in enumerate(lines) if i not in set(copy_idx)]
    if copy_idx:  # collapse the blank line a removed block leaves behind
        at = copy_idx[0]
        before = at - 1
        if 0 <= at < len(keep) and keep[at].strip() == "" and before >= 0 and keep[before].strip() == "":
            del keep[at]
    for i, l in enumerate(keep):
        if l.startswith("RUN touch "):
            toks = l.split(" ")
            keep[i] = " ".join(t for t in toks if not any(t.startswith(f"{p}/") for p in pkgs))
    return "\n".join(keep), pkgs


def edit_smoke_api(text: str, name: str) -> str:
    lines = text.split("\n")
    out = []
    for l in lines:
        if re.match(rf'^\s*\("{re.escape(name)}",', l):
            if not re.search(r"\),\s*(#.*)?$", l):
                raise Refused(f'tests/smoke/test_api.py has a multi-line API_CHECKS entry for "{name}" — remove it by hand, then run again.')
            continue
        out.append(l)
    text2 = "\n".join(out)
    # PAGE_ONLY = { "a", "b", ... }: drop this tool's entry, but ONLY inside that set literal (the name may appear elsewhere on purpose)
    start = text2.find("PAGE_ONLY = {")
    if start >= 0:
        end_ = text2.find("\n}", start)
        block = text2[start:end_ + 2]
        new_block = re.sub(rf'"{re.escape(name)}"\s*,?[ \t]?', "", block)
        new_block = "\n".join(l for l in new_block.split("\n") if l.strip() != "" or l == "")
        new_block = re.sub(r"\n[ \t]+\n", "\n", new_block)
        text2 = text2[:start] + new_block + text2[end_ + 2:]
    ast.parse(text2)
    return text2


def edit_knowledge_map(text: str, name: str) -> tuple[str, bool]:
    lines = text.split("\n")
    keep = [l for l in lines if not (l.startswith("|") and f"`/tools/{name}/`" in l)]
    return "\n".join(keep), len(keep) != len(lines)


def edit_compose(text: str, folder: str, name: str) -> tuple[str, list[str]]:
    """Remove mounts `<vol>:/app/data/<folder|name>` and the top-level key of a volume nothing else mounts. Returns (text, removed volumes)."""
    lines = text.split("\n")
    mount = re.compile(rf"^\s*-\s*([A-Za-z0-9_]+):/app/data/({re.escape(folder)}|{re.escape(name)})(:\w+)?\s*(#.*)?$")
    vols, keep = [], []
    for l in lines:
        m = mount.match(l)
        if m:
            vols.append(m.group(1))
            continue
        keep.append(l)
    gone = []
    for v in dict.fromkeys(vols):
        still = any(re.match(rf"^\s*-\s*{re.escape(v)}:", l) for l in keep)
        if still:
            continue
        top = [i for i, l in enumerate(keep) if l == f"  {v}:"]
        in_volumes = [i for i in top if any(k == "volumes:" for k in keep[:i])]
        if in_volumes:
            del keep[in_volumes[-1]]
            gone.append(v)
    return "\n".join(keep), gone


# ---- the plan ------------------------------------------------------------------------------------------------------------------------

def fetch_enabled(url: str, name: str):
    """True / False from the running stack, or None when it cannot be asked."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/workspace/status", timeout=2) as r:
            for p in json.loads(r.read()).get("plugins", []):
                if p.get("name") == name:
                    return bool(p.get("enabled"))
        return False
    except Exception:  # noqa: BLE001
        return None


def make_plan(repo: Path, ident: str, ignore_references: bool = False) -> Plan:
    name, folder, is_plugin = resolve(repo, ident)
    if name in HARD_PROTECTED or folder.name in HARD_PROTECTED:
        raise Refused(f"'{name}' is a core part of the platform and is never removed by this script.")
    plan = Plan(name=name, folder=folder, is_plugin=is_plugin)
    if is_plugin:
        plan.notes.append("A custom app in plugins/: removing it means deleting its folder (no image, Dockerfile or test wiring).")
        plan.review += doc_mentions(repo, name, folder)
        return plan

    docker, api, kmap, compose = repo / "Dockerfile", repo / "tests/smoke/test_api.py", repo / "KNOWLEDGE_MAP.md", repo / "docker-compose.yml"
    for f in (docker, api, kmap):
        if not f.is_file():
            raise Refused(f"{f} not found — is --repo the Toolbox root?")
    dtext, pkgs = edit_dockerfile(docker.read_text(), folder.name)
    if not pkgs:
        plan.notes.append(f"The Dockerfile has no `COPY {folder.name}/…` line for this tool (nothing to remove there).")
    plan.package = sorted(pkgs)[0] if pkgs else folder.name.replace("-", "_")
    plan.edits[docker] = dtext
    plan.edits[api] = edit_smoke_api(api.read_text(), name)
    ktext, found = edit_knowledge_map(kmap.read_text(), name)
    plan.edits[kmap] = ktext
    if not found:
        plan.notes.append("No row for this tool in the KNOWLEDGE_MAP.md tool index.")
    if compose.is_file():
        ctext, vols = edit_compose(compose.read_text(), folder.name, name)
        if ctext != compose.read_text():
            plan.edits[compose] = ctext
            yaml.safe_load(ctext)
        plan.volumes = vols
    for d in ("tests/smoke", "tests/unit"):
        for stem in sorted({plan.package, folder.name.replace("-", "_")}):
            for t in (repo / d).glob(f"test_{stem}*.py"):
                if t not in plan.deletes:
                    plan.deletes.append(t)

    if not ignore_references:
        plan.blockers = find_blockers(repo, name, folder, pkgs | {folder.name.replace("-", "_")})
    # what the tool leaves behind (never touched)
    code = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in folder.rglob("*.py"))
    for s in dict.fromkeys(re.findall(r'SqlStore\(\s*"([A-Za-z0-9_]+)"', code)):
        plan.left.append(f"Postgres schema `{s}` (tables with the tool's records). To drop it yourself: DROP SCHEMA {s} CASCADE;  — NOT run by this script")
    for s in dict.fromkeys(re.findall(r'FileCache\(\s*"([^"]+)"', code)):
        plan.left.append(f"S3 objects under the `{s}` prefix of the bucket (files the tool stored) — remove with your S3 tooling if you want them gone")
    try:
        v = (yaml.safe_load((folder / "manifest.yaml").read_text(encoding="utf-8")) or {}).get("vault") or {}
        kinds = sorted(set(v.get("read") or []) | set(v.get("write") or []))
        if kinds:
            plan.left.append(f"Vault entries of kind {', '.join(kinds)} may exist (shared with other tools?) — look at the Vault page")
    except Exception:  # noqa: BLE001
        pass
    for v in plan.volumes:
        plan.left.append(f"Docker volume `{v}` (the tool's stored files) — kept unless you pass --remove-volumes")
    plan.has_data = bool(plan.left)
    plan.review += doc_mentions(repo, name, folder)
    plan.review.append(f"Rebuild so the image no longer contains it: docker compose up -d --build   (and check requirements*.txt for packages only this tool used)")
    plan.review.append("workspace.yaml may still hold an on/off entry for it (harmless; it is ignored once the tool is gone)")
    return plan


def needs_confirm(plan: Plan, enabled) -> list[str]:
    why = []
    if enabled is True:
        why.append("the tool is currently ENABLED")
    elif enabled is None:
        why.append("the running stack could not be asked whether the tool is enabled")
    if plan.has_data:
        why.append("the tool has stored data")
    return why


def show(plan: Plan, repo: Path, enabled, confirm_reasons: list[str]) -> None:
    rel = lambda p: p.relative_to(repo)  # noqa: E731
    print(f"Tool: {plan.name}  (folder {rel(plan.folder)}{', custom app in plugins/' if plan.is_plugin else ''})\n")
    print("WILL DELETE / EDIT:")
    n = sum(1 for p in plan.folder.rglob("*") if p.is_file())
    print(f"  delete  {rel(plan.folder)}/   ({n} files)")
    for p in plan.deletes:
        print(f"  delete  {rel(p)}")
    for p in plan.edits:
        print(f"  edit    {rel(p)}")
    if plan.blockers:
        print("\nBLOCKERS — other code still uses this tool (nothing will be removed until they are gone, or use --ignore-references):")
        for b in plan.blockers[:20]:
            print(f"  ! {b}")
        if len(plan.blockers) > 20:
            print(f"  … and {len(plan.blockers) - 20} more")
    if plan.left:
        print("\nLEFT IN PLACE (never touched by this script):")
        for l in plan.left:
            print(f"  - {l}")
    if plan.review:
        print("\nREVIEW BY HAND:")
        for r in plan.review:
            print(f"  ? {r}")
    for n_ in plan.notes:
        print(f"\nNote: {n_}")
    if confirm_reasons:
        print(f"\n--apply needs --confirm {plan.name}  because: " + "; ".join(confirm_reasons) + ".")


# ---- applying ---------------------------------------------------------------------------------------------------------------------

def apply(repo: Path, plan: Plan, remove_volumes: bool) -> None:
    before = {p: p.read_text(encoding="utf-8") for p in plan.edits}
    trash = Path(tempfile.mkdtemp(prefix="remove_tool_")) / plan.folder.name
    moved_tests = []
    try:
        for p, text in plan.edits.items():
            p.write_text(text, encoding="utf-8")
        for t in plan.deletes:
            dest = trash.parent / f"_t_{t.name}"
            shutil.move(str(t), str(dest))
            moved_tests.append((t, dest))
        shutil.move(str(plan.folder), str(trash))
        # self-check: the tool is gone, the edited Python still parses, compose is still YAML
        try:
            resolve(repo, plan.name)
            raise Refused("the tool is still found after removal")
        except Refused as e:
            if "still found" in str(e):
                raise
        if (repo / "tests/smoke/test_api.py").is_file():
            ast.parse((repo / "tests/smoke/test_api.py").read_text())
        if (repo / "docker-compose.yml").is_file():
            yaml.safe_load((repo / "docker-compose.yml").read_text())
        if not plan.is_plugin and re.search(rf"^COPY\s+{re.escape(plan.folder.name)}/", (repo / "Dockerfile").read_text(), re.M):
            raise Refused("the Dockerfile still copies the tool")
    except Exception as exc:  # noqa: BLE001 - put everything back
        for p, text in before.items():
            p.write_text(text, encoding="utf-8")
        for orig, dest in moved_tests:
            if dest.exists():
                shutil.move(str(dest), str(orig))
        if trash.exists() and not plan.folder.exists():
            shutil.move(str(trash), str(plan.folder))
        raise Refused(f"removal failed its self-check ({exc}); everything was put back.") from None
    shutil.rmtree(trash.parent, ignore_errors=True)
    if remove_volumes and plan.volumes:
        for v in plan.volumes:
            r = subprocess.run(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.volume={v}"], capture_output=True, text=True)
            names = r.stdout.split() if r.returncode == 0 else []
            if not names:
                print(f"  volume {v}: not found in Docker (nothing to delete)")
            for n in names:
                d = subprocess.run(["docker", "volume", "rm", n], capture_output=True, text=True)
                print(f"  docker volume rm {n}: {'removed' if d.returncode == 0 else 'NOT removed — ' + d.stderr.strip()[:120]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Remove a Toolbox tool cleanly (dry run unless --apply).")
    ap.add_argument("tool", help="the tool's manifest name or folder name")
    ap.add_argument("--apply", action="store_true", help="really remove it (default: only show the plan)")
    ap.add_argument("--confirm", default="", help="type the tool's name to confirm (needed when it is enabled, unknown or has data)")
    ap.add_argument("--remove-volumes", action="store_true", help="also delete the tool's Docker volume(s) — its stored files are lost for good")
    ap.add_argument("--ignore-references", action="store_true", help="proceed although other code still uses the tool (it will break)")
    ap.add_argument("--url", default="http://localhost:8000", help="the running Toolbox, to check whether the tool is enabled")
    ap.add_argument("--repo", default=str(REPO))
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    try:
        plan = make_plan(repo, a.tool, a.ignore_references)
        enabled = fetch_enabled(a.url, plan.name)
        why = needs_confirm(plan, enabled)
        show(plan, repo, enabled, why)
        if not a.apply:
            print("\nDRY RUN — nothing was changed. Add --apply" + (f" --confirm {plan.name}" if why else "") + " to do it.")
            return 1 if plan.blockers else 0
        if plan.blockers:
            raise Refused("blockers above — remove those references first (or --ignore-references).")
        if why and a.confirm != plan.name:
            raise Refused(f"type the tool's name to confirm: --confirm {plan.name}")
        if a.remove_volumes and plan.volumes and a.confirm != plan.name:
            raise Refused(f"--remove-volumes deletes stored files for good: add --confirm {plan.name}")
        apply(repo, plan, a.remove_volumes)
    except Refused as exc:
        print(f"\nNothing was changed. {exc}", file=sys.stderr)
        return 1
    print(f"\nRemoved '{plan.name}'. Now: docker compose up -d --build   and   python3 -m pytest tests/unit -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
