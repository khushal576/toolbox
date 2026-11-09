<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: Schema Map — mounted at `/tools/schema-map/`

A **read-only**, progressive-disclosure explorer for large Postgres
schemas — connect, and see tables + foreign-key relationships as an
interactive Cytoscape.js graph, without ever rendering more than what's
currently expanded (a naive "graph every table at once" is unreadable
past a few dozen tables regardless of layout algorithm — this tool
exists specifically for schemas with hundreds to ~1000 tables). Built
for two motivations: seeing which tables cluster together before a
monolith → microservice split, and seeing everything transitively
connected to a table before migrating it. Editability (manual groups,
manual non-FK links) is deliberately out of scope for the current build
— see `schema-map/CLAUDE.md` for the full reasoning trail (Neo4j and
Kùzu were both seriously considered and rejected in favor of `networkx`,
given the actual confirmed scale).

**Build status**: Steps 1–3 of a 6-step plan are done (connection,
data-fetching, basic graph rendering), plus Step 6 (lazy per-table
column loading on click) pulled forward, plus a visual polish pass
(zoom controls, per-schema node coloring, a row-count/uniform node-size
toggle), plus a Filter feature (pick a table, see everything within 1–2
hops, with the rest of the graph genuinely hidden, not faded) — progressive
disclosure via connected components (Step 4) and interactive hub-collapse
(Step 5) are not yet built. See `schema-map/CLAUDE.md`'s "Build status"
section before assuming any of those exist.

| If you need to change...                                              | Go to |
|-------------------------------------------------------------------------|-------|
| The connection pool (connect/disconnect/status, idle reaper)            | `schema-map/db_engine.py`'s own `_POOL` — a `core.pooled_postgres.PooledPostgresConnection`, genuinely separate instance from `sql-studio/db_engine.py`'s, smaller pool (`pool_max_size=2`) |
| Which catalog queries run, adding a new introspection query             | `schema-map/introspection_postgres.py` — `get_schemas()`, `get_tables()`, `get_foreign_keys()`, `get_graph()`, `get_table_columns()`; every query is a direct port of an already-verified `sql-studio/ui/index.html` `SHOW_COMMANDS` query, extended to also select each FK's real target schema (`to_schema`) — see "Known non-obvious behavior" below |
| The `/schemas`, `/graph`, `/table/{schema}/{table}` backend routes      | `schema-map/server.py` |
| The schema picker, Connection panel UI                                  | `schema-map/ui/index.html` — `loadSchemaList()`, `applyConnectionStatus()` (Connection panel markup/behavior deliberately mirrors SQL Studio's) |
| How the graph is drawn (node sizing, edge styling, colors, layout)      | `schema-map/ui/index.html` — `renderGraph()`, `sizeFor()`, `buildSchemaColorMap()` — see `schema-map/CLAUDE.md` for why node sizing uses `sqrt` not linear scaling, and why schema colors are deterministic, not random |
| The column detail panel, zoom controls                                  | `schema-map/ui/index.html` — `openTableDetail()`/`closeDetailPanel()` (note the `cy.resize()` call — see `schema-map/CLAUDE.md`), `btnZoomIn`/`btnZoomOut`/`btnZoomFit` handlers |
| The detail panel's per-column FK relationship list                      | `schema-map/ui/index.html` — `buildRelationshipsHtml()`, built from cached `lastGraphData.foreign_keys`, no new endpoint |
| The table-connection Filter (hop depth, blast-radius list, hide/show)   | `schema-map/ui/index.html` — `computeNeighborhood()`/`buildAdjacency()` (undirected BFS over `foreign_keys`), `applyFilter()`/`clearFilter()` (`cy.hide()`/`.show()`, not a fade), `renderFilterResults()` |
| Table search / jump-to-table                                            | `schema-map/ui/index.html` — `populateTableSearch()`, `jumpToTable()` (`#canvasSearch`, native `<input list>`/`<datalist>`) |
| Hub ranking, orphan-table list                                          | `schema-map/ui/index.html` — `computeTableDegrees()` (reuses `buildAdjacency()`), `renderInsights()` (`#detInsights`) |
| FK-column badges in the columns table, the Relationships section        | `schema-map/ui/index.html` — `getTableForeignKeys()` (shared by both), `buildRelationshipsHtml()` |
| Clusters (create/rename/delete, table picker, cluster canvas, seed)     | `schema-map/ui/index.html` — data layer: `loadClusters()`/`saveClusters()`/`createCluster()`/etc.; UI: `switchMode()`, `renderClusterList()`, `renderClusterWorkspace()`, `renderClusterPicker()`, `renderClusterCanvas()` (separate `clusterCy` instance) |
| Explore graph "Color by Cluster" (multi-cluster pie split)              | `schema-map/ui/index.html` — `computeNodeColoring()`, `applyNodeColoring()`, `renderClusterColorLegend()` |
| Projects/Versions (storage + entry-point UI, v2 design Phase A)         | `schema-map/project_store.py` (Postgres schema `schema_map` via `core/state/sqlstore.py` since B6; SQLite standalone), endpoints in `schema-map/server.py`, `#projectsScreen`/`#detProject`/`openProject()`/`switchToVersion()` in `schema-map/ui/index.html` — see `schema-map/CLAUDE.md`'s "v2 design, Phase A" |
| Paste-and-load Project origin — 3 queries, tables/FKs required, columns optional (v2 design Phase B) | `introspection_postgres.TABLES_QUERY_SQL`/`FOREIGN_KEYS_QUERY_SQL`/`COLUMNS_QUERY_SQL`, `GET /paste-query`, `populatePasteQuery()`/`parsePastedArray()` in `schema-map/ui/index.html` — see `schema-map/CLAUDE.md`'s "v2 design, Phase B" |
| Table detail panel columns with no live connection                     | `schema-map/ui/index.html` — `openTableDetail()` branches on `isConnected`, falls back to `lastGraphData.columns`; `renderColumnsAndRelationships()` shared by both paths |
| Editor mode (from-scratch projects, add/edit tables/columns/FKs)        | `schema-map/ui/index.html` — `renderEditorCanvas()` (separate `editorCy` instance, LEFT sidebar `#editorTableCard` for per-table detail), `addTableToProject()`/`addColumnToProject()`/`addForeignKeyToProject()`/`changeColumnTypeInProject()` and their delete counterparts, `switchMode()`'s `skipRender` option — see `schema-map/CLAUDE.md`'s "v2 design, Phase C" |
| Editor's columns list / Add-FK dropdowns for an existing (non-from-scratch) table | `schema-map/ui/index.html` — `ensureColumnsLoadedFor()`, called from `selectEditorTable()` and `populateAddFkToColumn()` |
| Editor's zoom controls, canvas fit-zoom clamping                        | `schema-map/ui/index.html` — `updateEditorZoomLevel()`, `btnEditorZoomIn`/`Out`/`Fit` handlers (operate on `editorCy`, never the shared `cy`) |
| Editor's type picker (parameterized types: varchar length, numeric precision/scale) | `schema-map/ui/index.html` — `PARAM_TYPE_CONFIG`, `parseTypeForEditing()`, `buildTypeFromParams()`, `updateTypeParamUI()`, `resolveSelectedType()` |
| Version comparison, plain-English diff (no DataDiff Pro call anymore) | `schema-map/ui/index.html` — `diffSnapshots()`, `describeSnapshotDiff()`, `populateCompareSelects()`, `openCompareModal()` — fully local, no network call for the diff itself; see `schema-map/CLAUDE.md`'s "AI Assist, Phase H" |
| Full-schema DDL export — "Export Full DDL" button, whole structure every time, never a delta (CREATE TABLE + NOT NULL/UNIQUE/PRIMARY KEY/FOREIGN KEY only, v2 design Phase E) | `schema-map/ui/index.html` — `generateDDL()`, `buildCreateTableSQL()`, `quoteIdent()`; PK/unique detection added to `_COLUMNS_SQL`/`COLUMNS_QUERY_SQL` in `introspection_postgres.py` — see `schema-map/CLAUDE.md`'s "v2 design, Phase E". Renamed from "Export DDL" after real user confusion with the row below — see `schema-map/CLAUDE.md`'s "Export DDL renamed" note. |
| Migration DDL between two versions (only the delta, with DROPs for removals, v2 design Phase F) | `schema-map/ui/index.html` — `generateMigrationDDL()`, wired to `#btnGenerateMigrationDdl` inside the Compare-versions modal; shares `buildCreateTableSQL()`/`pkConstraintName()`/`uniqueConstraintName()`/`fkConstraintName()` with `generateDDL()` — see `schema-map/CLAUDE.md`'s "v2 design, Phase F" |
| "Save as Version" saving an incomplete snapshot for a never-clicked table | `schema-map/ui/index.html` — `ensureAllColumnsLoadedForSave()`, called from `btnSaveVersion`'s handler; backend: `GET /columns`, `introspection_postgres.get_all_columns()`/`_ALL_COLUMNS_SQL` — see `schema-map/CLAUDE.md`'s "AI Assist, Phase H" follow-up |
| Deleting a project | `schema-map/project_store.py` — `delete_project()`; `DELETE /projects/{project_id}` in `server.py`; the ✕ button in `loadProjectsScreen()`'s row template |
| Auto-created "v0" initial version | `schema-map/ui/index.html` — `saveVersion()` (extracted, reusable), `autoSaveInitialVersionIfNeeded()`, called from scratch/paste project creation and the first successful `loadGraph()` |
| Comparing the current (unsaved) state against any saved version | `schema-map/ui/index.html` — `CURRENT_STATE_SENTINEL`, `resolveCompareSide()`, `populateCompareSelects()`'s "Current (unsaved)" option |
| Graph node positions staying stable across re-renders, "Reset Layout" | `schema-map/ui/index.html` — `nodePositions` (ONE shared map for both Explore and Editor — see next bullet for why), `capturePositions()`/`applyStoredPositions()`/`layoutPreservingPositions()`, `btnResetLayout`/`btnEditorResetLayout` |
| Detecting a server-side DB connection timeout (the idle reaper) | `schema-map/ui/index.html` — the `setInterval` polling `GET /status`, `handleServerSideDisconnect()`; root cause is the `idle_timeout_seconds` passed to `schema-map/db_engine.py`'s `PooledPostgresConnection` (shared mechanics in `core/pooled_postgres.py`) |
| Static HTML export (single self-contained file, view-only, no backend needed) | `schema-map/ui/index.html` — `buildStaticExportHtml()`, `jsonForInlineScript()`, wired to `#btnExportStaticHtml` — see `schema-map/CLAUDE.md`'s "Static HTML export" section |
| Editor's 🔗 (FK) / 🔑 (UNIQUE) column badges | `schema-map/ui/index.html` — `renderEditorColumnsList()`'s `fkOutCols`/`fkInCols`; re-rendered by `btnConfirmAddFk` and the FK-row delete handler too, not just table selection |
| The cross-schema-FK Cytoscape crash fix (Explore + Editor) | `schema-map/ui/index.html` — `edgeSafeForeignKeys()`, called from `renderGraph()` and `renderEditorCanvas()` — see `schema-map/CLAUDE.md`'s "v2 design, Phase F" |
| Dependency enforcement for delete (RESTRICT — blocks, doesn't cascade or confirm) | `schema-map/ui/index.html` — `findDependentForeignKeys()`/`findDependentTableForeignKeys()`, `deleteColumnFromProject()`/`deleteTableFromProject()` (both return `{ error }` and change nothing when blocked) — see `schema-map/CLAUDE.md`'s "v2 design, Phase G" |

### Known non-obvious behavior

- **No column data is fetched for any table until it's individually
  clicked** — true since Step 2's queries were first written
  (`introspection_postgres.get_tables()` deliberately stops at
  `{schema_name, table_name, row_estimate, total_size}`), and clicking a
  node now actually surfaces those columns via a separate per-table
  fetch (`GET /table/{schema}/{table}`, `openTableDetail()` in
  `ui/index.html`). Don't "simplify" a future change by folding columns
  into the bulk `/graph` query — see `schema-map/CLAUDE.md`.
- **`row_estimate` is `pg_class.reltuples` (a fast estimate), not
  `COUNT(*)`** — same metric SQL Studio's "Show Table Sizes" uses, and
  for the same reason (hundreds of full-table-scan counts just to draw
  a graph would be slow). A never-`ANALYZE`d table reports `-1`, clamped
  to `0` before node sizing.
- **`cytoscape.js` loads as a classic `<script>` tag, not inside the
  `type="module"` script** — it's a UMD build (global `cytoscape`
  function), not an ES module like SQL Studio's esm.sh CodeMirror
  imports. See `schema-map/CLAUDE.md` for why the load-order isn't a
  race condition despite that split.
- **Node IDs are `schema.table`, not just `table`** — same cross-schema
  name-collision case already verified for SQL Studio's schema-fetch
  feature (`public.orders` vs. `analytics.orders`) applies here too;
  namespacing by schema in the node id avoids two different tables
  colliding into one graph node.
- **A foreign key's target can be in a different schema than its source
  — `introspection_postgres.py` must select the target's real schema
  (`to_schema`), never assume it matches `from_schema`.** A real bug
  found and fixed while building the Filter feature (which builds node
  ids from this data and would silently traverse to the wrong node
  otherwise) — verified against a genuine cross-schema FK added to the
  dev database. See `schema-map/CLAUDE.md` for the full story.
- **A single-schema `/graph` fetch must include cross-schema FKs from
  BOTH directions** — `_FOREIGN_KEYS_SQL_ONE_SCHEMA` matches the
  selected schema on either the FROM or TO side (`OR`, not just FROM).
  An earlier version only matched FROM, silently dropping any FK where
  a table OUTSIDE the selected schema references INTO it — found when
  the Filter feature showed a table's outgoing dependencies but not its
  incoming ones while a single schema was selected. See
  `schema-map/CLAUDE.md` for the full story and why this one's easy to
  reintroduce by accident.
- **The table detail panel shows FK relationships now, not just
  columns** — below the columns table, a "Relationships" section lists
  every FK this table takes part in as a clickable `column → other
  table.column` link, split into "References" (outgoing) and
  "Referenced by" (incoming). Built client-side from the already-cached
  graph data, not a new backend call. Node labels also moved above each
  node (`text-valign: "top"`), not below.
- **"Degree" in the Insights card counts distinct connected tables, not
  raw FK rows** — two FK columns on the same table pointing at the same
  other table count as one coupling relationship, not two. See
  `schema-map/CLAUDE.md` for the verified real numbers (`orders`/`users`
  top the hub list at degree 6, `employees`/`analytics.daily_stats` are
  the orphans).
- **Clusters are stored in browser `localStorage`, scoped per connected
  database (`schema_map_clusters:<host>:<port>:<database>`), not on the
  server** — a deliberate tradeoff (won't survive a browser data clear
  or work across machines), not an oversight. A table can belong to
  multiple clusters at once; membership is pure manual judgment,
  independent of the FK graph. The cluster canvas is a SEPARATE
  Cytoscape instance (`clusterCy`) from the Explore graph's `cy` — never
  confuse the two. See `schema-map/CLAUDE.md`'s "Fifth pass" for the
  full design rationale and the two real headless-browser-testing
  gotchas found while verifying this feature (collapsed `<details>`
  elements aren't clickable via automation; module-scope JS vars aren't
  reachable from `page.evaluate` without deliberately capturing them).
- **`switchMode("explore")` can trigger a real graph rebuild now, not
  just a resize** — it rebuilds when there's no `cy` yet (a from-
  scratch project's Explore view) or `editorStructureDirty` is set (you
  edited structure in Editor mode). This must stay guarded on
  `lastGraphData` being non-null, and `showGraphPlaceholder()` must keep
  passing `{ skipRender: true }` — both guards exist because of two
  real bugs found while building Editor mode (a startup crash, and a
  just-destroyed graph silently redrawing itself). See
  `schema-map/CLAUDE.md`'s "v2 design, Phase C" for the full story
  before touching this function.
- **Clusters is scoped to `project.id`** (`clustersStorageKey()`), not to
  a live connection's `host:port:database` — that was the ORIGINAL
  scheme and had a real bug: a from-scratch/paste-imported project has
  no connection at all, so Clusters silently did nothing for them, and
  two different projects on the same database would have shared one
  cluster set. `currentConnectionKey` (the old key source) no longer
  exists. Filter/Insights/Color-by needed no separate fix — they all
  just read `loadClusters()`, so this one function fixed them together.
- **Editor's columns/Add-FK-dropdowns need `ensureColumnsLoadedFor()`
  for any table that didn't come from scratch** — `lastGraphData.columns`
  is correctly empty for a live-connected or columns-skipped
  paste-imported table (columns are only ever fetched lazily on click
  elsewhere in this tool), so Editor must lazily fetch them itself the
  first time it needs them for such a table, or its columns list and FK
  dropdowns show nothing for real, pre-existing tables. Verified against
  the real dev database: `public.orders` correctly shows all 12 real
  columns once this fires. `keepEditorLabelSizeConstant()` is a
  DELIBERATELY separate small function from Explore's
  `keepLabelSizeConstant()`, not that one reused — see
  `schema-map/CLAUDE.md`'s "v2 design, Phase C" second checkpoint for
  why sharing it would silently misfire.
- **Editor's canvas fit-zoom must stay clamped to 100% max** on initial
  render and on every "Fit to screen" click — `cose`'s own auto-fit
  zooms in aggressively (observed: a 1-3-table canvas hit the
  `maxZoom: 8`/800% ceiling on load) when there are only a few nodes,
  which is exactly Editor's common case while building a schema by
  hand. `maxZoom: 8` itself stays as-is — only the automatic fit is
  clamped, a deliberate manual zoom-in can still go further.
- **The type picker's dropdown holds base type names only, never a
  baked-in length/precision** (`character varying`, not
  `character varying(255)`) — `PARAM_TYPE_CONFIG` drives small
  dedicated parameter box(es) next to the picker instead
  (`character varying`/`character`: one length box; `numeric`: two,
  precision + scale). Switching a column's type via the select always
  RESETS those boxes to the newly-chosen type's own defaults
  (`updateTypeParamUI()`) — an old varchar length carried over into a
  numeric field would be actively wrong, not just stale.
- **SUPERSEDED — version comparison no longer calls DataDiff Pro at
  all.** This used to require passing `list_keys` via `environment_yaml`
  to avoid DataDiff Pro's auto-detect only trying up to 2-field key
  combinations (a `foreign_keys` row needs 3). That whole concern went
  away once Compare switched to its own purpose-built comparator
  (`diffSnapshots()`) — no generic list-pairing algorithm is involved at
  all anymore, each list is walked with exact keys this tool controls
  directly. See `schema-map/CLAUDE.md`'s "AI Assist, Phase H" for the
  reasoning behind dropping DataDiff Pro here.
- **Projects is now the app's real entry point** — `#projectsScreen`
  shows before `#mainLayout` (Connection/Explore/Clusters, everything
  that existed before this phase), and opening an existing project loads
  its latest saved version directly, with no live database connection
  required at all. Clusters IS now scoped to `project.id` (see above) —
  but a saved version snapshot still does NOT include cluster data, so
  reopening an old version doesn't restore what was clustered at that
  point; clusters live independently of version history for now. See
  `schema-map/CLAUDE.md`'s "v2 design, Phase A"/"Phase C" for the full
  picture.
- **The paste-import queries must stay byte-identical in shape/filtering
  to the live-fetch queries they mirror** — `TABLES_QUERY_SQL`/
  `FOREIGN_KEYS_QUERY_SQL` wrap `_TABLES_SQL_ALL`/`_FOREIGN_KEYS_SQL_ALL`
  directly (the literal same strings, not copies), specifically so the
  two paths can never silently diverge. Verified once already (byte-
  identical output against the same database, both queries) — re-verify
  the same way if either underlying query ever changes. This is
  deliberately TWO separate queries, not one combined one — split apart
  after the owner asked for a simpler staged paste flow (see
  `schema-map/CLAUDE.md`'s "v2 design, Phase B" for the full story).
- **"Color by Cluster" splits a multi-cluster table's node into an exact
  pie chart, one equal wedge per cluster** (Cytoscape's built-in
  `pie-N-background-color`/`-size`, verified as an exact 50/50 split for
  a 2-cluster table) — not a single arbitrary color. Toggling Color-by
  mode recolors in place (`applyNodeColoring()`) without rebuilding the
  graph or losing pan/zoom/filter state, unlike the Node-size toggle.
  See `schema-map/CLAUDE.md`'s "Sixth pass" for the full design.
- **The Filter feature's traversal is undirected and hides, not fades**
  — the owner explicitly confirmed both: "both directions" (what a
  table references AND what references it both count toward its
  neighborhood) and a true hide ("show only nodes which comes in filter
  other does not show"), not the more common highlight/dim pattern. A
  node's reported hop distance is its shortest path from the selected
  table (plain BFS, first-visit wins) — don't reintroduce a
  directed-only or fade-based version without re-confirming that's
  actually what's wanted now.
- **Table labels are held to a constant on-screen size regardless of
  zoom** (`keepLabelSizeConstant()`) — cytoscape scales font size with
  the rest of the graph's geometry by default, which reads as
  disorienting text growth while zooming in. Past 150 tables in the
  current view, no persistent labels are drawn at all (hover tooltip
  only) — a stopgap for "the whole loaded scope renders at once," not a
  substitute for real progressive disclosure (Step 4, not built yet).
  Raised from an original 60 after a real production schema (70 tables,
  single schema) hit both this threshold AND `buildSchemaColorMap`'s
  one-schema-one-color behavior at once, which together looked like a
  "grid of unlabeled dots" bug but wasn't — see `schema-map/CLAUDE.md`
  for the full investigation. See also `schema-map/CLAUDE.md` for a
  real bug found while building the constant-size behavior itself (a
  clamp floor that silently broke the guarantee at high zoom) and why
  `min-zoomed-font-size` was removed rather than kept alongside the
  fix — the two approaches directly contradict each other.
- **DDL export's `is_unique` checks `pg_index` (`indisunique`), not
  `pg_constraint`** — a real, common pattern is `CREATE UNIQUE INDEX`
  run directly rather than declared as a table constraint, and that's
  invisible in `pg_constraint` entirely. Found on the dev fixture:
  `customers.email` is enforced by a plain unique index (missed by an
  earlier `pg_constraint`-only version of this query), `users.email` by
  an actual UNIQUE constraint (works either way). `indpred`/`indexprs
  IS NULL` excludes partial/expression unique indexes — a partial
  unique index (soft-delete pattern) doesn't mean the column is unique
  across all rows. Only a column that's the SOLE key of a single-column
  unique index is reported; composite `UNIQUE(a, b)` isn't
  representable by this per-column model and is correctly left out
  rather than incorrectly split into two single-column `UNIQUE`s. See
  `schema-map/CLAUDE.md`'s "v2 design, Phase E" for the full story,
  including why a PK's own backing index being unique too required an
  explicit suppression in `generateDDL()` to avoid a redundant
  `UNIQUE ... PRIMARY KEY` pair.
- **DDL export only emits a FOREIGN KEY when BOTH endpoint tables were
  actually exported** — `lastGraphData.foreign_keys` is bulk-loaded for
  a whole schema, but `lastGraphData.columns` (what actually determines
  whether a table gets a `CREATE TABLE`) may only cover a subset (a
  cluster, or just the tables someone clicked in Editor). Emitting an
  `ALTER TABLE ... FOREIGN KEY` for a table this script never creates
  isn't runnable SQL — `generateDDL()` tracks created tables and filters
  on both endpoints before emitting each FK. Caught during real-database
  verification, not assumed away — see `schema-map/CLAUDE.md`'s "v2
  design, Phase E".
- **FIXED (was previously known-but-unfixed): loading a single schema
  via Explore, or opening Editor mode, could crash Cytoscape if that
  schema has an incoming cross-schema FK** (`Can not create edge ...
  with nonexistent source`) — reproduced on the dev fixture by loading
  just `public` when `analytics.orders` references `public.customers`
  (`_FOREIGN_KEYS_SQL_ONE_SCHEMA` deliberately includes cross-schema FKs
  when either end matches the selected schema, but the OTHER end's node
  was never added to the graph). First found while testing Phase E and
  left unfixed as out-of-scope — turned out to also be the real cause of
  a separate Editor-mode bug report (`editorCy` never gets assigned when
  its construction throws, so NO click on ANY node works afterward, not
  just "the second one" — easy to misdiagnose as a click-handling bug
  when the actual failure is upstream, in canvas construction). Fixed by
  `edgeSafeForeignKeys()`, shared by `renderGraph()` and
  `renderEditorCanvas()` — see `schema-map/CLAUDE.md`'s "v2 design,
  Phase F".
- **Migration DDL's constraint names are a best-effort guess, not a
  read of the real database** — `pkConstraintName()`/
  `uniqueConstraintName()`/`fkConstraintName()` match Postgres's own
  DEFAULT auto-generated naming (`<table>_pkey` /
  `<table>_<column>_key` / `<table>_<column>_fkey`), used for BOTH
  `generateDDL()`'s `ADD CONSTRAINT` names and `generateMigrationDDL()`'s
  `DROP CONSTRAINT IF EXISTS` names — chosen because this tool never
  captures a live database's REAL constraint name, only whether a
  column is PK/unique/FK. If a real constraint was given an explicit
  custom name, the generated DROP won't match it; every migration DDL
  block says so in its own header comment. A table being dropped
  entirely never gets a separate DROP CONSTRAINT for its own FKs —
  `DROP TABLE` removes them for free, verified directly.
- **Deleting a column or table now uses RESTRICT semantics, not
  cascade** — `deleteColumnFromProject()` used to only clean up FKs
  where the deleted column was the SOURCE (`fk.from_column`); a column
  that was some OTHER table's FK TARGET (`fk.to_column`) was left
  dangling — still rendered as a valid edge, still emitted by both DDL
  generators as a `FOREIGN KEY` referencing a now-nonexistent column.
  The FIRST fix cascaded both directions (mirroring
  `deleteTableFromProject()`) with a confirm dialog scoped to the
  cross-table case — that version was reported as intermittently not
  asking on a second, independently-referenced column, investigated
  hard (reproduced the exact sequence three different ways, never
  once failed) and never conclusively explained. Rather than keep
  chasing it, this was redesigned to match real Postgres's own default
  (`RESTRICT`): both `deleteColumnFromProject()` and
  `deleteTableFromProject()` now return `{ error }` and change NOTHING
  when a dependency exists — no cascade, no confirm-with-cascade
  dialog, just a hard block via `alert()` naming exactly what needs to
  be removed first. This also removes the entire class of bug the
  confirm version might have had — there's no "cascade automatically"
  branch left for a race/timing issue to hide in.
  `findDependentTableForeignKeys()` (whole-table version) deliberately
  excludes self-referencing FKs (e.g.
  `categories.parent_id -> categories.category_id`) — the table
  disappearing takes a self-reference with it consistently, only an
  EXTERNAL table's dependency blocks.
- **"Save as Version" now bulk-loads any table's columns it's missing
  before saving, for a live connection** — `ensureAllColumnsLoadedForSave()`.
  Before this, a table nobody had individually clicked in Editor/Explore
  got saved with ZERO columns recorded, silently — not a display bug, a
  genuinely incomplete snapshot. Found because a LATER version
  comparison looked broken (a real column removal didn't show up,
  because the baseline version never captured that column existing at
  all — confirmed directly from the raw stored version data, not
  assumed). Only fills GAPS — a table that already has columns loaded
  (from a click, or an Editor edit) is never touched, so this can't
  clobber an in-progress edit with a live re-read. Zero extra cost when
  there's nothing missing (every table already loaded, or `isConnected`
  is false for a from-scratch/paste-import project) — the new `GET
  /columns` bulk endpoint only gets called when there's an actual gap.
  Same underlying category of bug as Phase E's `user_roles`-shows-one-
  column DDL export issue, surfacing through a different action.
- **Compare's diff direction is A → B, always** — the older/baseline
  side belongs in the A select, the newer/target side in B, because
  "added" in the result means "new in B" and "removed" means "gone from
  B." When "Current (unsaved)" was added as a compare option, the FIRST
  version defaulted A=Current (the newest possible state) and B=the
  saved version — backwards, which silently inverted every Added/Removed
  label in the result (a genuinely NEW table read as "Removed table
  ...", found and fixed during verification, not assumed correct
  on the first try). Correct default: A=most recent saved version,
  B=Current — reads as "what have I changed since my last save."
- **Graph node positions persist across re-renders now — `cose` used to
  reshuffle the same data on every reload — AND Explore/Editor share
  ONE position map, not two.** Two separate maps
  (`explorePositions`/`editorPositions`) was the first version, reversed
  fast: the owner pointed out the same table jumping to a different
  spot just from switching modes was disorienting, since both canvases
  show the same underlying structure. `nodePositions` (one `Map` keyed
  by node id) remembers positions for both now — verified directly:
  Explore and Editor render the same 26-table live fixture at
  sub-pixel-identical positions the FIRST time Editor is entered, no
  drag or manual sync needed. `layoutPreservingPositions()` LOCKS every
  node with a remembered
  position (Cytoscape's `.lock()` — excludes it from being moved by a
  layout while still letting the layout account for it when placing
  everything else) before running `cose`, so only genuinely NEW nodes
  get auto-placed. Both `cytoscape({...})` constructors changed their
  `layout:` from `"cose"` (auto-runs on construction, would undo the
  locking) to `"preset"` (does nothing automatically — the explicit
  `layoutPreservingPositions()` call right after construction is what
  actually places things). "↻ Reset Layout" is the one deliberate way to
  get a genuinely fresh arrangement, since nothing does that on its own
  anymore. Verified with real captured positions, not eyeballed
  screenshots: identical data re-rendered at sub-pixel-exact same
  positions; adding a third table left the first two bit-for-bit
  unchanged and placed the new one at a real, non-overlapping position.
- **Node SIZE is shared between Explore/Editor now too, not just
  position** — found right after fixing positions, same underlying
  "should look the same" ask. Explore scales node diameter by row count
  (`buildSizeFor()`, sqrt-scaled 28-88px, or uniform 46px depending on
  the "Node size" radio); Editor used to hardcode a fixed 46/46
  regardless. `buildSizeFor(tables)` is now a shared function both
  `renderGraph()` and `renderEditorCanvas()` call (previously inline
  only inside `renderGraph()`), and Editor's node style changed from
  hardcoded `46`/`46` to `"data(size)"`/`"data(size)"`, matching
  Explore. `currentSizeMode()` already reads the radio directly from the
  DOM, so no new wiring was needed to share that part. Verified: zero
  size differences across all 26 real dev-fixture tables (which have
  genuine row-count variation, 28-88px, not a degenerate same-size case).
- **A lost DB connection is only ever discovered via polling, never
  instantly** — `schema-map/db_engine.py`'s idle reaper (20 min) runs
  server-side with no way to push a notification to the frontend, so
  `setInterval`-based `GET /status` polling (every 60s, only while
  `isConnected` is true) is the only detection mechanism; there will
  always be up to ~60s of stale "Connected" badge after the server
  actually closes the connection — confirmed directly (badge stayed
  "Connected" immediately after a real server-side disconnect, only
  flipped after the next poll tick). `handleServerSideDisconnect()`
  deliberately does NOT call `applyConnectionStatus()` — that function's
  disconnected branch wipes the canvas to the placeholder via
  `switchMode("explore")`, which is right for clicking Disconnect but
  wrong for a background timeout: Editor mode doesn't need a live
  connection once loaded, and Explore's already-rendered graph is still
  valid to keep looking at. Only the Connection panel itself updates.
- **Any literal `</script>` inside a JS template-literal string embedded
  in this page's own `<script>` block will silently break the WHOLE
  app, not just the feature that put it there** — the HTML parser looks
  for the raw closing-tag byte sequence anywhere in a script element's
  text content, including inside a string literal or a `//` comment; it
  has no concept of JavaScript syntax at all. `buildStaticExportHtml()`
  (the static export feature) generates a template containing real
  `<script>...</script>` tags as HTML markup CONTENT for the OUTPUT
  file — found and fixed before ever shipping: write the closing tag as
  `<\/script>` wherever it needs to appear inside the template's own
  source (the backslash keeps the HTML parser from matching it while
  still evaluating to a real `</script>` at runtime, which the
  standalone output file genuinely needs). Any embedded DATA that might
  itself contain that sequence needs the same defense a different way —
  see `jsonForInlineScript()`, which escapes `<` in JSON before
  embedding it, for exactly that case. Check both any time a template
  embeds another HTML document's markup, not just embedded data.
