<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: LaTeX to PDF — mounted at `/tools/latex-pdf/`

Paste LaTeX (e.g. a resume), compile offline with the image's `pdflatex`, preview with the browser's built-in PDF viewer, download. See `latex-pdf/CLAUDE.md`.

| I need to change… | Go to |
|---|---|
| How a compile runs (flags, timeout, passes, sandbox env, concurrency limit) | `latex-pdf/server.py` (`_run_pass`, `compile_tex`, `_TIMEOUT`, `_SLOTS`) |
| How LaTeX errors are shown | `latex-pdf/server.py` (`_summarise`), `latex-pdf/ui/index.html` (`#errbox`) |
| The starter resume / editor / PDF preview / auto-compile | `latex-pdf/ui/index.html` (`SAMPLE`, `compile()`) |
| Which TeX packages are available | `Dockerfile` (TeX Live layer, `TEX_FONTS_EXTRA` build arg, default off) |
| Font Awesome for LaTeX (vendored, installed at build) | `latex-pdf/texmf/` (`install_fontawesome.py`, the two CTAN zips), `Dockerfile` |
