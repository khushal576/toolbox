# LaTeX to PDF — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture and
`../KNOWLEDGE_MAP.md` for the symptom→file map.

## What this tool is
Paste LaTeX (e.g. a resume), compile it to PDF fully offline, preview it, download it.

## How it's built
- `server.py` — `/compile` (POST `{source}`) writes `main.tex` into a temp dir, runs the image's
  `pdflatex` (shell-escape off, `openin_any/openout_any=p`, 30 s timeout, up to 2 passes when LaTeX asks
  for a rerun) and returns the PDF; on failure returns 422 `{error, log}`. `/health` reports whether
  `pdflatex` exists. At most 2 compiles run at once (semaphore) and run as subprocesses, so they never
  block the single uvicorn worker.
- `ui/index.html` — editor + browser-native PDF viewer (blob URL in an `<iframe>`, so no PDF.js, no CDN).
  Source is kept in `localStorage`. `SAMPLE` is the starter resume.

## Gotchas
- TeX Live comes from the root `Dockerfile` (`apt-get install texlive-*`). Packages not in the installed
  set fail with "File `x.sty' not found" — the error panel shows it. other packages from `texlive-fonts-extra` (e.g. `fontawesome` variants, many symbol fonts) are NOT installed by default (the package is a 624 MB download, ~1.7 GB on disk); enable with `--build-arg TEX_FONTS_EXTRA=1`.
- Font Awesome: the CTAN `fontawesome` and `fontawesome5` packages are vendored in `texmf/` and installed by
  `texmf/install_fontawesome.py` (Dockerfile) — ~2 MB instead of the 1.7 GB `texlive-fonts-extra`. A document
  can load only ONE of them: `fontawesome5` raises "Incompatible version of Font Awesome already loaded" if
  `fontawesome` is also loaded. `\faLinkedinSquare` exists only in `fontawesome` (v4); in v5 it is `\faLinkedin`.
- Only `pdflatex` is wired up (no xelatex/lualatex, no bibtex/biber).
- Nothing is stored server-side; the temp dir is deleted after every compile.
