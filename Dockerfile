# =============================================================================
# Toolbox — Dockerfile
# =============================================================================
# One Dockerfile, several images (build targets, roadmap C1). Every image has the same code and the same
# plugin loader (main.py); they differ only in the libraries/system tools installed and which plugins they mount:
#   worker   background jobs of every runtime: all packages + pg_dump, no TeX (the `worker` service, roadmap C4)
#   full     everything incl. TeX in one image — only for a single-container `docker run` (default target)
#   gateway  workspace UI + proxy, no tool code — the `toolbox` service since roadmap C2
#   light    small stateless tools                       TOOLBOX_RUNTIME=light
#   data     pandas / DuckDB / DB drivers (+ Vault)       TOOLBOX_RUNTIME=data
#   pgtools  + bundled pg_dump/pg_restore/psql            TOOLBOX_RUNTIME=pgtools
#   ssh      paramiko (SSH & SFTP)                        TOOLBOX_RUNTIME=ssh
#   latex    TeX Live (LaTeX → PDF)                       TOOLBOX_RUNTIME=latex
#   datadiff DataDiff Pro as a shared service (roadmap D1) TOOLBOX_RUNTIME=datadiff
# A plugin's `runtime:` in its manifest.yaml decides which image serves it; requirements/<runtime>.txt lists
# that image's Python packages (pins identical to requirements.txt — tests/unit/test_runtimes.py).
# Build:   docker build -t toolbox .                  (full)
#          docker build --target data -t toolbox-rt-data .
# Run:     docker-compose up -d                       (gateway + one container per runtime, roadmap C2)
#
# The classic builder is used here (no BuildKit/buildx), so packages are installed in throw-away deps-*
# stages with `pip --prefix=/install` and only /install is copied into an image — the 130 MB wheelhouse
# never ends up in a final image. Note the classic builder runs every stage that comes BEFORE the target,
# so the stages are ordered cheapest-first.
# =============================================================================

# --- Stage 1: the PostgreSQL client bundle (pg_dump + pg_restore + psql) -----
# Schema Copy and Data Dumper shell out to the REAL pg_dump/pg_restore/psql. The toolbox image below is
# Debian 12 (bookworm); the stock `postgres:N` image is Debian 13 and its
# binaries do not run here, so this stage uses the `-bookworm` variant and
# copies the two binaries plus exactly the shared libraries they need
# (everything but glibc) into /opt/pgclient. They are put on LD_LIBRARY_PATH
# only for the child processes core/pgclient.py spawns.
# A pg_dump can dump any server up to its OWN major version, so keep this at
# (or above) the newest server you will copy FROM — preflight says so when a
# source is newer. Bump with: docker build --build-arg PG_CLIENT_MAJOR=19 …
# (or change the default here / `args:` in docker-compose.yml).
ARG PG_CLIENT_MAJOR=18
FROM postgres:${PG_CLIENT_MAJOR}-bookworm AS pgclient
ARG PG_CLIENT_MAJOR
RUN mkdir -p /opt/pgclient/bin /opt/pgclient/lib \
 && for b in pg_dump pg_restore psql; do cp /usr/lib/postgresql/${PG_CLIENT_MAJOR}/bin/$b /opt/pgclient/bin/; done \
 && for b in pg_dump pg_restore psql; do ldd /usr/lib/postgresql/${PG_CLIENT_MAJOR}/bin/$b | awk '/=> \//{print $3}'; done | sort -u \
    | grep -Ev '/(libc|libm|libdl|libpthread|librt|libresolv)\.so' | xargs -I{} cp -L {} /opt/pgclient/lib/

# --- Base for every image: slim Python 3.11 + env ------------------------------
FROM python:3.11-slim AS pyslim
WORKDIR /app
# No .pyc files, unbuffered logs (they show up in `docker compose logs` at once), /app importable.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# --- Application code (identical in every image) -------------------------------
FROM pyslim AS code
# --- Copy application code ---------------------------------------------------
# DataDiff Pro (tool #1) — uses the un-namespaced "core"/"api" top-level
# packages. Grandfathered as-is; any NEW tool must NOT reuse these two
# names (see encode_decode/ below for the pattern new tools should follow:
# each gets its own uniquely-named top-level package).
COPY core/ ./core/
COPY api/   ./api/
COPY ui/    ./ui/
COPY environments/ ./environments/

# Encode/Decode (tool #2) — namespaced under its own package so it can
# never collide with another tool's "core"/"api"/etc.
COPY encode-decode/server.py ./encode_decode/server.py
COPY encode-decode/manifest.yaml ./encode_decode/manifest.yaml
COPY encode-decode/ui/       ./encode_decode/ui/

# Subnet Calculator (tool #3) — same namespacing pattern.
COPY subnet-calc/server.py ./subnet_calc/server.py
COPY subnet-calc/manifest.yaml ./subnet_calc/manifest.yaml
COPY subnet-calc/ui/       ./subnet_calc/ui/

# DNS Lookup (tool #4) — same namespacing pattern.
COPY dns-lookup/server.py ./dns_lookup/server.py
COPY dns-lookup/manifest.yaml ./dns_lookup/manifest.yaml
COPY dns-lookup/ui/       ./dns_lookup/ui/

# VLAN Designer (tool #5) — same namespacing pattern.
COPY vlan-designer/server.py ./vlan_designer/server.py
COPY vlan-designer/manifest.yaml ./vlan_designer/manifest.yaml
COPY vlan-designer/ui/       ./vlan_designer/ui/

# Packet Journey (tool #6) — same namespacing pattern.
COPY packet-journey/server.py ./packet_journey/server.py
COPY packet-journey/manifest.yaml ./packet_journey/manifest.yaml
COPY packet-journey/ui/       ./packet_journey/ui/

# cURL Builder (tool #7) — same namespacing pattern.
COPY curl-builder/server.py ./curl_builder/server.py
COPY curl-builder/manifest.yaml ./curl_builder/manifest.yaml
COPY curl-builder/ui/       ./curl_builder/ui/

# HTTP Header Reference (tool #8) — same namespacing pattern.
COPY header-reference/server.py ./header_reference/server.py
COPY header-reference/manifest.yaml ./header_reference/manifest.yaml
COPY header-reference/ui/       ./header_reference/ui/

# HTTP Methods & Status Codes (tool #9) — same namespacing pattern.
COPY http-methods-status/server.py ./http_methods_status/server.py
COPY http-methods-status/manifest.yaml ./http_methods_status/manifest.yaml
COPY http-methods-status/ui/       ./http_methods_status/ui/

# Cookie Lab (tool #10) — same namespacing pattern.
COPY cookie-lab/server.py ./cookie_lab/server.py
COPY cookie-lab/manifest.yaml ./cookie_lab/manifest.yaml
COPY cookie-lab/ui/       ./cookie_lab/ui/

# DataFrame Studio (tool #11) — same namespacing pattern, but copied as a
# whole folder (not the usual two-line server.py + ui/ copy) because it has
# extra backend modules (engine.py, steps.py) alongside server.py.
COPY df-studio/ ./df_studio/

# SQL Studio (tool #12) — copied as a whole folder (not the usual two-line
# server.py + ui/ copy), same reason as df-studio above: it has extra
# backend modules now (db_engine.py, query_guard.py) that back the Run
# feature's live Postgres connection. Format/Templates/Schema autocomplete
# stay fully client-side — only Run/Connect/Export touch this backend.
COPY sql-studio/ ./sql_studio/

# Schema Map (tool #13) — whole-folder copy, same reason as df-studio/
# sql-studio above (extra backend module: db_engine.py, with more to
# follow as its build steps land). A read-only, progressive-disclosure
# table/foreign-key explorer for large Postgres schemas — its own
# connection pool, deliberately not shared with SQL Studio's.
COPY schema-map/ ./schema_map/

# Duck Lab (tool #14) — whole-folder copy, same reason as df-studio/
# sql-studio/schema-map above (extra backend module: engine.py). Loads
# CSV/JSON/XML files and queries/joins them with DuckDB; imports
# core.normalizer directly for XML parsing (see duck-lab/CLAUDE.md), so it
# must be copied after core/ above.
COPY duck-lab/ ./duck_lab/

# Orchestrator — NOT a mounted tool (no server.py, no ui/, no manifest.yaml
# entry, no main.py mount). Headless recipes that call other tools' engines
# directly (core.pipeline, duck-lab-style DuckDB reads, a one-shot Postgres
# connector) and are invoked as a one-shot process, not a web request — see
# orchestrator/CLAUDE.md. Must be copied after core/ above, same reason as
# duck-lab.
COPY orchestrator/ ./orchestrator/

# Vault (tool #15) — management page for core/vault.py's shared
# encrypted secret store. Imports core.vault directly, so must be
# copied after core/ above, same reason as duck-lab/orchestrator.
COPY vault/ ./vault/

# Data Syncer (tool #16) — whole-folder copy (engine, sync_ops, state_store,
# runner, connections modules alongside server.py). Resumable table
# copy/upsert between two Vault-saved Postgres connections; imports
# core.vault / core.postgres_conn, so must be copied after core/ above. Runs
# as a job in the `worker` service (roadmap B4).
COPY data-syncer/ ./data_syncer/

# Schema Copy (tool #17) — whole-folder copy. Copies a database's STRUCTURE
# (no rows) into a new empty database via the real pg_dump/psql from the
# 'pgclient' stage above. Imports core.db_endpoint (Vault -> connection,
# shared with data-syncer), so must be copied after core/. Runs as a job in
# the `worker` service; scripts live in S3 storage (roadmap B5).
COPY schema-copy/ ./schema_copy/

# Data Dumper (tool #18) — whole-folder copy. Takes Postgres dumps (downloadable) and restores
# them selectively, using the bundled pg_dump/pg_restore/psql above via core/pgclient.py. Dumps and
# restores run as worker jobs; dump files live in S3 storage (roadmap B5).
COPY data-dumper/ ./data_dumper/

# SSH & SFTP (tool #19) — whole-folder copy. Browse/upload/download files and run commands on servers saved
# in the Vault (kind "ssh_server"), via paramiko (already a dependency) and core/ssh_client.py (host-key
# pinning). Uploads/commands run as worker jobs and staged uploads live in S3 storage (roadmap B8); the
# browsing connection cache stays per process (recreated on demand).
COPY ssh-sftp/ ./ssh_sftp/

# Data Lake (roadmap L2) — whole-folder copy. Loads files into Vault Data tables (core/lake.py); loads run in the
# worker; reads the shared data folder (/data, mounted read-only in compose).
COPY data-lake/ ./data_lake/

# LaTeX to PDF (tool #20) — same namespacing pattern. Shells out to pdflatex from the TeX Live
# layer above; fully offline.
COPY latex-pdf/server.py ./latex_pdf/server.py
COPY latex-pdf/manifest.yaml ./latex_pdf/manifest.yaml
COPY latex-pdf/ui/       ./latex_pdf/ui/

# Plugin model + discovery (roadmap A1/A2). main.py imports it at startup and
# builds the home page and mounts from every /app/*/manifest.yaml (whole-folder
# copies above bring their manifest along; file-by-file copies list it).
COPY core_plugins/ ./core_plugins/
COPY main.py .

# Create empty __init__.py files so Python treats these as packages.
RUN touch core/__init__.py api/__init__.py encode_decode/__init__.py subnet_calc/__init__.py dns_lookup/__init__.py vlan_designer/__init__.py packet_journey/__init__.py curl_builder/__init__.py header_reference/__init__.py http_methods_status/__init__.py cookie_lab/__init__.py df_studio/__init__.py sql_studio/__init__.py schema_map/__init__.py duck_lab/__init__.py orchestrator/__init__.py orchestrator/connectors/__init__.py orchestrator/recipes/__init__.py vault/__init__.py data_syncer/__init__.py schema_copy/__init__.py data_dumper/__init__.py ssh_sftp/__init__.py latex_pdf/__init__.py data_lake/__init__.py

# --- Python packages: wheelhouse + one deps stage per image ----------------------
# wheelhouse/ (gitignored) holds pre-downloaded wheels for this exact platform/Python version — see
# ./download-wheels.sh; regenerate it after changing requirements.txt. Installing from it avoids the
# network during builds (slow connection).
FROM pyslim AS wheels
COPY requirements.txt ./
COPY requirements/ ./requirements/
COPY wheelhouse/ ./wheelhouse/

FROM wheels AS deps-light
RUN pip install --no-cache-dir --no-index --find-links=./wheelhouse --prefix=/install -r requirements/light.txt

# --- Runtime images (roadmap C1) -------------------------------------------------
FROM pyslim AS light
COPY --from=deps-light /install /usr/local
COPY --from=code /app /app
ENV TOOLBOX_ROLE=runtime TOOLBOX_RUNTIME=light
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8080 --workers ${TOOLBOX_WEB_WORKERS:-1}"]

# --- datadiff (roadmap D1): DataDiff Pro as a shared stateless service (light + xmltodict) ------------------------
FROM wheels AS deps-datadiff
RUN pip install --no-cache-dir --no-index --find-links=./wheelhouse --prefix=/install -r requirements/datadiff.txt

FROM pyslim AS datadiff
COPY --from=deps-datadiff /install /usr/local
COPY --from=code /app /app
ENV TOOLBOX_ROLE=runtime TOOLBOX_RUNTIME=datadiff
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8080 --workers ${TOOLBOX_WEB_WORKERS:-1}"]

# --- gateway (roadmap C2): workspace UI + proxy to the runtime images; runs no tool code ---------------------
FROM wheels AS deps-gateway
RUN pip install --no-cache-dir --no-index --find-links=./wheelhouse --prefix=/install -r requirements/gateway.txt

FROM pyslim AS gateway
COPY --from=deps-gateway /install /usr/local
COPY --from=code /app /app
# web role: home page, switches, status; every python tool proxied to TOOLBOX_RUNTIME_URLS / TOOLBOX_SINGLETON_URL
ENV TOOLBOX_ROLE=web
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8080 --workers ${TOOLBOX_WEB_WORKERS:-1}"]

FROM wheels AS deps-ssh
RUN pip install --no-cache-dir --no-index --find-links=./wheelhouse --prefix=/install -r requirements/ssh.txt

FROM pyslim AS ssh
COPY --from=deps-ssh /install /usr/local
COPY --from=code /app /app
ENV TOOLBOX_ROLE=runtime TOOLBOX_RUNTIME=ssh
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8080 --workers ${TOOLBOX_WEB_WORKERS:-1}"]

FROM wheels AS deps-pgtools
RUN pip install --no-cache-dir --no-index --find-links=./wheelhouse --prefix=/install -r requirements/pgtools.txt

FROM pyslim AS pgtools
COPY --from=deps-pgtools /install /usr/local
COPY --from=pgclient /opt/pgclient /opt/pgclient
COPY --from=code /app /app
ENV TOOLBOX_ROLE=runtime TOOLBOX_RUNTIME=pgtools
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8080 --workers ${TOOLBOX_WEB_WORKERS:-1}"]

FROM wheels AS deps-data
RUN pip install --no-cache-dir --no-index --find-links=./wheelhouse --prefix=/install -r requirements/data.txt

FROM pyslim AS data
COPY --from=deps-data /install /usr/local
COPY --from=code /app /app
ENV TOOLBOX_ROLE=runtime TOOLBOX_RUNTIME=data
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8080 --workers ${TOOLBOX_WEB_WORKERS:-1}"]

# --- worker (roadmap C4): background jobs of every runtime — all Python packages + pg_dump, NO TeX Live ---------
# Jobs are syncs, dumps/restores, schema copies, SSH uploads/commands; none renders LaTeX, so the worker no
# longer drags TeX Live around (before C4 it ran the 1.2 GB `full` image).
FROM wheels AS deps-full
RUN pip install --no-cache-dir --no-index --find-links=./wheelhouse --prefix=/install -r requirements.txt

FROM pyslim AS worker
COPY --from=deps-full /install /usr/local
COPY --from=pgclient /opt/pgclient /opt/pgclient
COPY --from=code /app /app
CMD ["python", "-m", "core.jobs.worker"]

# --- TeX Live: base for the latex and full images ---------------------------------
# Starts exactly like the pre-C1 image (FROM python:3.11-slim, WORKDIR, then TeX) so its big apt layer stays
# cached across rebuilds — TeX Live is a ~600 MB download on a slow line.
FROM python:3.11-slim AS tex
WORKDIR /app
# --- TeX Live (LaTeX to PDF tool) --------------------------------------------
# Offline pdflatex for latex-pdf/. Kept before the pip layer so rebuilds that only change app code
# reuse it. texlive-fonts-extra (fontawesome5, marvosym, ...) is a 624 MB download / ~1.7 GB on disk,
# so it is opt-in:
#   docker compose build --build-arg TEX_FONTS_EXTRA=1
ARG TEX_FONTS_EXTRA=0
RUN apt-get update \
 && apt-get install -y --no-install-recommends texlive-latex-base texlive-latex-recommended \
        texlive-latex-extra texlive-fonts-recommended texlive-plain-generic lmodern \
 && if [ "$TEX_FONTS_EXTRA" = "1" ]; then apt-get install -y --no-install-recommends texlive-fonts-extra; fi \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man

# Font Awesome for LaTeX resumes: the CTAN `fontawesome` and `fontawesome5` packages (~2 MB together,
# vendored in latex-pdf/texmf/) instead of the ~1.7 GB texlive-fonts-extra. Installed into TEXMFLOCAL
# and registered with updmap. Note LaTeX itself refuses to load both in one document (fontawesome5
# errors) — a resume must pick one.
COPY latex-pdf/texmf/ /tmp/texmf/
RUN python /tmp/texmf/install_fontawesome.py /usr/local/share/texmf /tmp/texmf/fontawesome5.zip /tmp/texmf/fontawesome.zip \
 && mktexlsr \
 && updmap-sys --enable Map=fontawesome5.map --enable Map=fontawesome.map \
 && rm -rf /tmp/texmf
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

FROM wheels AS deps-latex
RUN pip install --no-cache-dir --no-index --find-links=./wheelhouse --prefix=/install -r requirements/latex.txt

FROM tex AS latex
COPY --from=deps-latex /install /usr/local
COPY --from=code /app /app
ENV TOOLBOX_ROLE=runtime TOOLBOX_RUNTIME=latex
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8080 --workers ${TOOLBOX_WEB_WORKERS:-1}"]

# --- full: everything in one image (default target) --------------------------------
# NOT run by compose (since roadmap C4). The image to `docker run` when you want every tool in ONE container
# (then TOOLBOX_WEB_WORKERS=1, see below). The only image besides `latex` that carries TeX Live.
FROM tex AS full
COPY --from=deps-full /install /usr/local
COPY --from=pgclient /opt/pgclient /opt/pgclient
COPY --from=code /app /app
EXPOSE 8080
# --workers: N processes since roadmap B9 (TOOLBOX_WEB_WORKERS, compose default 4). Singleton plugins (sql-studio,
# schema-map) run in the `singletons` service and are proxied (TOOLBOX_SINGLETON_URL); without that variable
# (a bare `docker run`) they are mounted in-process — then keep TOOLBOX_WEB_WORKERS=1. See CLAUDE.md "Standing rule".
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8080 --workers ${TOOLBOX_WEB_WORKERS:-1}"]
