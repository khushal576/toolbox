#!/usr/bin/env python3
"""
scripts/new_tool.py — create a new Toolbox tool from tools/_template (roadmap P2).

    python3 scripts/new_tool.py my-tool "My Tool" --icon 🧩 --description "What it does" [--runtime light|data] [--order N] [--dry-run]

What it does (all-or-nothing: every edit is prepared and checked first; nothing is written if any check fails):
  1. copies tools/_template/{manifest.yaml,server.py,ui/,CLAUDE.md,KNOWLEDGE_MAP.md} to <repo>/<name>/ and fills the __TOOL_*__ placeholders
     (escaped for the file type: YAML string / HTML text / plain);
  2. Dockerfile: three COPY lines (server.py, manifest.yaml, ui/) above the `>>> scripts/new_tool.py` marker + `<package>/__init__.py` on the `RUN touch` line;
  3. tests/smoke/test_api.py: one API_CHECKS line (a new tool must be classified — test_every_tool_is_classified);
  4. tests/smoke/test_<package>.py from tools/_template/smoke_test.py;
  5. KNOWLEDGE_MAP.md: one row in the tool index.
Then you edit server.py / ui/index.html, fill in the tool's CLAUDE.md, and rebuild: `docker compose up -d --build`.
Every line it adds contains the tool's folder name, so scripts/remove_tool.py (roadmap P3) can take them out again.
Standard library only (+ PyYAML for the final self-check, which Toolbox already requires).
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import keyword
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^(?!.*--)[a-z][a-z0-9-]{0,39}[a-z0-9]$")   # a letter first (the package must be an identifier), no trailing or doubled hyphen
TEMPLATE_FILES = ["manifest.yaml", "server.py", "CLAUDE.md", "KNOWLEDGE_MAP.md", "ui/index.html"]   # README.md / smoke_test.py are not copied into the tool
DOCKERFILE_MARKER = "# >>> scripts/new_tool.py adds new tools' COPY lines ABOVE this marker"


class Refused(Exception):
    """A problem with the input or the repo; nothing has been written."""


def package_of(name: str) -> str:
    return name.replace("-", "_")


def _check_text(label: str, value: str, limit: int) -> str:
    value = value.strip()
    if not value or len(value) > limit:
        raise Refused(f"{label} must be 1–{limit} characters.")
    if any(ord(c) < 32 for c in value) or "\\" in value or '"""' in value or "'''" in value:
        raise Refused(f"{label} may not contain newlines, backslashes or triple quotes.")
    return value


def _reserved(repo: Path) -> set[str]:
    sys.path.insert(0, str(repo)) if str(repo) not in sys.path else None
    try:
        from core_plugins.loader import _reserved_names     # the same list the plugin loader uses (Toolbox packages + stdlib)
        return _reserved_names(repo)
    except Exception:                                        # a stripped-down repo (tests) without core_plugins
        return {p.name for p in repo.iterdir()} | set(getattr(sys, "stdlib_module_names", ()))


def _fill(text: str, rel: str, vals: dict[str, str]) -> str:
    """Replace the placeholders. Titles / descriptions are escaped for where they land."""
    free = {"__TOOL_TITLE__", "__TOOL_DESCRIPTION__", "__TOOL_ICON__"}
    for token, v in vals.items():
        if token in free and rel.endswith(".yaml"):
            v = json.dumps(v, ensure_ascii=False)            # a quoted YAML string: colons, # and quotes cannot break the manifest
        elif token in free and rel.endswith(".html"):
            v = html.escape(v, quote=True)
        elif token in free and rel.endswith(".py"):
            v = json.dumps(v, ensure_ascii=False)[1:-1]       # inside a "…" literal (and a docstring): quotes are backslash-escaped
        text = text.replace(token, v)
    return text


def _insert_before(lines: list[str], marker: str, new: list[str], what: str) -> list[str]:
    idx = [i for i, l in enumerate(lines) if l.startswith(marker)]
    if len(idx) != 1:
        raise Refused(f"cannot find the anchor for {what} ({marker!r}) exactly once — edit that file by hand, or restore the marker.")
    return lines[:idx[0]] + new + lines[idx[0]:]


def plan(repo: Path, name: str, title: str, description: str, icon: str, runtime: str, order: int) -> dict:
    """Everything that would be written: {path: new full text}. Raises Refused before anything is touched."""
    if not NAME_RE.match(name):
        raise Refused("name must be a lowercase slug starting with a letter: letters, digits and single '-' (not at the end), 2–41 characters (for example my-tool).")
    pkg = package_of(name)
    if not pkg.isidentifier() or keyword.iskeyword(pkg):
        raise Refused(f"'{name}' does not make a valid Python package name ('{pkg}').")
    if pkg in _reserved(repo) or name in _reserved(repo):
        raise Refused(f"'{name}' would collide with an existing Toolbox / standard-library package or folder.")
    if runtime not in ("light", "data"):
        raise Refused("--runtime must be light or data (use `data` only if the tool needs pandas / DuckDB / database drivers).")
    title, description = _check_text("title", title, 60), _check_text("description", description, 300)
    icon = _check_text("icon", icon, 8)
    tool_dir, template = repo / name, repo / "tools" / "_template"
    if tool_dir.exists():
        raise Refused(f"{tool_dir} already exists.")
    if not template.is_dir():
        raise Refused(f"template folder {template} not found.")
    docker, smoke_api, kmap = repo / "Dockerfile", repo / "tests/smoke/test_api.py", repo / "KNOWLEDGE_MAP.md"
    for f in (docker, smoke_api, kmap):
        if not f.is_file():
            raise Refused(f"{f} not found — is --repo the Toolbox root?")
    dtext = docker.read_text()
    if f"COPY {name}/" in dtext or f"./{pkg}/" in dtext or f" {pkg}/__init__.py" in dtext:
        raise Refused(f"the Dockerfile already mentions '{name}' / '{pkg}'.")
    if (repo / "tests/smoke" / f"test_{pkg}.py").exists():
        raise Refused(f"tests/smoke/test_{pkg}.py already exists.")

    vals = {"__TOOL_NAME__": name, "__TOOL_PACKAGE__": pkg, "__TOOL_TITLE__": title, "__TOOL_DESCRIPTION__": description,
            "__TOOL_ICON__": icon, "__TOOL_RUNTIME__": runtime, "__TOOL_ORDER__": str(order), "__TOOL_DATE__": dt.date.today().isoformat()}
    out: dict[Path, str] = {}
    for rel in TEMPLATE_FILES:
        src = template / rel
        if not src.is_file():
            raise Refused(f"template file {src} is missing.")
        out[tool_dir / rel] = _fill(src.read_text(encoding="utf-8"), rel, vals)
    out[tool_dir / "__init__.py"] = ""
    out[repo / "tests/smoke" / f"test_{pkg}.py"] = _fill((template / "smoke_test.py").read_text(encoding="utf-8"), "smoke_test.py", vals)

    # Dockerfile: COPY lines above the marker, package __init__ on the `RUN touch` line
    lines = dtext.split("\n")
    lines = _insert_before(lines, DOCKERFILE_MARKER, [
        f"COPY {name}/server.py ./{pkg}/server.py", f"COPY {name}/manifest.yaml ./{pkg}/manifest.yaml", f"COPY {name}/ui/ ./{pkg}/ui/", ""], "the Dockerfile COPY lines")
    touch = [i for i, l in enumerate(lines) if l.startswith("RUN touch ")]
    if len(touch) != 1:
        raise Refused("cannot find the single `RUN touch …__init__.py` line in the Dockerfile.")
    lines[touch[0]] = lines[touch[0]].rstrip() + f" {pkg}/__init__.py"
    out[docker] = "\n".join(lines)

    # smoke API_CHECKS line
    stext = smoke_api.read_text().split("\n")
    i = [k for k, l in enumerate(stext) if l.startswith("API_CHECKS = [")]
    if len(i) != 1:
        raise Refused("cannot find `API_CHECKS = [` in tests/smoke/test_api.py exactly once.")
    stext.insert(i[0] + 1, f'    ("{name}", "GET", "/health", None, "application/json"),   # scaffolded by scripts/new_tool.py (roadmap P2)')
    out[smoke_api] = "\n".join(stext)

    # KNOWLEDGE_MAP index row (append to the Tool index table)
    ktext = kmap.read_text().split("\n")
    head = [k for k, l in enumerate(ktext) if l.startswith("| Tool | Mounted at")]
    if len(head) != 1:
        raise Refused("cannot find the 'Tool index' table in KNOWLEDGE_MAP.md.")
    end_ = head[0] + 1
    while end_ < len(ktext) and ktext[end_].startswith("|"):
        end_ += 1
    ktext.insert(end_, f"| {title} | `/tools/{name}/` | [`{name}/KNOWLEDGE_MAP.md`]({name}/KNOWLEDGE_MAP.md) | [`{name}/CLAUDE.md`]({name}/CLAUDE.md) |")
    out[kmap] = "\n".join(ktext)
    return out


def selfcheck(repo: Path, name: str) -> None:
    """The new manifest must load and the loader must see exactly one new tool."""
    sys.path.insert(0, str(repo))
    from core_plugins.loader import load_manifest              # noqa: E402

    m = load_manifest(repo / name / "manifest.yaml")
    if m.name != name or m.module != f"{package_of(name)}.server":
        raise Refused(f"the generated manifest is not what was asked for: {m.name} / {m.entry}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Create a new Toolbox tool from tools/_template.")
    ap.add_argument("name", help="slug, e.g. my-tool (becomes the folder, /tools/<name>/ and the package my_tool)")
    ap.add_argument("title", help='shown on the home page, e.g. "My Tool"')
    ap.add_argument("--description", default="TODO: describe this tool in one sentence")
    ap.add_argument("--icon", default="🧩")
    ap.add_argument("--runtime", default="light", help="light (default) or data")
    ap.add_argument("--order", type=int, default=1000, help="display order; built-in tools use 10–200")
    ap.add_argument("--repo", default=str(REPO), help="Toolbox root (default: this checkout)")
    ap.add_argument("--dry-run", action="store_true", help="show what would be written and change nothing")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    try:
        out = plan(repo, a.name, a.title, a.description, a.icon, a.runtime, a.order)
        if a.dry_run:
            print("Dry run — would write:")
            for p in sorted(out):
                print(f"  {'edit ' if p.exists() else 'new  '} {p.relative_to(repo)}")
            return 0
        before = {p: p.read_text(encoding="utf-8") for p in out if p.exists()}          # to restore on failure
        created_dirs = [d for d in {p.parent for p in out if not p.exists()} if not d.exists()]
        try:
            for p, text in out.items():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
            selfcheck(repo, a.name)
        except Exception as exc:                                                         # noqa: BLE001 - never leave a half-made tool behind
            for p in out:
                if p in before:
                    p.write_text(before[p], encoding="utf-8")
                elif p.exists():
                    p.unlink()
            for d in sorted(created_dirs, key=lambda x: len(x.parts), reverse=True):
                try:
                    d.rmdir()
                except OSError:
                    pass
            raise Refused(f"the new tool did not pass its self-check ({exc}); everything was put back.") from None
    except Refused as exc:
        print(f"Nothing was changed. {exc}", file=sys.stderr)
        return 1
    print(f"Created {a.name}/ — package {package_of(a.name)}, runtime {a.runtime}.\n")
    print("Next steps:")
    print(f"  1. edit {a.name}/server.py and {a.name}/ui/index.html (relative fetch paths; state outside the process)")
    print(f"  2. new Python packages? add the pin to requirements.txt AND requirements/{a.runtime}.txt, then ./download-wheels.sh")
    print(f"  3. fill in {a.name}/CLAUDE.md and {a.name}/KNOWLEDGE_MAP.md")
    print("  4. docker compose up -d --build   (the tool appears on the home page; switch it on in Settings if needed)")
    print(f"  5. python3 -m pytest tests/unit -q  &&  scripts/smoke.sh   (tests/smoke/test_{package_of(a.name)}.py was created for you)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
