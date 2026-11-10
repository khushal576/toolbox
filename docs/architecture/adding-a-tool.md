# Adding a new tool — the tested checklist

> Moved **verbatim** from the root `CLAUDE.md` by roadmap session O3 (2026-11-10). The root keeps only the rules and an index;
> nothing was reworded. Paths in the text are repo-root relative.

## Adding a new tool

> **Since roadmap P2 most of the mechanical steps below are automated:** `python3 scripts/new_tool.py <name> "<Title>"` creates the folder from `tools/_template/`
> (steps 1, 4, 5, 9 below: package name, manifest, relative-path page, colours), adds the Dockerfile `COPY`/`touch` lines (step 10's build wiring), the smoke
> `API_CHECKS` line (step 6) and the `KNOWLEDGE_MAP.md` index row (step 8). You still do steps 2–3 and 7 yourself (the real code, colours if you want them different,
> dependencies) and write the tool's `CLAUDE.md`. The list below stays as the reference for WHY each step exists.
>
> **Removing a tool (roadmap P3):** `python3 scripts/remove_tool.py <name>` (dry run by default) reverses this list: folder, Dockerfile `COPY`/`touch`, smoke entries and tests, index row, compose volume mounts. It never touches data in
> Postgres / the Vault / S3 (it lists what stays), deletes a Docker volume only with `--remove-volumes --confirm <name>`, and refuses while other code still imports the tool or calls `/tools/<name>/`.

(Followed twice already — Encode/Decode and Subnet Calculator — this is the
tested checklist, not a guess.)

> Updated in roadmap **A2**: tools are plugins with a `manifest.yaml`; there is
> no mount list in `main.py` and no `registry.yaml`. Prefer **client-side
> (tier 1)** designs when a tool can run in the browser — they cost the server
> nothing.

1. New top-level folder for the tool's own code (its own `core`/`api`/`ui`
   equivalent — organize however fits that tool, doesn't need to mirror
   DataDiff's shape, doesn't need to be FastAPI, but it must expose an ASGI
   `app` object if it's Python/FastAPI-based so `main.py` can mount it the
   same way).
2. Its frontend calls its own API with relative paths (see above) — this is
   the one hard requirement for a page to work correctly when mounted under
   a path prefix.
3. Copy the six `:root` color variables from `theme-tokens.css` into the
   tool's own `<style>` block verbatim — this is the one thing every tool's
   palette should agree on. Everything else (status colors, tool-specific
   accents) is that tool's own call; see `theme-tokens.css`'s header for why
   this stays a copy, not a shared/served stylesheet.
4. **Give it a uniquely-named top-level Python package** — never reuse
   `core` or `api` (DataDiff Pro already owns those, grandfathered as-is).
   Namespace the tool's own code under its own folder name instead (see
   `encode-decode/` → copied into the image as `encode_decode/`, imported
   as `from encode_decode.server import app`). This is the one thing that
   actually breaks silently if skipped — two tools both exposing a top-level
   `core` package means whichever gets imported second in `main.py` wins,
   and the other tool's real code never runs.
5. Add **`<tool>/manifest.yaml`** (spec: `docs/architecture/plugin-manifest.md`):
   `name`, `title`, `description`, `icon`, `category` (`tool` or `learn` —
   `learn` cards are hidden until the home page's "Show learning tools"
   toggle), `kind: python`, `entry: <tool_package>.server:app`, `runtime`,
   `tier`, `state`, `depends_on`, `requires`, `order`. `main.py` mounts it
   automatically — **do not edit `main.py`**. If the Dockerfile copies the tool
   file-by-file, also `COPY <tool>/manifest.yaml ./<tool_package>/manifest.yaml`
   (`tests/unit` checks this).
6. Add it to `tests/smoke/test_api.py` — an `API_CHECKS` entry (read-only, no
   outside systems) or `PAGE_ONLY` — then run `python3 -m pytest tests/unit -q`
   and `scripts/smoke.sh`.
7. Add its dependencies to the root `requirements.txt` (watch for version
   conflicts with existing tools' dependencies — since everything now
   shares one Python environment, this is the real cost of the "one
   container" tradeoff; a genuine conflict is the signal to reconsider, not
   something to route around silently). If a tool needs no Python packages
   beyond what's already there (e.g. a pure client-side tool like
   Encode/Decode), this step is a no-op — nothing to add. **Since roadmap
   C1** also add the same pin line to `requirements/<runtime>.txt` for the
   tool's manifest `runtime:` (`tests/unit/test_runtimes.py` checks the pins
   match and that every package is used by some runtime), then rebuild the
   wheelhouse (`./download-wheels.sh`) if the package is new.
8. Update `KNOWLEDGE_MAP.md` with this tool's section.
9. **Add a `CLAUDE.md` inside the tool's own folder** — short, scoped to
   just that tool (what it does, where each piece of logic lives, its own
   gotchas), pointing back to this file and `KNOWLEDGE_MAP.md` for anything
   repo-wide. This is what lets a future session opened directly inside
   `<tool>/` get oriented without pulling in every other tool's context
   first. See `encode-decode/CLAUDE.md` or `subnet-calc/CLAUDE.md` for the
   shape to copy.
10. Rebuild the one image: `docker-compose up --build -d`.
