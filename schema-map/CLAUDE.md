# Schema Map — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

A **read-only**, progressive-disclosure explorer for large, poorly-
documented Postgres schemas — connect, see tables and foreign-key
relationships as an interactive graph, without ever rendering more than
what's currently expanded. Built for two concrete motivations: (1)
planning a monolith → microservice split needs to see which tables are
tightly interconnected vs. isolated, not infer it from scattered `\d`
output; (2) before migrating a table, seeing everything transitively
connected to it prevents a class of migration bug (moving a table
without its real dependencies).

**Editability (manual groups, manual non-FK links) is deliberately out
of scope for now** — the owner explicitly scoped the first build to
read-only exploration only; that's a separate future phase, not an
oversight. See the plan this tool was built from
(`/home/cygnet/.claude/plans/i-want-a-sql-glistening-dawn.md` at the time
of writing, though plan files don't persist long-term — the reasoning
below is the durable record) for the full back-and-forth that led here,
condensed:
- Started as "just visualize the FK graph." A naive force-directed
  layout of hundreds-to-1000 tables is unreadable regardless of layout
  algorithm — the real problem is progressive disclosure, not a better
  renderer.
- Considered Neo4j once editability came up (naming groups, adding
  manual links for relationships that exist in practice but were never
  enforced as real FKs) — a real graph database makes that natural.
  Then considered Kùzu (an embedded, no-server graph database, genuinely
  analogous to DuckDB) as a lighter alternative.
- **Settled on neither.** At the confirmed actual scale (hundreds to
  ~1000 tables, at most 2-hop traversal depth), a real graph database's
  architectural advantages (built for millions-scale graphs) never pay
  for themselves — its fixed per-query overhead (connection/session
  setup, query planning, an FFI boundary for Kùzu specifically) would
  very likely exceed the actual computation time at this scale.
  `networkx` (plain Python, in-process, rebuilt fresh from Postgres on
  each request, no persistence layer) is genuinely faster and lighter
  *at this specific scale* — not a compromise, the actually-correct
  choice given the numbers.

## Build status

Built so far (Steps 1–3 of the plan's sequence):
- **Step 1** — connection scaffolding, reusing SQL Studio's exact
  Connection-panel UX (collapsed by default, host/port/database/username
  in `localStorage`, password never persisted, collapses to a status
  line once connected) and `db_engine.py` idiom (own global `STATE`,
  `psycopg_pool`, credential-pre-validation before opening the pool,
  20-minute idle reaper).
- **Step 2** — `introspection_postgres.py` (direct ports of already-
  verified SQL Studio `SHOW_COMMANDS` queries — Show Schemas, Show
  Tables + Show Table Sizes joined, Show Foreign Keys — deliberately
  fetching NO column data), `GET /schemas` and `GET /graph?schema=X`
  endpoints.
- **Step 3** — Cytoscape.js (CDN, cdnjs, classic `<script>` tag — it's a
  UMD build, not an ES module, unlike SQL Studio's esm.sh CodeMirror
  imports) renders whatever `/graph` returns as a force-directed
  (`cose` layout) graph. This step proves the pipeline end-to-end; it
  deliberately does NOT yet solve "hundreds of tables at once looks like
  a hairball" — that's Step 4 (progressive disclosure via connected
  components) and Step 5 (interactive hub-collapse), not built yet.
- **Step 6, pulled forward** — click a node, see its real columns
  (`GET /table/{schema}/{table}`, fetched only for the clicked table,
  same lazy-loading principle as everything else here) in a right-side
  detail panel. Built ahead of Steps 4/5 because it's independently
  useful and doesn't depend on progressive disclosure landing first —
  the owner asked for it directly after seeing Step 3 render.
- **Polish pass** (owner feedback after seeing Step 3 render for real):
  zoom controls (+/−/fit-to-screen buttons and a live zoom-percentage
  readout — cytoscape already supports scroll-to-zoom/drag-to-pan by
  default, but neither is discoverable without a visible affordance),
  per-schema node coloring (a fixed 10-color categorical palette,
  deterministically assigned by sorted schema name — see
  `SCHEMA_COLOR_PALETTE`/`buildSchemaColorMap()` — with an auto-shown
  legend once 2+ schemas are in the current graph), and a node-size mode
  toggle ("by row count" — the original sqrt-scaled behavior — vs.
  "uniform," for when you want to see pure FK structure without volume
  competing for attention). The toggle re-renders from a cached
  `lastGraphData` instead of re-fetching — changing how something
  already-fetched is *displayed* shouldn't cost a network round-trip.
- **Second polish pass** (owner feedback after using the first one):
  label readability — a near-opaque white box behind each table name
  (`text-background-color`/`-opacity`/`-shape`/`-padding`) so an FK
  edge line crossing behind the text no longer merges with the letters;
  a hover tooltip (`showNodeTooltip()`/`#nodeTooltip`) showing table
  name, schema, row count, and size on mouseover, separate from the
  small persistent labels; and **labels held to a constant on-screen
  size regardless of zoom** (`keepLabelSizeConstant()`, `BASE_FONT_SIZE`)
  — cytoscape scales font size together with node geometry by default,
  which the owner correctly flagged as disorienting (text visibly
  growing every time you zoom in). See "Things that will bite you"
  below for the real bug found and fixed while building this (an
  overly defensive `Math.max()` floor that silently broke the
  constant-size guarantee at high zoom) and for why an *earlier*
  attempt at this same request (`min-zoomed-font-size`, shrink-to-hide
  on zoom-out) was removed rather than kept alongside the fix — the two
  approaches directly contradict each other.

- **Filter (a migration blast-radius view, built ahead of Steps 4/5)** —
  the owner asked, after using the graph for real: "which tables are
  directly connected to `orders`, or two degrees down, and via which
  columns." A new sidebar Filter card lets you pick a table + a depth (1
  or 2 hops) and get a **true hide, not a fade/highlight** — everything
  outside the chosen neighborhood is `.hide()`d from the Cytoscape
  instance, not just dimmed, per the owner's explicit answer ("when
  filter show only nodes which comes in filter other does not show").
  Traversal is **undirected** (the owner's confirmed answer: "both
  directions" — what a table references AND what references it both
  count), a plain BFS over an adjacency map built from `foreign_keys`
  (`computeNeighborhood()`/`buildAdjacency()` in `ui/index.html`), so a
  node's reported hop distance is its shortest path from the selected
  table, not double-counted if reachable multiple ways. The sidebar also
  lists every connection found, grouped by hop distance, each row
  showing the actual FK column pair (`orders.customer_id →
  customers.id`, not just the two table names) and clickable to open
  that table's column detail panel. This directly depended on the
  cross-schema-FK fix below landing first — see "Things that will bite
  you."
- **Third polish pass** (owner feedback after using the Filter card for
  real): a **Relationships section in the table detail panel** —
  clicking any node now shows, below its columns, every FK it takes
  part in as a clickable `column → other_schema.other_table.column`
  link, grouped into "References" (this table's own FK columns pointing
  out) and "Referenced by" (other tables' FK columns pointing in) —
  `buildRelationshipsHtml()` in `ui/index.html`, built from the already-
  cached `lastGraphData.foreign_keys` (no new endpoint, no new network
  call). The owner's own words: clicking a table showed its columns but
  gave no way to tell *which* column was a foreign key or what it
  pointed at — this closes that gap directly in the panel you're
  already looking at, instead of only in the separate Filter card's
  connection list. Also: node labels moved from below the node to above
  it (`text-valign: "top"`, `text-margin-y: -6`, was `"bottom"`/`4`),
  and the Filter feature now **force-shows labels on whatever small
  subset it filters down to**, regardless of what the full unfiltered
  graph's `LABEL_VISIBLE_THRESHOLD` decided — a filtered neighborhood is
  never more than a handful of tables (the owner's own observation:
  "we never have more than 10 dependency in one or 2 hop"), so there's
  no clutter reason to keep labels off just because the *original*
  full-graph view had too many tables to show them all. See `applyFilter()`/
  `clearFilter()` and the new `currentShowLabels` module-level variable.
- **Fourth pass — four "quick win" improvements, scoped by the owner
  from a list of my own suggestions before any code was written**:
  1. **Table search** (`#canvasSearch`, top-left over the graph canvas,
     map-search-bar styling) — a native `<input list>`/`<datalist>`
     type-ahead over every table in the current graph, deliberately not
     a custom dropdown widget (free keyboard nav/filtering from the
     browser, zero new dependency). Picking a result or pressing Enter
     calls `jumpToTable()`: centers/fits the graph on that node
     (`cy.animate({fit:...})`), opens its detail panel, and — the
     owner's own ask — pre-fills the Filter card's table picker too, so
     finding a table and tracing its dependencies chain together. If
     the target table is currently hidden by an active filter,
     `jumpToTable()` clears the filter first (fitting to a hidden
     element does nothing visible, so this isn't optional).
  2. **Insights card** (`#detInsights`, sidebar, between Schema and
     Filter) — "Most connected tables" (top `TOP_HUBS_COUNT` = 8 by
     degree) and "Orphan tables" (zero FK connections at all), both
     from `computeTableDegrees()`. "Degree" is the count of *distinct*
     neighboring tables, not raw FK-row count — a table with two FK
     columns pointing at the same other table (`orders` →
     `user_addresses` via both `billing_` and `shipping_address_id`) is
     one coupling relationship for this purpose, not two. Verified live:
     `public.orders`/`public.users` top the hub list at degree 6 each,
     and the orphan list correctly finds exactly the two zero-FK
     fixtures the original plan called out (`employees`,
     `analytics.daily_stats`). Every row is clickable → `jumpToTable()`.
  3. **FK columns marked directly in the columns table** — a small 🔗
     badge next to any column that's part of a FK, either this table's
     own outgoing reference or the target of another table's incoming
     one (tooltip distinguishes which). Reading the Relationships
     section below used to be the only way to know a column was a FK
     at all; now it's visible without scrolling.
  4. **Refactor enabling #3**: `buildRelationshipsHtml(nodeData)` was
     split into `getTableForeignKeys(nodeData)` (returns
     `{outgoing, incoming}`) + `buildRelationshipsHtml(outgoing,
     incoming)`, so the Relationships section and the column badges
     share one filter over `lastGraphData.foreign_keys` instead of two
     that could silently drift apart. If you ever add a third
     FK-derived view, call `getTableForeignKeys()` again rather than
     re-filtering `lastGraphData.foreign_keys` by hand.

- **Fifth pass — Clusters**: the one item from the original plan's
  "explicitly deferred" list that the owner explicitly asked to bring
  back in, scoped through its own dedicated design discussion before any
  code (not folded into a quick-win). User-defined, freely-editable
  table groupings for planning a monolith → microservice split —
  deliberately independent of the FK graph itself (a table can belong to
  any number of clusters, or none; membership is pure human judgment,
  not inferred). Key design decisions, each made explicitly rather than
  assumed:
  - **Persistence: browser `localStorage`, not a server-side store** —
    scoped to `schema_map_clusters:<host>:<port>:<database>`
    (`clustersStorageKey()`/`currentConnectionKey` in `ui/index.html`,
    set in `applyConnectionStatus()`), so switching databases never
    mixes one schema's clusters into another's. Chosen over a backend
    file/DB store *knowingly* — it won't survive a browser data clear or
    work across machines, which was accepted as a real tradeoff, not an
    accident. If that ever stops being acceptable, treat it as a fresh
    decision, not a silent upgrade to a server-side store.
  - **Entry point: an in-page "Explore/Clusters" mode toggle**
    (`#modeToggle` in the header, `switchMode()`), not a real new browser
    tab — the two modes share the same connection and `lastGraphData`,
    and switching back to Explore costs only a `cy.resize()` because the
    Explore graph (`cy`) is never destroyed when hidden, just its
    container's `display` is toggled. Gated on a graph actually being
    *loaded* (`renderGraph()`/`showGraphPlaceholder()`), not merely
    "connected" — Clusters mode reads `lastGraphData` directly and has
    no fetch of its own.
  - **A table can be in multiple clusters** — `tableIds: []` arrays, no
    exclusivity, no partitioning.
  - **A separate, deliberately plain Cytoscape instance for the cluster
    canvas** (`clusterCy`, distinct from the Explore graph's `cy`) —
    labeled boxes (`width/height: "label"`, auto-sized to text), no
    size-by-volume, no schema coloring, since none of that matters for a
    clustering decision. Shows only the active cluster's member tables
    plus the real FK lines where BOTH endpoints are members (an induced
    subgraph, same principle as the Filter feature's hide/show). Single
    click on a node removes it from the cluster — no confirmation, since
    it's a one-click-reversible action (the table just flips back to
    "+ Add" in the picker).
  - **Seed-from-hub**: reuses `computeNeighborhood()` (the exact BFS the
    Filter feature already has) to pre-populate a new cluster from a
    chosen table's 1–2 hop neighborhood, which you then prune/extend by
    hand — directly built on the owner's own observation that
    well-connected tables are natural cluster starting points (same
    insight the Insights hub ranking already surfaces).
  - Verified end-to-end with a headless-Chrome (puppeteer-core against
    the system's `google-chrome`) script, not just `curl`/Node
    simulation — this is the first schema-map feature that's genuinely
    only testable by driving real DOM interaction (mode switching,
    `<details>` collapse state, localStorage). Two real test-script bugs
    were caught and fixed along the way (clicking inside a collapsed
    `<details>` silently does nothing; module-scope JS variables like
    `cy`/`lastGraphData` aren't reachable from `page.evaluate` unless a
    test deliberately captures them) — worth remembering before writing
    another browser-driven test for this tool.
- **Sixth pass — Color by Cluster**: the visual payoff of Clusters —
  the owner asked to see cluster membership directly on the Explore
  graph, "same as the image but now colour will be cluster colour." A
  new "Color by: Schema / Cluster" radio (next to the existing Node
  size toggle, `#colorModeSchema`/`#colorModeCluster`) recolors nodes by
  which cluster(s) they belong to instead of which schema they're in.
  Since a table can be in several clusters at once, a single solid
  color isn't always honest — the owner explicitly asked whether a
  50/50 split (their words: "half red half green") was possible for a
  table in 2 clusters, confirming the design before it was built. The
  answer is Cytoscape.js's own built-in pie-chart node background
  (`pie-size`, `pie-N-background-color`/`-size` for N=1..`MAX_PIE_SLICES`
  = 8) — no custom canvas drawing. `computeNodeColoring()` returns a
  solid `color` for schema mode, an unclustered table (`UNCLUSTERED_COLOR`,
  a neutral gray), or a table in exactly one cluster; for 2+ clusters it
  returns `pie` wedge data instead, each cluster getting an equal share
  (`100 / count`%). `applyNodeColoring()` is the one function that
  actually pushes this onto the live `cy` instance via `.data()`
  updates — deliberately NOT a full `renderGraph()` rebuild, since color
  never affects layout, so switching Color-by mode keeps your current
  pan/zoom and any active Filter view instead of resetting them (unlike
  the Node-size toggle, which genuinely does need cose to re-run).
  Called in three places: right after `renderGraph()` builds `cy`, on
  the radio's own `change` event, and when switching back to Explore
  from Clusters mode (membership may have just changed there). Verified
  live: a table added to two clusters renders as an exact 50.000%/50.000%
  split of each cluster's color, an unclustered table shows the neutral
  gray, and switching back to Schema mode correctly zeroes out the pie
  fields (`pie1Size`/`pie2Size` → `"0%"`) rather than leaving stale
  wedges from a previous coloring. The cluster color legend
  (`renderClusterColorLegend()`, `#clusterColorLegend`) and the schema
  legend are mutually exclusive — never shown at once, matching the
  mutually-exclusive radio itself. The hover tooltip also shows which
  cluster(s) a table is in, when that data is present
  (`nodeData.clusterNames` in `showNodeTooltip()`).
- **v2 design, Phase A — Projects + Versions (backend AND frontend now
  built and verified end-to-end).** This is the foundation of a much
  larger planned expansion (Editor mode, DDL export — see
  `[[schema-map-v2-design]]` memory for the full multi-session design
  conversation this came from) — turning Schema Map from a read-only
  live-DB viewer into a real offline-capable schema *design* tool.
  - `project_store.py` — SQLite at `/app/data/schema-map/projects.db`,
    on a Docker named volume (`schema_map_data` in `../docker-compose.yml`)
    so it survives image rebuilds — **verified with an actual
    `--force-recreate`**, not assumed. Deliberately a SEPARATE database
    from whatever Postgres the owner connects to explore/design — this
    one only ever holds Schema Map's own memory of its projects.
  - **Every version is a complete, independent snapshot, never a diff.**
    This was an explicit, deliberated decision (not a default): it's
    what makes deleting any one version always safe, regardless of
    order — nothing else can structurally depend on it. The storage
    cost of that independence is absorbed by gzip-compressing each
    snapshot, not by diffing — verified: a synthetic 500-table snapshot
    compressed to 7.2% of its raw JSON size. Diffing was considered and
    rejected specifically because deleting a middle version would then
    either break later versions or need a "repair the chain" step,
    contradicting the owner's requirement that delete never cascades.
  - `server.py` — endpoints: `POST/GET /projects`, `GET /projects/{id}`,
    `POST/GET /projects/{id}/versions`, `GET/DELETE /versions/{id}`. All
    SQLite calls go through `asyncio.to_thread` — this whole toolbox
    runs `--workers 1` (one shared process for every tool, see repo root
    `CLAUDE.md`), so a blocking sqlite3 call on the event loop would
    stall every other tool's requests too, not just Schema Map's.
  - **`ui/index.html` — Projects is now the real entry point.**
    `#projectsScreen` shows before anything else (`init()`, the former
    `loadInitialStatus()`); `#mainLayout` (everything that existed
    before this phase — Connection, Explore, Clusters, all of it) stays
    hidden until a project is opened. A brand-new project starts at the
    Connection card exactly like the app always has; **opening an
    EXISTING project loads its latest saved version straight into the
    graph with zero live connection** — verified live: reopening a
    project after going "back to all projects" (which explicitly
    disconnects) shows the full graph while `/status` still reports
    disconnected. That's the actual point of Projects owning the
    schema instead of a live connection owning it.
  - A new always-visible sidebar card (`#detProject`, above Connection,
    shown regardless of Explore/Clusters mode) holds the current
    project's name/origin, a "← All Projects" back button (which
    disconnects and returns to the picker), a labeled "Save as Version"
    action, and the version history list — reusing the Cluster list's
    row styling (`.cluster-item` etc.) rather than new CSS.
  - Verified end-to-end in a real headless-Chrome run: create project →
    connect → load graph → save v0 → back to projects (confirmed
    disconnected) → reopen (confirmed graph loads with NO reconnect) →
    save v1 → confirmed newest-first ordering → delete v0 → confirmed
    v1 completely unaffected.
  - **Not yet built**: rescoping Clusters (and Filter/Insights/Color-by)
    from their current `host:port:database` localStorage keys to
    `project.id` (deferred to Phase C, once from-scratch projects exist
    and truly have no `host:port:database` to key off); the from-scratch
    origin (Phase C); the Editor mode itself; DDL export. The version
    snapshot itself is currently just `{tables, foreign_keys}` — it does
    NOT include Clusters yet, consistent with
    Clusters not being project-scoped yet either. See the
    `[[schema-map-v2-design]]` memory for the full phase breakdown.
- **v2 design, Phase B — the paste-and-load Project origin, TWO
  separate queries (tables, foreign keys), not one combined query.**
  For when there's no direct database access at all (private network,
  no credentials to hand over) — the owner runs two self-contained
  queries themselves, one at a time, in whatever Postgres client they
  have, pasting each JSON result back into its own box on the "New
  Project — Paste Query Results" card next to the direct-database one.
  - **This started as ONE combined query** (CTEs + `json_build_object`
    producing the whole `{tables, foreign_keys}` object in a single
    round trip) — the owner explicitly asked for it to be split into a
    staged, two-query flow instead, after a garbled-looking render
    turned out (once actually reproduced screenshot-for-screenshot) to
    NOT be reproducible with either the combined query or a live
    connection — the real fix wasn't a bug fix, it was simplifying the
    ask itself: two plain `json_agg(row_to_json(...))` queries are less
    SQL for an unfamiliar client to choke on per step than one query
    combining two aggregates, and a bad paste in one step now names
    that step specifically instead of leaving one ambiguous failure to
    debug across a whole combined blob.
  - `introspection_postgres.TABLES_QUERY_SQL` /
    `FOREIGN_KEYS_QUERY_SQL` — each wraps `_TABLES_SQL_ALL` /
    `_FOREIGN_KEYS_SQL_ALL` DIRECTLY (the literal same query strings
    the live-fetch path uses, not copies) in
    `COALESCE(json_agg(row_to_json(...)), '[]'::json)` — **verified
    byte-identical to a live `GET /graph` call against the same
    database**, both queries, not just "shaped similarly."
    `COALESCE(...)` matters here specifically because `json_agg()` over
    zero rows returns SQL `NULL`, not `[]` — a bare `null` would parse
    as valid JSON but isn't an array, which is exactly the kind of
    silent-wrong-shape input the frontend validation now checks for by
    name (see below).
  - `GET /paste-query` — returns `{tables_sql, foreign_keys_sql}`; needs
    no connection at all to answer.
  - `ui/index.html` — both queries fetched once (`populatePasteQuery()`)
    and shown in their own read-only textareas (so they're always
    visible/selectable even if a copy button fails — clipboard
    permissions are genuinely unreliable in some automated/sandboxed
    contexts, verified directly: `navigator.clipboard.writeText` failed
    under headless-Chrome test automation with `NotAllowedError` even
    after explicitly granting clipboard permissions, which is why each
    button is a convenience, not the only way to get the text).
    `parsePastedArray()` (shared by both steps, parameterized by label
    and required fields) does deliberately light validation — enough to
    name which step failed and why (not valid JSON / not an array /
    missing a required field) instead of a confusing crash partway
    through rendering, not full-schema validation.
  - A paste-imported project creates itself with `origin: "paste"`, has
    zero versions until explicitly saved (same "nothing touches storage
    until Save as Version" rule as the database origin), and once
    loaded is otherwise indistinguishable from a live-fetched graph to
    every other feature — **verified live, screenshot-compared**: the
    force-directed layout, per-schema coloring, node sizing, and
    Insights hub ranking (`orders`/`users` at degree 6, matching known
    values) all match a live connection's render of the identical data,
    pixel-for-pixel in structure if not in exact node position (`cose`
    layout isn't deterministic between runs, but the graph it lays out
    is the same one).
  - **Third paste query added — columns, optional.** The owner pointed
    out that a paste-imported project could never show a table's
    columns in the detail panel at all, since that path has no live
    connection to lazily fetch them from on click (the way Explore
    normally does). `introspection_postgres.COLUMNS_QUERY_SQL` bulk-
    fetches every column for every table in one shot — the ONE
    deliberate exception to "never bulk-fetch columns," since for this
    origin bulk IS the only option, not a scale mistake (see the
    query's own comment). Wraps the same column list `_COLUMNS_SQL`
    already used, extended with `schema_name`/`table_name` since it's
    no longer scoped to one table — **verified identical to the live
    per-table `GET /table/{schema}/{table}` fetch** for the same table.
    Deliberately optional (an empty paste is accepted, not an error) —
    `openTableDetail()` now branches on `isConnected`: a live connection
    still fetches lazily per-table exactly as before (unchanged, still
    the preferred path when available); with none, it falls back to
    `lastGraphData.columns` filtered to the clicked table, shared
    through the same `renderColumnsAndRelationships()` rendering
    function so the two paths can never visually drift apart. Verified
    live: clicked a table in a paste-imported project with zero live
    connection, saw its full column list, types, NOT NULL markers, FK
    badges, and Relationships section — all identical in shape to the
    live-connected version.
- **v2 design, Phase C — from-scratch origin + Editor mode.** The
  biggest phase, and the first checkpoint of it is built and verified:
  design a schema by hand, from nothing, no database ever involved.
  - "New Project — From Scratch" creates a project with `origin:
    "scratch"` and — since there's nothing to connect to or explore —
    `openProject()` special-cases zero-version scratch projects to open
    straight into **Editor**, a third mode alongside Explore/Clusters
    (`#modeBtnEditor`), instead of the usual "Connect to a database"
    placeholder that makes no sense for this origin.
  - **Editor mutates `lastGraphData` directly, never a separate draft
    copy** — the same explicit decision from the original design
    conversation, now actually built: switching to Explore or Clusters
    mid-edit shows the exact in-progress structure, not a stale
    snapshot, and "Save as Version" is the ONLY thing that ever writes
    any of it to storage. Six pure mutation functions
    (`addTableToProject`/`deleteTableFromProject`/`addColumnToProject`/
    `deleteColumnFromProject`/`addForeignKeyToProject`/
    `deleteForeignKeyFromProject`) are the single place these arrays
    ever get touched from the Editor — each does just enough validation
    to reject an exact duplicate (same table, same column name, same
    FK), nothing more; type correctness, sensible FK targets, etc. are
    the owner's call, per the "trust the user" decision from the design
    conversation, not this build's to second-guess.
  - **Deleting cascades correctly**: deleting a table removes its
    columns and every FK touching it (either side); deleting a column
    removes any FK using it. Verified live: added table `b` with column
    `y`, FK'd it to table `a`'s column `x`, deleted column `y`, confirmed
    the FK disappeared with it.
  - A third, separate Cytoscape instance (`editorCy`, distinct from
    Explore's `cy` and the Cluster workspace's `clusterCy`) renders
    every current table/FK on a plain canvas — reuses the exact
    "labeled box" styling already built for the Cluster canvas, since
    structure, not volume or schema, is what matters while editing.
    Clicking a table selects it (`selectEditorTable()`), showing its
    columns and outgoing FKs with add/delete controls in the sidebar.
  - **Add Column**: name, a type picked from a short common-types list
    or free-text custom, and NOT NULL/UNIQUE/PRIMARY KEY checkboxes
    (composite primary keys work for free — DDL export will just
    collect every column flagged `is_primary_key` on a table into one
    `PRIMARY KEY (...)` clause, no extra modeling needed). **Add Foreign
    Key**: pick one of the current table's own columns, pick a target
    table, pick one of ITS columns — the target-table and target-column
    dropdowns repopulate live as you pick.
  - **Two real bugs found and fixed while building this, both by
    reasoning through the code before they were ever seen live, and
    both concerning what `switchMode("explore")` does**:
    1. `switchMode`'s new "rebuild Explore if there's no `cy` yet"
       logic (added so a from-scratch project's Explore view isn't
       permanently blank) crashes on `renderGraph(null)` — `.tables` on
       null — the very first time the page loads, before any project is
       open, because `showGraphPlaceholder()` (part of every page
       load's startup sequence) itself calls `switchMode("explore")`.
       That crash silently aborted the rest of the startup sequence
       before it ever reached `loadProjectsScreen()` — the whole app
       would land on a blank "Connect to a database" screen instead of
       the Projects picker. Fixed by guarding on `lastGraphData` also
       being non-null before attempting a rebuild.
    2. Even with that guard, `showGraphPlaceholder()` deliberately
       destroys `cy` and shows its own placeholder text — but its own
       call to `switchMode("explore")` would then see "no `cy`" and
       immediately rebuild the exact graph `showGraphPlaceholder` just
       tore down, from whatever `lastGraphData` happened to still hold
       (e.g., disconnecting while viewing a project would silently
       redraw the old graph right after trying to hide it). Fixed with
       an explicit `switchMode(mode, { skipRender: true })` option that
       `showGraphPlaceholder()` passes — it only needs `switchMode` to
       reset which sidebar/main is shown and which mode button is
       active, never to render anything itself.
    Both were verified fixed by re-running the full Editor test suite
    end-to-end afterward, not just reasoned about — see `editorStructureDirty`'s
    own comment in `ui/index.html` for the live version of this story.
  - **Second checkpoint — owner feedback after using the first one**:
    - **Editor's canvas now matches Explore's node styling** (schema-
      colored circles, always-labeled) instead of the plain gray-blue
      boxes it launched with — the owner asked for visual consistency
      between modes directly. Needed its own small
      `keepEditorLabelSizeConstant()` rather than reusing Explore's
      `keepLabelSizeConstant()` — that function hardcodes the module-
      level `cy` (Explore's instance) rather than taking one as a
      parameter, and a Cytoscape zoom event handler receives the Event
      object as its argument, not the cy instance — binding the shared
      function directly to `editorCy`'s zoom event would have silently
      operated on the wrong instance (or none, if Explore's `cy` was
      still null). Caught before it shipped, not after.
    - **The real, load-bearing fix — lazy column loading
      (`ensureColumnsLoadedFor()`)**: Editor's columns list and its Add
      Foreign Key form's dropdowns only ever read from
      `lastGraphData.columns`, which is correctly EMPTY for a table
      that came from a live connection (Explore only fetches columns
      lazily per-table on click, never in bulk) or a paste-import that
      skipped the optional columns step. Before this fix, selecting any
      real, pre-existing table in Editor showed it as having zero
      columns, and the Add FK form's dropdowns were empty for both
      sides — the owner described this precisely as the dropdowns
      "showing null." Fixed by having `selectEditorTable()` and
      `populateAddFkToColumn()` both lazily fetch a table's real
      columns (reusing the exact same `GET /table/{schema}/{table}`
      endpoint Explore's `openTableDetail()` already uses) the first
      time Editor needs them for a table it doesn't already know the
      columns of, then cache them into `lastGraphData.columns` exactly
      like a paste-imported project's columns already live. **Verified
      against the real dev database, precisely (not just eyeballed)**:
      selecting `public.orders` in Editor now shows all 12 of its real
      columns with correct NOT NULL flags, and the Add FK form's
      dropdowns show all 12 real column names — both empty/broken
      before this fix. One known gap: columns fetched this way default
      `is_unique`/`is_primary_key` to `false`, since the live per-table
      query (`_COLUMNS_SQL`) only ever reported NOT NULL, never real
      UNIQUE/PRIMARY KEY constraints from the catalog — such a column
      just won't show that badge in Editor yet, though it's still fully
      usable as an FK target either way.
    - **Panel placement — tried the right side, owner asked to revert
      to the left.** The per-table edit card was briefly moved to a new
      right-side panel (mirroring Explore's `#detailPanel` convention:
      click a node, see its detail on the right) on the reasoning that
      Editor and Explore should share that convention — the owner tried
      it and preferred the original left-sidebar placement instead, so
      it moved back. Left as a lesson: matching an existing convention
      isn't automatically the right call if the owner's actual working
      habit is different — ask or offer, don't just assume consistency
      trumps preference.
    - **Columns are now editable in place, not just add/delete-able.**
      Each column row has its own inline type `<select>` (same list as
      the Add Column form's — `COMMON_COLUMN_TYPES`, one shared JS array
      instead of two hardcoded option lists that could drift apart) plus
      a custom-text fallback; picking a new type applies immediately via
      `changeColumnTypeInProject()`, no separate Save button, consistent
      with how the NOT NULL/UNIQUE/PK checkboxes elsewhere already apply
      directly rather than as a staged edit.
  - **Third checkpoint — zoom controls + a redesigned, parameterized
    type picker**:
    - **Zoom controls** (`#editorZoomControls`) mirror Explore's exactly
      (`updateEditorZoomLevel()`/`btnEditorZoomIn`/`Out`/`Fit`, operating
      on `editorCy` — never the shared Explore `cy`/`updateZoomLevel()`,
      same separate-instance discipline as everything else in Editor).
      **A real bug caught and fixed during this**: `cose`'s default
      post-layout auto-fit zooms in very aggressively when there are
      only a handful of nodes — observed directly, a 1-3-table Editor
      canvas fit-zoomed to the `maxZoom: 8` ceiling (800%) on load,
      which reads as broken, not "fit to screen." Fixed by explicitly
      clamping the zoom to 100% max both right after initial layout and
      after every "Fit to screen" click — `maxZoom: 8` stays available
      for a deliberate manual zoom-in past that, only the *automatic*
      fit is clamped.
    - **The type picker no longer bakes one arbitrary length/precision
      into the dropdown option text** (the old list had literal
      `character varying(255)` and `numeric(12,2)` entries) — the owner
      asked for this directly: pick a base type, and if it takes
      parameters, small dedicated box(es) appear next to the picker for
      them, not a fixed value hidden inside the option label.
      `PARAM_TYPE_CONFIG` covers the two Postgres types that actually
      commonly take numeric parameters — `character varying`/`character`
      (one box, length) and `numeric` (two boxes, precision + scale) —
      anything else parameter-shaped still goes through the existing
      Custom… free-text field rather than this app trying to model
      every possible parameterized type. `COMMON_COLUMN_TYPES` was also
      expanded well past the original 12 entries (added `real`,
      `double precision`, `time`, `interval`, `json`, `bytea`, plain
      `character`) per the owner's ask to cover "all important data
      types," not just a minimal starter set.
    - **Existing columns parse their real type back into base + params
      correctly** (`parseTypeForEditing()`) — e.g. a real
      `character varying(30)` column (from a live-fetched or
      paste-imported table) shows "character varying" selected with
      "30" already in the length box, not falling through to the Custom
      field just because the exact string doesn't match a fixed
      dropdown option anymore. Switching a column's base type via the
      select always RESETS the param box(es) to that new type's own
      defaults (`updateTypeParamUI()`) rather than carrying over a
      previous type's params — a varchar length isn't a meaningful
      numeric precision, so keeping it around across a type switch
      would be actively wrong, not just unused.
    - Verified precisely end-to-end: added a `character varying` column
      with length 64 and a `numeric` column with precision 8/scale 3,
      confirmed both resolved to exactly `character varying(64)` and
      `numeric(8,3)`; switched an existing varchar(64) column to numeric
      via its inline select and confirmed the param boxes correctly
      reset to numeric's own defaults (12, 2) instead of keeping 64.
  - **Fourth checkpoint — Clusters rescoped from `host:port:database` to
    `project.id`, closing out Phase C.** `clustersStorageKey()` used to
    key off the live connection's `host:port:database`
    (`currentConnectionKey`) — a real bug, not just an inconsistency:
    a from-scratch or paste-imported project has no live connection at
    all, so that key was always `null` for them and Clusters silently
    did nothing; worse, two DIFFERENT projects pointed at the SAME live
    database would have incorrectly SHARED one cluster set, since the
    old key only ever captured "which database," never "which project."
    Now keyed by `currentProject.id` instead — `currentConnectionKey`
    itself was removed entirely (it had no other use). Filter/Insights/
    Color-by-Cluster needed no separate rescoping — none of them have
    their own storage, they all just read `loadClusters()`, so fixing
    that one function fixed all of them together. **Verified precisely,
    three scenarios**: (1) a from-scratch project with zero live
    connection ever can now create and see its own clusters — this was
    completely broken before; (2) a second, separate project does NOT
    see the first project's clusters — confirmed real isolation, not
    just "seems to work"; (3) reopening the first project still shows
    its cluster, confirming correct persistence under the new key. Also
    regression-tested the original database-origin path (the one that
    already worked before this change) to confirm nothing broke:
    create/list/seed-from-hub all still behave identically to how they
    were verified when Clusters first shipped.
  - **Phase C is now fully done** — from-scratch origin, Editor mode
    (add/edit tables, columns with parameterized types, foreign keys,
    zoom controls, matching Explore's visual language), and Clusters
    correctly project-scoped.

- **v2 design, Phase D — version comparison via DataDiff Pro, done and
  verified AT THE TIME — since SUPERSEDED by "AI Assist, Phase H"
  below.** The DataDiff Pro `/compare` call this section describes was
  removed once this tool had its own purpose-built comparator
  (`diffSnapshots()`); Compare now runs entirely locally, no DataDiff
  Pro call at all. Kept below for the historical reasoning (why
  DataDiff Pro was the right call at the time), not as a description of
  current behavior — see "AI Assist, Phase H" for what actually runs
  today. A "Compare versions" picker (two `<select>`s, in
  the Project sidebar card below version history, shown once 2+
  versions exist — defaults to the two most recent) hands both full
  snapshots to DataDiff Pro's own `/compare` endpoint and shows the
  result in a modal — the one place in this app that uses a modal,
  deliberately: it's a genuinely temporary "look at this, then close
  it" view, unlike Explore/Clusters/Editor, which you stay in and keep
  working within.
  - **Called directly from the frontend**
    (`fetch("/tools/datadiff-pro/compare", ...)`), not proxied through
    a new Schema Map backend endpoint — this whole toolbox is one
    process on one port (see repo root `CLAUDE.md`'s mounting
    explanation), so it's same-origin with zero CORS concern, and a
    Schema Map endpoint that just forwarded the request unchanged would
    add nothing. This is the one place in `schema-map/ui/index.html`
    that calls a DIFFERENT tool's absolute path rather than its own
    relative one — deliberate, not an oversight of the usual
    relative-path convention, since it genuinely is a different tool.
  - **`list_keys` is passed explicitly via `environment_yaml`, not left
    to DataDiff Pro's own auto-detection** — read
    `core/list_resolver.py` before assuming auto-detect would have been
    fine: it only ever tries key combinations of up to 2 fields, but a
    `foreign_keys` row's real identity needs 3
    (`from_schema`/`from_table`/`from_column` — a table can have
    several FK columns, so schema+table alone isn't unique). Left to
    auto-detect, that list would have silently fallen back to fragile
    position-based pairing, which reorders unpredictably between
    versions and would have produced noisy, wrong-looking diffs for
    rows that never actually changed. `COMPARE_LIST_KEYS_YAML` declares
    the real composite key for all three lists
    (`tables`/`foreign_keys`/`columns`) up front, every time.
  - **Verified against the real endpoint, not assumed**: a direct curl
    against `/tools/datadiff-pro/compare` with a synthetic
    add-a-table-and-change-a-value example confirmed the environment
    key strategy is actually being used
    (`"list_strategy": "environment key (schema_name, table_name)"` in
    the response's own trace data, not the fragile fallback) and that
    `MISMATCH`/`EXTRA_RIGHT` land exactly where expected. Then verified
    the full UI flow end-to-end in a real browser: built a project with
    two versions genuinely differing by one added table and one added
    column, compared them, and confirmed the modal shows exactly "2
    added · 0 removed · 0 changed" with both real records rendered
    correctly, using the `columns` list key too (not just `tables`).
  - Only `MISMATCH`/`EXTRA_LEFT`/`EXTRA_RIGHT` records are shown —
    `MATCH`/`EQUIVALENT` (nothing meaningfully different) are filtered
    out, since schema data has no numeric-tolerance-style equivalence
    rules configured and would just be noise here.
- **v2 design, Phase E — DDL export, done and verified. The last piece
  of the v2 plan; all five phases are now complete.** An "Export DDL"
  button in the Project sidebar (`generateDDL()` in `ui/index.html`)
  opens a modal (reusing the `.modal-overlay`/`.modal-box` pattern from
  Phase D's compare modal) with the generated SQL in a read-only
  textarea plus a Copy button.
  - **Scope is deliberately fixed**: columns, `NOT NULL`, `UNIQUE`,
    `PRIMARY KEY`, `FOREIGN KEY` only — no indexes, no partitioning, no
    `DEFAULT` values. Defaults were considered and explicitly left out:
    a live-fetched default is often a `nextval(...)` sequence reference
    that wouldn't exist in a fresh target database, and the owner's
    original scope named four constraint kinds, not five — guessing at
    which defaults are "simple enough" to be safe was rejected in favor
    of matching the agreed scope exactly.
  - **Every identifier is always double-quoted** (`quoteIdent()`),
    unconditionally — not just when "needed." Real schemas mix case
    (this exact dev fixture's own tables don't, but the principle was
    tested with a synthetic `OrderLineItem` table), and unquoted DDL
    would silently fold a mixed-case name to lowercase, creating a
    differently-named table than intended. Always-quote sidesteps
    guessing whether a given name needs it.
  - **`CREATE TABLE` statements first, `FOREIGN KEY`s as separate
    `ALTER TABLE ... ADD CONSTRAINT` statements after all tables
    exist** — avoids topologically sorting `CREATE TABLE` by dependency
    order, and works even for circular references between tables.
  - **A found-and-fixed real gap**: `is_primary_key`/`is_unique` were
    never fetched at all for a live-connected or paste-imported table
    before this phase — `_COLUMNS_SQL`/`COLUMNS_QUERY_SQL`
    (`introspection_postgres.py`) only ever reported `NOT NULL`. This
    was already known and flagged as a cosmetic-only gap in
    `ensureColumnsLoadedFor()`'s own comment (Phase C) — fine when the
    only consequence was a missing PK/UNIQUE badge in Editor, but
    load-bearing for DDL correctness, so fixed now: both queries gained
    `is_primary_key` (via `pg_constraint`, `contype = 'p'`) and
    `is_unique` (via `pg_index`, `indisunique`, **not**
    `pg_constraint`). The `pg_index` choice matters: a real, common
    pattern is `CREATE UNIQUE INDEX` run directly rather than declared
    as a table constraint, and that's invisible in `pg_constraint`
    entirely — found on this exact dev fixture (`customers.email` is
    enforced by a plain unique index, `users.email` by an actual UNIQUE
    constraint; both had to be detected). `indpred`/`indexprs IS NULL`
    excludes partial and expression unique indexes, since a partial
    unique index (e.g. a soft-delete pattern) doesn't mean the column
    is unique across all rows — treating it as a plain column `UNIQUE`
    would be wrong. Only a column that's the *sole* key of a
    single-column unique index is reported — a composite
    `UNIQUE(a, b)` isn't representable by this per-column model (same
    restriction Editor's own single-checkbox-per-column UI already
    has), so composite unique constraints are correctly left out rather
    than incorrectly split into two single-column `UNIQUE`s.
  - **A PK's own backing index is always unique too** — `generateDDL()`
    suppresses the inline `UNIQUE` when a column is already the primary
    key, to avoid a redundant `NOT NULL UNIQUE ... PRIMARY KEY` pair.
  - **FK export is scoped to what was actually exported**: `generateDDL`
    tracks which tables actually got a `CREATE TABLE` (a table with no
    columns loaded is skipped, and an export of a subset — a cluster,
    or just the tables someone clicked in Editor — legitimately won't
    include every table the bulk `foreign_keys` list mentions), and
    filters `ALTER TABLE ... FOREIGN KEY` statements to only those
    where BOTH endpoints were created. Without this, exporting a
    partial schema would emit non-runnable `ALTER TABLE` statements
    referencing tables that don't exist in the generated script — this
    was caught during verification, not assumed away.
  - **Verified by actually running the generated SQL against a real,
    fresh Postgres database, not just eyeballed** — same discipline as
    every other phase. Live-connect test: loaded `users` (PK
    `user_id`, UNIQUE `email` via a real constraint) and `orders` (PK
    `order_id`, `FOREIGN KEY user_id -> users.user_id`, plus three
    OTHER FKs to tables deliberately left un-loaded) into Editor,
    exported DDL, and confirmed the other three FKs were correctly
    omitted (the "only export what was loaded" filter). Ran the
    generated SQL against a throwaway database on the same dev Postgres
    container — it executed with zero errors, and `\d` on the resulting
    tables matched the source exactly (same PK, same UNIQUE, same NOT
    NULL, same FK, defaults correctly absent). Separately verified
    composite primary keys (a from-scratch two-column PK) and
    mixed-case identifier quoting (`OrderLineItem`) the same way — real
    SQL, real execution, real `\d` comparison, not just reading the
    generated text. (A temporary `window.__scmTest` hook was added to
    `ui/index.html` to let Puppeteer reach `selectEditorTable`/
    `lastGraphData` — both are `<script type="module">`-scoped and not
    reachable from outside otherwise — and removed again once
    verification was done; nothing in the shipped page still exposes
    them.)
  - **A pre-existing, unrelated bug found along the way — now FIXED
    (see "v2 design, Phase F" below)**: loading a single schema via
    Explore's schema picker crashed Cytoscape when that schema had an
    incoming cross-schema FK whose source table wasn't in the loaded
    node set. Flagged as out-of-scope at the time; turned out to also
    be the real root cause of a separate Editor-mode bug report, so it
    got fixed properly instead of staying deferred.

- **v2 design, Phase F — cross-schema-FK crash fix, plus Migration DDL
  (a delta between two versions, not the whole schema).** Not part of
  the original 6-point plan (all of which finished at Phase E) — this
  is the "further usability change" the owner flagged right after Phase
  D shipped, now described and built.
  - **The crash fix**: `edgeSafeForeignKeys(tables, foreignKeys)`
    (`ui/index.html`), shared by `renderGraph()` (Explore's `cy`) and
    `renderEditorCanvas()` (Editor's `editorCy`), filters `foreign_keys`
    down to edges where BOTH endpoints have a real node in the loaded
    table set before handing anything to Cytoscape — mirroring a filter
    Clusters' `renderClusterCanvas()` already had (`memberSet.has(...)`
    on both ends), just not shared until now. Without it, Cytoscape
    throws (`Can not create edge ... with nonexistent source/target`)
    the moment an edge references a missing node, which crashes the
    WHOLE canvas build, not just that one edge — for Editor specifically,
    that means `editorCy` never gets assigned at all, so NO click on ANY
    node works afterward, not just "the second one." This turned out to
    be the actual cause of the owner's report ("first click shows
    columns, switching to a different node shows none") — reproduced
    exactly: `editorCy exists: false` after switching to Editor mode
    with only `public` loaded (this dev fixture has
    `analytics.orders -> public.customers`), `editorCy exists: true`
    and both real mouse-clicks correctly showing full column lists once
    fixed. Investigated by ruling out the data layer first — direct
    `selectEditorTable()` calls (both sequential and a deliberate
    zero-await race) rendered correctly every time — before finding the
    real cause in canvas construction, not click handling.
  - **Migration DDL**: a "Generate Migration DDL" button inside the
    existing Compare-versions modal (Phase D) — reuses the same two
    full version snapshots already fetched for that comparison
    (`lastCompareSnapA`/`lastCompareSnapB`, module-level, set right
    before `openCompareModal()`), and opens the SAME `#ddlModal` Phase E
    already built (title/subtitle now dynamic — `ddlModalTitle`/
    `ddlModalSubtitle` — so one modal serves both "Export DDL" and
    "Migration DDL: vX → vY").
  - **Built from the two full snapshots directly, not from DataDiff
    Pro's diff records** — `generateMigrationDDL(snapA, snapB)` walks
    `tables`/`columns`/`foreign_keys` itself and computes adds/drops/
    changes by key comparison. DataDiff Pro's records are shaped for
    DISPLAY (a flat list of field-level path/value differences, built
    for the Compare modal's UI) — reconstructing a full new table's
    worth of columns/constraints out of that would mean re-deriving
    information this tool already has cleanly in the two snapshots. The
    visual Compare modal and the DDL generator both start from the same
    two fetches; they just do different things with them.
  - **Scope, per the owner's own answers**: only version-vs-version
    (not live-DB-vs-version or working-state-vs-last-version — the
    owner picked "any version vs any version" specifically when asked).
    Removed items DO get DROP statements (owner: "if you compare you
    get something extra left and extra right which you can if remove
    then give me drop query") — `DROP TABLE`/`DROP COLUMN`/
    `DROP CONSTRAINT IF EXISTS`. Changed column types get a real
    `ALTER COLUMN ... TYPE ... USING ...::newtype` (owner picked
    "Generate ALTER COLUMN TYPE," not a comment-only flag).
  - **Constraint naming switched to match Postgres's own default
    auto-generated names** (`<table>_pkey`, `<table>_<column>_key`,
    `<table>_<column>_fkey` — via `pkConstraintName()`/
    `uniqueConstraintName()`/`fkConstraintName()`), for BOTH this
    feature and Phase E's `generateDDL()` (which previously used its
    own `fk_<table>_<column>` scheme). This matters specifically for
    DROP: this tool doesn't capture a live database's REAL constraint
    names, only whether a column is PK/unique/FK, so a DROP CONSTRAINT
    has to guess a name — matching Postgres's own default gives it the
    best real chance of hitting an actual constraint in an unmodified
    database, and every generated SQL block says so explicitly (a
    custom-named real constraint needs manual adjustment before
    running). `buildCreateTableSQL(schema, table, tableCols)` was
    extracted out of `generateDDL()` so both it and new-table creation
    inside `generateMigrationDDL()` share identical column/constraint
    logic, not two copies that could drift.
  - **Ordering**: drops/narrowing first (FK drops → PK drops → UNIQUE
    drops → `DROP TABLE` → `DROP COLUMN` → type/nullability `ALTER`s),
    then creates/adds (new schemas → `CREATE TABLE` → `ADD COLUMN` →
    `ADD CONSTRAINT UNIQUE` → `ADD PRIMARY KEY`), then FKs dead last —
    same "FKs need everything else to exist first" reasoning as
    `generateDDL()`, plus drops have to clear out before anything that
    needs the old thing gone (e.g. a PK constraint dropped before its
    own column can be dropped). An FK that keeps its own
    `(from_schema,from_table,from_column)` identity but changes WHAT it
    references is treated as a full identity+target key
    (`fk_from...=>to...`) — a retarget is a drop of the old target plus
    an add of the new one, not silently ignored. A table being dropped
    entirely never gets a separate FK-drop for its own FKs — `DROP
    TABLE` removes them for free (verified directly: a synthetic
    composite-PK-to-single-PK narrowing plus a whole-table drop with an
    FK owned by that table produced no redundant `DROP CONSTRAINT` for
    the doomed table's own FK, and ran clean against real Postgres).
  - **A NOT NULL column added with no default gets a warning comment**
    right above its `ADD COLUMN` line — `ADD COLUMN ... NOT NULL` with
    no `DEFAULT` fails outright on a non-empty table in real Postgres,
    and DEFAULT values are explicitly out of scope for this tool (same
    Phase E decision, same reasoning: a live default is often a
    sequence reference that doesn't port). Rather than silently
    generating DDL that might fail on a real table with rows, or
    guessing a default value, this flags it and lets the owner decide
    (add a default manually, or backfill first).
  - **Verified against real Postgres, twice, not just read as text**:
    (1) a full Editor-built scenario (drop a column, widen a varchar,
    add a NOT NULL UNIQUE column with the expected warning comment, add
    a whole new table with a FK to the first) — ran clean against a
    database seeded with the "before" structure, and `\d` on the result
    matched the intended "after" structure exactly, including the
    UNIQUE constraint auto-named `accounts_email_key` and the FK
    auto-named `orders_account_id_fkey`, both matching Postgres's own
    convention as designed. (2) A synthetic case exercising `DROP TABLE`
    and composite-PK narrowing together (untouched by test 1) — also
    ran clean, also matched exactly, confirming the "table drop owns
    its own FKs" ordering logic for real.

- **v2 design, Phase G — dependency enforcement, RESTRICT semantics,
  done and verified.** The first step of a broader "AI Assist"
  initiative (see below) — a real, standalone correctness fix the owner
  found by asking a hypothetical question, not a report: "if I drop a
  column referenced by 10 tables, do we handle that?" The honest answer
  at the time was no.
  - **The gap**: `deleteColumnFromProject()` only ever cleaned up
    foreign keys where the deleted column was the SOURCE side
    (`fk.from_column`) — mirroring only half of what
    `deleteTableFromProject()` already did correctly (that function
    cleans up FKs on BOTH the `from_` and `to_` side of a deleted
    table). A column deleted while still being some OTHER table's FK
    target left that FK dangling in `lastGraphData` — still rendered as
    a valid edge in Editor/Explore (now that `edgeSafeForeignKeys()`
    only checks table existence, not column existence), and still
    emitted by `generateDDL()`/`generateMigrationDDL()` as a
    `FOREIGN KEY` referencing a column that no longer exists — SQL that
    fails in real Postgres (`cannot drop column ... because other
    objects depend on it`).
  - **Design went through two shapes — worth remembering both, not just
    the final one.** The first version fixed the gap by cascading in
    both directions (like `deleteTableFromProject()` already did) and
    added a confirm dialog scoped to only the cross-table case. That
    version was reported as broken ("asks the first time, then deletes
    without asking" on a DIFFERENT column with its own real dependents)
    — investigated hard: reproduced the exact reported sequence three
    separate ways (same-table two-columns-back-to-back, different
    tables, and against real live-connected data with real FKs) and
    every one correctly asked every time; never reproduced a failure.
    Rather than keep chasing an unreproducible report, the owner
    proposed a fundamentally simpler design instead of debugging
    further: mirror real Postgres's own default (`RESTRICT`, not
    `CASCADE`) — refuse the delete outright while any dependency
    exists, require removing it first, no cascade and no confirm
    dialog at all. This sidesteps the whole class of "did the dialog
    show or not" bug surface by removing the conditional-cascade path
    entirely — there's no "cascade automatically" branch left to have
    a bug in.
  - **Current behavior**: `deleteColumnFromProject()` and
    `deleteTableFromProject()` both now return `{ error }` (unchanged)
    and change NOTHING when a dependency exists — matching the
    `addTableToProject()`-style error contract already used elsewhere
    in this file. `findDependentForeignKeys(schema, table, column)`
    checks a column's dependents; `findDependentTableForeignKeys(schema, table)`
    checks a table's, deliberately EXCLUDING self-referencing FKs (a
    table pointing at its own column, e.g.
    `categories.parent_id -> categories.category_id`) — the whole table
    disappearing takes a self-reference with it consistently, so only
    an external table's dependency actually blocks. A column's own
    OUTGOING FK (it references something else) is still auto-removed
    with the column, same as before — only INCOMING references from
    other tables/columns block.
  - **UI**: the column-delete button and `btnDeleteTable` both call
    their respective function and `alert()` the returned error if
    blocked — no more confirm-with-cascade dialog. Table deletion keeps
    its pre-existing generic confirm ("this also removes its own
    columns and foreign keys") as a first gate, unchanged; the RESTRICT
    check runs after that confirm, as a hard second gate that can't be
    clicked through.
  - **New shared helpers become Phase J's validation layer**: both
    `findDependentForeignKeys()`/`findDependentTableForeignKeys()` are
    exactly the "is this operation safe" checks the AI Assist design
    needs to catch a bad LLM-proposed delete before it's ever shown for
    approval — built once here, reused there, not built twice.
  - **Verified live, four scenarios, all against real Editor state**:
    (1) deleting a column referenced by another table — blocked, clear
    message naming the referencing `table.column`, column untouched.
    (2) a SECOND, independently-referenced column on the same table —
    blocked too, with its OWN correct message (the exact case the
    confirm-dialog version was reported to mishandle). (3) attempting
    to delete the whole table while two DIFFERENT other tables still
    reference it — blocked, correctly naming BOTH referencing
    `table.column`s in one message. (4) removing the blocking FK first,
    then retrying the same column delete — succeeds cleanly, proving
    the block is a real gate, not a permanent wall.

## AI Assist initiative (Phases G, H done; I, J planned)

A second major initiative, distinct from the v2 design plan above (which
finished at Phase F). The owner's own framing: schema edits that are
tedious through pure clicking (e.g. "add 50 columns across 2 tables")
are trivial to describe in plain English, and a small LOCAL model
(Qwen3 4B was the owner's own suggestion, not Claude's) is plausible for
this specific narrow task — not because small models reason well in
general, but because the actual job is narrow "structured extraction"
(English → a JSON list of calls against a small, fixed, already-existing
operation vocabulary: `addTable`/`addColumn`/`addForeignKey`/
`changeColumnType`/`deleteColumn`/`deleteTable`), not open-ended
generation. Discussed and locked in across a multi-turn conversation
before any code was written — the owner was explicit throughout:
"don't start anything until we're sure this is possible and worth it."

**Four planned pieces, in dependency order** (each one lowers the risk
of the next, not independent parallel efforts):
1. **Phase G — dependency enforcement** (done, above). Foundational: the
   same "what depends on this, is this safe" check that fixed the
   column-delete bug becomes the validation layer Phase J needs to catch
   a bad LLM-proposed operation before it's ever shown for approval.
2. **Phase H — plain-English diffs, done and verified.** No LLM needed
   at all — the Compare modal's raw `path`/`left_value`/`right_value`
   output (from DataDiff Pro's response) was hard to read; the owner's
   own words: "showing me a json difficult for me to understand... easy
   plain text will be easy for me."
   - **Architecture reconsidered, not just restyled**: rather than
     translate DataDiff Pro's generic bracket-path records into English
     (nontrivial — parsing `columns[schema_name=x,table_name=y,...]`
     cleanly back into a table/column/field triple), Compare now uses a
     NEW, purpose-built `diffSnapshots(snapA, snapB)` that walks the two
     full snapshots directly, the same style as `generateMigrationDDL()`
     already did — Map lookups keyed the exact same way, no generic
     path-parsing needed at all. This retires the DataDiff Pro
     `/compare` call entirely for this feature (`COMPARE_LIST_KEYS_YAML`
     removed) — a deliberate reversal of the original Phase D decision
     ("reuse DataDiff Pro rather than build a second diff engine"), but
     the REASONING behind that original decision no longer applies: at
     Phase D there was no comparator in this tool at all; by Phase F,
     `generateMigrationDDL()` already needed to build one for SQL
     generation, so keeping DataDiff Pro around for DISPLAY meant
     maintaining TWO diff mechanisms for the same two snapshots, not
     avoiding a second one. `diffSnapshots()` is deliberately a SEPARATE
     function from `generateMigrationDDL()`'s own internal comparison,
     not a shared refactor of it — that function is already verified
     end-to-end against real Postgres, and reusing its internals for a
     read-only display feature wasn't worth the risk of destabilizing
     something already proven, for comparison logic simple enough that
     a second copy costs little.
   - **`describeSnapshotDiff(snapA, snapB)`** renders `diffSnapshots()`'s
     structured output as sentences — "Added table `public.refunds`",
     "Changed type: `public.accounts.name` — `varchar(50)` →
     `varchar(100)`", "`public.accounts.status` is now UNIQUE" — grouped
     into Added/Removed/Changed, same three-bucket summary line the
     modal already had, just computed locally instead of from DataDiff
     Pro's `EXTRA_RIGHT`/`EXTRA_LEFT`/`MISMATCH` counts.
   - **A column or FK belonging to a wholly added/removed table is NOT
     reported as a separate line** — "Added table `orders`" already
     implies its columns; a redundant "Added column `orders.id`" right
     next to it would be noise, not information. Same suppression for
     FKs owned by a new/removed table.
   - **A genuinely subtle case, verified correct**: a column that's a
     PRIMARY KEY in version A and a plain (non-PK) column in version B,
     with `is_unique: true` unchanged on the raw flag the whole time,
     still correctly reports "is now UNIQUE" — because a PK's own
     backing index already implies uniqueness (see `buildCreateTableSQL()`'s
     suppression logic), so the column's *effective*, DDL-relevant
     uniqueness genuinely changes even though the stored flag didn't.
     Matches what `generateMigrationDDL()` would actually emit for the
     same transition (`ADD CONSTRAINT ... UNIQUE`), not just a surface
     reading of the raw data.
   - **Verified two ways**: (1) a synthetic snapshot pair deliberately
     covering every category at once (added/removed table, added/removed
     column, type change, nullability change, unique-became-true on an
     ordinary column AND on a just-demoted-from-PK column, PK moved from
     one column to another, added/removed FK, plus the "new table's own
     FK isn't double-reported" and "removed table's own column isn't
     double-reported" suppressions) — all 11 expected lines present,
     correctly categorized, nothing extra. (2) A full real UI run
     (create project → two versions differing by one added table → click
     Compare → correct "1 added" summary and "Added table
     `public.orders`" line → click Generate Migration DDL immediately
     after, confirming it still works sharing the same
     `lastCompareSnapA`/`lastCompareSnapB` variables this change didn't
     touch). Identical-snapshots case also confirmed: "No differences
     between these two versions."
   - **A real bug found BY using Phase H, not IN Phase H — "Save as
     Version" could silently save an incomplete snapshot.** The owner
     compared v0 → v2 expecting to see exactly one thing (a removed
     column) and instead saw two unrelated ADDED columns plus a PK
     change, with the actual removal missing entirely. Traced to the
     raw stored version data, not assumed: `v0`'s snapshot had ZERO
     columns recorded for the `roles` table — not because the real
     table has none, but because nobody had clicked into it in
     Editor/Explore before `v0` was saved, so `ensureColumnsLoadedFor()`
     never fired for it. "Save as Version" (`btnSaveVersion`'s handler)
     just serializes whatever happens to already be in
     `lastGraphData.columns` at that moment — for a live-connected
     project, that's whatever click history happened to load, which can
     be a totally arbitrary subset of the real schema. Comparing that
     against a LATER version (with `roles` fully loaded, post-edit) made
     the diff engine correctly report "these columns are new" (they
     genuinely weren't in `v0`'s data) while having nothing to say about
     the real removal (the baseline never captured that column existing
     at all). Not a diff bug — `diffSnapshots()` did exactly what its
     inputs told it to; the inputs were the problem. Same underlying
     category as the `user_roles`-shows-one-column DDL export issue
     from Phase E, surfacing a different way.
   - **Fixed at the point of save, not by special-casing the diff or DDL
     generators** — `ensureAllColumnsLoadedForSave()` runs right before
     serializing the snapshot in `btnSaveVersion`'s handler: if
     `isConnected` and at least one table has zero columns recorded, it
     calls a new bulk endpoint (`GET /columns` →
     `introspection_postgres.get_all_columns()`, the SQL text
     `COLUMNS_QUERY_SQL` already had for paste-import, now also runnable
     directly via psycopg — pulled the inner `SELECT` out as
     `_ALL_COLUMNS_SQL` so both share one copy) and merges in ONLY the
     missing tables' columns. Deliberately a gap-filler, not a full
     refresh — a table that already has columns loaded (whether from a
     click, or from an Editor edit like a changed type) is left
     completely untouched, so this can never clobber an in-progress
     edit with a live re-read of the real database. Zero extra cost for
     the common case (every table already loaded, or a from-scratch/
     paste-import project where `isConnected` is false) — the bulk
     fetch only happens when there's an actual gap to fill.
   - **Verified against the exact reported scenario, not a
     reconstruction**: loaded the real dev fixture, confirmed `roles`
     had 0 columns loaded, saved a version WITHOUT ever clicking into
     it, then clicked into Editor (confirming all 3 real columns —
     `role_id`/`role_name`/`created_at` — were already present, proving
     the save-time fetch had already filled the gap), deleted
     `role_name`, saved again, compared the two versions: "0 added · 1
     removed · 0 changed" — "Removed column `public.roles.role_name`" —
     exactly what should have shown the first time. Also confirmed a
     from-scratch project's save path is completely unaffected (no
     `isConnected`, function returns immediately, same save behavior as
     always).
3. **Phase I — LLM-suggested clusters** (not yet built, first real LLM
   use). Deliberately the LOWEST-risk model use case: Clusters is
   already 100% free-form/manual-judgment with no validation at all
   ("membership is pure manual judgment, independent of the FK graph" —
   the original Clusters design decision), so a wrong suggestion here
   has zero structural risk — it's a proposal you accept, edit, or
   ignore, never an ALTER TABLE that could fail. Real value beyond what
   Insights' existing FK-degree ranking already does: a model reading
   table/column NAMES can catch domain grouping that's invisible to
   pure FK connectivity — relevant specifically because this exact dev
   fixture (and, per the owner, real legacy schemas generally) often
   enforces relationships in application code, not real FK constraints.
   Also where the FIRST real timing/hardware test happens — the owner
   has prior experience with Llama3 being painfully slow on large
   pasted context, but that was row DATA, not schema metadata; a
   cluster-suggestion prompt only ever needs table/column names+types,
   a much smaller context, but this needs measuring on the owner's real
   hardware, not assumed.
4. **Phase J — English → structure editing** (not yet built, highest
   risk, built last). Explicitly staged internally, NOT built as one
   step: first the full pipeline (propose → validate against Phase G's
   dependency checker + real current schema → preview via Phase H's
   plain-English formatter → approve → apply via the EXISTING Editor
   mutation functions, never new "apply" logic) using a dumb
   deterministic placeholder parser instead of a real model call — this
   proves the riskiest infrastructure (validation, preview, apply-via-
   existing-functions) with zero LLM uncertainty in the loop. Only once
   that works end-to-end does the real Qwen3 4B call (constrained/
   grammar-guided JSON decoding against the fixed operation schema) get
   swapped in as the last piece, so a slow/unreliable model on the
   owner's hardware costs nothing on the plumbing already built.

**Infra decision, locked in**: the model runs via Ollama (or similar)
reachable from the toolbox container over plain HTTP — NOT a second
Docker container. The repo's own `CLAUDE.md` explicitly rejected
multi-container/gateway architecture once already; calling out to a
host-level (or sibling, non-toolbox) inference server keeps that rule
intact while still getting local-model behavior. Reaching a host-level
service from a native-Linux container needs an explicit
`extra_hosts: ["host.docker.internal:host-gateway"]` entry in this
repo's own `docker-compose.yml` — without it, the only working address
is the Docker bridge gateway IP (`172.17.0.1` on this host), which is an
implementation detail of this specific machine's networking, not
something to hardcode into application code. Added and verified: the
toolbox container can reach `http://host.docker.internal:11434` (an
Ollama instance running as its own separate, unrelated docker-compose
project on this host).

**Phase I — PAUSED, hardware-blocked, real numbers gathered before
committing further.** qwen3:4b (the owner's original choice) measured at
~4 tokens/second on this host's CPU (i5-1135G7, no discrete GPU,
`OLLAMA_NUM_GPU=0`) — confirmed NOT a Docker overhead issue (the
container sees all 8 CPU threads with zero cgroup limits, verified
directly; native execution would perform identically) and NOT fixable
via the `think: false` API parameter (tested — Ollama's support for that
flag is template-dependent and isn't wired up correctly for this
model/version; it made a real test prompt SLOWER, not faster: 19.8
minutes vs. 11.5 minutes, and produced raw prose instead of the
requested JSON). qwen3:0.6b is fast enough to be usable (23 seconds on
the same test prompt) but the actual suggestions were noticeably
worse — 2 of 8 tables dropped entirely from any group, and one
nonsensical pairing (customers grouped with employees, no real
relationship between them in the schema). qwen3:1.7b was the intended
middle-ground test — never actually run (kept hitting a sandbox-check
outage, then paused at the owner's request to move to other work) — if
Phase I is picked back up, that's the next concrete step, not a redo of
everything already measured here.

## UI/UX polish and edge cases (owner's direct ask, separate from any phase sequence)

Four concrete items, explored and fixed together after AI Assist was
paused — the owner's framing: "lets just try to improve uiux and edge
cases we will see this later."

1. **Delete a project.** No `delete_project()` existed in
   `project_store.py` at all — added, deletes the project AND all its
   versions (no `ON DELETE CASCADE` in the schema, since sqlite3 doesn't
   enforce FK constraints unless `PRAGMA foreign_keys=ON` is set
   per-connection, which this module doesn't do — versions are deleted
   explicitly first instead). `DELETE /projects/{project_id}` in
   `server.py`. UI: a ✕ button on each row in the Projects list, with
   `event.stopPropagation()` so it doesn't also open the project, and a
   confirm naming exactly what's being lost ("permanently removes the
   project AND all of its saved versions").
2. **Two related asks, not the original literal request.** The owner's
   first framing ("write structure to disk so it survives a restart")
   turned out to already be true — Projects/Versions already persist on
   the `schema_map_data` Docker volume (Phase A). Clarifying revealed
   what was actually wanted:
   - **Auto-create an initial version ("v0") the moment a project
     actually has a real structure to save** — this was the ORIGINAL
     design intent from the very first design conversation ("v0 at
     project start") but was never actually implemented; every project
     required an explicit first "Save as Version" click before it had
     ANY history at all. `saveVersion(label, {silent})` is the save
     logic extracted out of the button handler into a reusable
     function; `autoSaveInitialVersionIfNeeded()` calls it once,
     guarded by the project genuinely having zero versions yet (checked
     fresh, not cached). Fires at project-creation time for
     scratch/paste origins (both have a real structure immediately) and
     on the first successful "Load graph" for a database-origin project
     (nothing exists to snapshot before that). `saveVersion()`'s own
     "nothing to save" guard was relaxed from "zero tables blocks
     saving" to "only a genuinely null/uninitialized `lastGraphData`
     blocks saving" — an empty scratch project's true starting point
     (zero tables) is a legitimate, meaningful v0 to have on record, not
     an error.
   - **Compare the CURRENT (possibly unsaved) working state against any
     saved version**, not just two saved versions against each other —
     the owner's own words, echoing all the way back to the original
     Migration DDL discussion: "compare current state with last version
     or any version." A `CURRENT_STATE_SENTINEL` (`"__current__"`)
     option now appears in both Compare selects alongside real
     versions; `resolveCompareSide(id)` returns `lastGraphData` directly
     (no fetch) when that sentinel is selected, or fetches a real
     version as before. **A real directional bug found during
     verification, not assumed correct**: since the diff reads "A → B"
     (added = new in B), the older/baseline side belongs in A and the
     newer side in B — matching how comparing two real versions already
     defaulted (older, then newer). The first version of this feature
     defaulted A=Current (the newest possible state) and B=the saved
     version (older) — backwards, which silently inverted Added/Removed
     in the result (a genuinely added table read as "Removed table").
     Fixed by swapping the default: A=most recent saved version
     (baseline), B=Current (target) — "what have I changed since my
     last save" now reads correctly.
3. **Lock graph positions across re-renders — Cytoscape's `cose` layout
   is force-directed and non-deterministic, so the SAME data used to
   visually reshuffle on every "Load graph" click, project reopen, or
   mode switch back to Explore.** `nodePositions` (a single `Map` keyed
   by node id) remembers every node's position across renders — ONE
   shared map for BOTH Explore and Editor, not two separate ones. Two
   separate maps (`explorePositions`/`editorPositions`) was the FIRST
   version of this, reversed almost immediately: the owner correctly
   pointed out that the same table jumping to a different spot just
   from switching modes was disorienting, since Explore and Editor show
   the same underlying structure and should look the same. Merged into
   one map with a straight find-and-replace (`sed`) once the design
   call was made — no logic change needed beyond that, since both
   canvases already called the same `capturePositions()`/
   `applyStoredPositions()`/`layoutPreservingPositions()` helpers,
   they just each had their own separate map before. `capturePositions()` reads
   current positions before a `cy`/`editorCy` instance is destroyed;
   `applyStoredPositions()` stamps remembered positions onto node data
   before a new instance is built; `layoutPreservingPositions()` runs
   right after construction — it LOCKS every node with a remembered
   position (Cytoscape's own `.lock()`, which excludes a node from being
   moved by a layout while still letting the layout account for it when
   placing everything else), runs `cose` (which now only ever moves the
   unlocked, genuinely-new nodes), then unlocks everything again so
   normal interaction still works. The `layout:` key on both
   `cytoscape({...})` constructors changed from `"cose"` (auto-runs
   immediately, would undo all of this) to `"preset"` (uses whatever
   `position` was already stamped on each node, runs nothing
   automatically). An explicit "↻ Reset Layout" button
   (`btnResetLayout`/`btnEditorResetLayout`) was added next to the
   existing zoom controls on both canvases — the one deliberate way to
   ask for a genuinely fresh arrangement, since nothing does that
   automatically anymore. Verified directly (not by eyeballing
   screenshots): captured real node positions via a temporary debug
   hook, re-triggered "Load graph" on identical data — zero movement,
   sub-pixel-exact. Added a third table to a two-table Editor project —
   the two existing tables' positions were bit-for-bit unchanged, the
   new table got its own real, non-overlapping position. Reset Layout
   genuinely moved every node (confirmed non-trivial deltas on all of
   them), proving it's a real fresh layout, not a no-op. Re-verified
   after the shared-map merge: Explore's rendered positions and
   Editor's, for the same 26-table live dev fixture, matched exactly
   (sub-pixel) on first entry into Editor — no drag, no manual sync
   needed — and switching back to Explore left it unchanged too.

   **A second "should look the same" gap found right after fixing
   positions — node SIZE, not just position.** Explore scales each
   node's diameter by row count (`sizeFor()`, sqrt-scaled, 28-88px, or
   uniform 46px depending on the "Node size" radio) — Editor hardcoded
   a fixed `width: 46, height: 46` for every node regardless, so the
   same table could visibly be a different size depending which mode
   you were looking at it in. Fixed the same way as positions: extracted
   `buildSizeFor(tables)` out of `renderGraph()` (previously inline,
   closed over that render's own `maxRows`) into a shared function both
   `renderGraph()` and `renderEditorCanvas()` call, so there's one
   sizing formula, not two that could drift — Editor's node style
   changed from the hardcoded `46`/`46` to `"data(size)"`/`"data(size)"`,
   matching Explore's own pattern exactly, and `currentSizeMode()` (the
   radio toggle) is read directly from the DOM either way, so it's
   already shared state regardless of which mode's sidebar happens to
   be visible — no new wiring needed for that part. Verified directly:
   compared every node's `data('size')` between `cy` and `editorCy` for
   the real dev fixture (which has genuine row-count variation — sizes
   spanning 28 to 88px, not a degenerate all-same-size case) — zero
   differences across all 26 tables.
4. **Surface a lost database connection instead of leaving a stale
   "Connected" badge.** Root cause: `schema-map/db_engine.py` closes an
   idle connection after 20 minutes (`IDLE_TIMEOUT_SECONDS`) — a
   deliberate safety feature (a forgotten tab shouldn't hold a live DB
   connection open forever), copied from `sql-studio/db_engine.py`'s
   same pattern, not a bug. But the frontend had no way to ever learn
   this happened — `isConnected` was only ever set at explicit
   connect/disconnect time, so the badge stayed "Connected" forever and
   the first sign of trouble was some unrelated LATER action failing
   with a generic error. Fixed with a `setInterval` polling `GET
   /status` every 60 seconds (matching the reaper's own check interval)
   — but ONLY while `isConnected` is currently true, so there's no
   pointless polling once a disconnect is already known. When the
   server's view and the frontend's disagree, `handleServerSideDisconnect()`
   updates the Connection panel and shows a clear message — deliberately
   does NOT call `applyConnectionStatus()` wholesale, since that
   function's disconnected branch calls `switchMode("explore")` and
   wipes the canvas to the "Connect to a database" placeholder, which is
   correct for an explicit Disconnect click but wrong here: Editor mode
   doesn't need a live connection at all once loaded, and Explore's
   already-rendered graph is still perfectly valid to keep looking at —
   only the Connection panel itself changes; whatever's already on
   screen is untouched. Scope was explicitly decided with the owner:
   clear feedback only, NOT a heartbeat to keep the connection alive
   during active editing (the other option offered) — Editor mode not
   touching the database at all while working is a known, accepted
   tradeoff, not something this fix tries to paper over. Verified with
   the real 60-second wait, not a shortened test double: connected,
   loaded a graph, called `POST /disconnect` directly (bypassing the
   UI entirely, exactly mirroring what the server's own reaper does),
   confirmed the badge stayed "Connected" immediately after (the poll
   hadn't fired yet — not an instant-detection claim), then confirmed
   after ~65 real seconds the badge correctly flipped to "Disconnected"
   with the clear message shown and the Connection panel auto-opened.

## Static HTML export — a fifth item, added right after the four above

The owner's direct ask, following a separate discussion about what would
make this tool more worth adopting: a single, self-contained HTML file
that can be emailed/shared with someone who has NO access to this tool
at all — opens in any browser, view-only, no backend, no live DB
connection, nothing to install. Deliberately minimal scope (the owner's
own words): click a table to see its columns and relationships, zoom
in/out/fit, but explicitly NOT drag nodes and NOT refresh — there's no
backend for a standalone file to refresh from anyway.

- **`buildStaticExportHtml(data, positions, title)`** (`ui/index.html`)
  builds the whole file as one template-literal string — Cytoscape
  loaded from the same CDN this app already uses, an ADAPTED (not
  reused-by-reference) copy of the schema-coloring/node-sizing/
  detail-panel/relationships logic, working off one embedded data object
  instead of `lastGraphData`/`fetch`. Deliberately excludes Editor,
  Clusters, Filter, Insights, search, and the Connection panel entirely
  — none of that belongs in a file whose whole point is having none of
  it. `autoungrabify: true` on the Cytoscape config is the one-line
  mechanism that disables node dragging while leaving zoom/pan fully
  working (both are Cytoscape defaults, no extra code needed).
- **A real, severe bug found and fixed during THIS build, not
  hypothetical**: the exported file's own template contains literal
  `<script src="...">...</script>` tags as HTML markup CONTENT — but
  those tags live inside a JS template-literal STRING that is itself
  embedded inside the app's OWN `<script>` block. The HTML parser
  doesn't understand JavaScript at all; it just scans raw bytes for the
  literal sequence that closes a script tag, even inside a string
  literal or a `//` comment. The first version of this feature had TWO
  real closing-script-tag sequences inside its own template content
  (the Cytoscape CDN reference, and the exported file's own closing
  tag) — both would have prematurely closed THIS APP'S OWN top-level
  script block the moment the page loaded, silently breaking the entire
  tool, not just this feature (everything after that point in
  `index.html` would render as raw text instead of executing as JS).
  Caught before ever being deployed live, by reasoning about how HTML
  tokenization actually works, not by observing a live failure — fixed
  by writing those two occurrences as `<\/script>` (the backslash makes
  the SOURCE text not match the closing pattern, while still evaluating
  to a real `</script>` at runtime, which is exactly what the OUTPUT
  file needs — a completely separate, standalone document at that
  point). The SAME class of risk was already handled correctly for the
  embedded DATA (`jsonForInlineScript()`, escaping `<` in any string
  value that might contain `</script>`) — this was the one place the
  same defense hadn't yet been applied to the template's own literal
  content, not a new category of bug.
- **Verified three ways, not just "it opened without erroring"**: (1)
  confirmed the MAIN APP still works correctly after the fix — a
  scratch project could still be created and opened Editor mode
  correctly, zero JS errors — proving the fix didn't just move the
  breakage rather than eliminate it. (2) Generated a real export from
  the live dev fixture (26 tables) and opened the saved file as a
  genuinely separate page with request interception watching for any
  call to the toolbox backend or the dev Postgres container — zero,
  confirming real standalone behavior, not just "looks like it doesn't
  need one." (3) A second copy of the same export with a tiny
  test-only debug hook (`window.__testCy = cy`, never part of the
  shipped output) confirmed: clicking the `users` node opened the
  detail panel showing its real 8 columns with correct types, NOT NULL
  markers, and FK badges; a simulated drag left the node's position
  bit-for-bit identical (`autoungrabify` genuinely blocking movement,
  not just visually suggesting it should); clicking zoom-in actually
  increased the real Cytoscape zoom level.
- **Reuses `ensureAllColumnsLoadedForSave()`** (Phase H's own fix for
  the exact same underlying gap) before generating the export — a
  static file with no backend to fall back on can't afford a table
  showing zero columns just because nobody happened to click it first
  in this session.
- **Captures the CURRENTLY on-screen layout** if Explore is live at
  export time (same `cy.nodes().position()` pattern as
  `capturePositions()`), so the shared file visually matches what was
  being looked at — falls back to a fresh `cose` layout computed
  inside the exported file itself if Explore isn't currently rendered.

**"Export DDL" renamed to "Export Full DDL"** — a real point of
confusion, not a bug: the owner clicked it right after comparing
`v2 → Current` (a small, few-line diff) and expected the DDL output to
reflect that same small scope, but got the ENTIRE schema instead.
Investigated first, not assumed: confirmed directly (build 3 versions,
explicitly "Switch to this" on an older one, export) that this button
DOES correctly follow whichever version you've switched to — the
confusion was that it always exports the FULL structure of whatever's
loaded, never a delta, and has no relationship to the Compare picker's
A/B selection at all — "Generate Migration DDL" (the delta-only
version) lives inside the Compare modal specifically, a different
button in a different place. Given the two are easy to conflate at a
glance, the fix was simply making the always-full-schema scope explicit
in the name itself — "Export Full DDL" — rather than adding an
explanatory hint elsewhere (the owner's own pick when offered both).
`$("ddlModalTitle")` is still set dynamically by both `btnExportDdl`'s
and `btnGenerateMigrationDdl`'s handlers (one modal, two possible
titles — "Export Full DDL" vs. "Migration DDL: vX → vY") — only the
STATIC fallback text (before either handler ever runs) and the button
label itself changed.

**Editor's column list gained two symbol badges — 🔗 for "part of a
foreign key" (either direction) and 🔑 for UNIQUE**, matching Explore's
own existing `col-fk-badge` styling for 🔗 (reused as-is, not
redefined) so the two modes read consistently. Additive to the existing
PK/NOT NULL/UNIQUE text flags, not a replacement — the owner's own ask
was to ADD two symbols, not restyle what's already there.
`renderEditorColumnsList()` now computes `fkOutCols`/`fkInCols` once per
table render (not per column), mirroring `getTableForeignKeys()`'s own
"both directions count" convention from Explore.

**A real bug found while verifying this, not shipped-then-discovered**:
adding or removing a foreign key never re-rendered the columns list at
all — `btnConfirmAddFk`'s and the FK-row delete button's handlers only
ever called `renderEditorFksList()`/`renderEditorCanvas()`, never
`renderEditorColumnsList()`. Caught immediately by the test itself (a
column that should have shown 🔗 right after adding its FK showed
nothing at all until the table was deselected and reselected) — fixed
by adding the missing call to both handlers. Verified directly: added
an FK from `sessions.account_id` to `accounts.id` and confirmed the 🔗
badge appears on `account_id` immediately, no reselect needed.

**Not yet built** (pre-v2 items, still outstanding): Step 4 (schema → connected-components → group
expansion, so nothing renders before you explicitly ask for it), Step 5
(hub-collapse toggle). Manual *non-FK* links between tables (the cluster
canvas only ever draws real FK edges) — other DB engines, community
detection beyond plain connected components.

- **SSH tunnel + Vault — Connection panel gained the exact same fields
  sql-studio's did**, same owner pain (the idle reaper drops the
  connection, retyping credentials every time is friction) and same
  implementation, both built on the shared `core/pooled_postgres.py`/
  `core/postgres_conn.py`/`core/vault.py` modules — see
  `sql-studio/CLAUDE.md`'s own "SSH tunnel + Vault" section for the full
  writeup (the SSH tunnel lifecycle, the vault's save/load shape, the
  same-origin direct-call pattern to `/tools/vault/...`); nothing here
  diverges from that description except which tool's `server.py`/
  `db_engine.py` the fields are wired into. Verified against the same
  isolated SSH+Postgres test setup sql-studio's was verified against.

## How it's built

- `server.py` — thin FastAPI app: `GET /` (UI), `POST /connect`,
  `POST /disconnect`, `GET /status`, `GET /schemas`, `GET /graph`. No
  `/query` endpoint and no `query_guard.py` equivalent at all — unlike
  SQL Studio, this tool never accepts free-form user SQL, only ever runs
  its own fixed introspection queries, so none of that machinery
  (statement splitting, destructive-keyword detection, the confirm-
  dialog flow) is needed or present here.
- `db_engine.py` — now a thin ~15-line wrapper around
  `core.pooled_postgres.PooledPostgresConnection` (own instance, `_POOL`
  — genuinely separate from SQL Studio's own `_POOL`, not shared; Schema
  Map and SQL Studio might reasonably be pointed at two different
  databases at once). The pool+reaper lifecycle (the `ConnectionState`
  dataclass, the idle reaper, credential pre-validation before opening
  the pool, password scrubbing) used to be a byte-for-byte-similar copy
  of `sql-studio/db_engine.py`'s own version — that duplication is what
  `core/pooled_postgres.py`/`core/postgres_conn.py` now eliminate; both
  tools' `db_engine.py` call the same shared mechanics while keeping
  their own, genuinely different state. This tool still only passes a
  smaller pool size (`pool_max_size=2` vs. SQL Studio's 3 — this tool
  only ever runs a handful of introspection queries per fetch, never
  sustained query traffic) and exposes `run = _POOL.run` (SQL Studio's
  `execute()` has its own extra logic on top — statement execution,
  result caching — so it isn't a plain alias there, but the underlying
  `run()` it's built on is the exact same shared method).
- `introspection_postgres.py` — `get_schemas()`, `get_tables(schema)`,
  `get_foreign_keys(schema)`, `get_graph(schema)` (the one function
  `server.py`'s `/graph` route calls, combining the other two). Every
  query is a direct port of an already-verified `SHOW_COMMANDS` query
  from `sql-studio/ui/index.html`, not written from scratch — same
  `SYS_SCHEMA_FILTER`-equivalent non-system-schema exclusion. Returns
  plain dicts (via `psycopg`'s cursor `.description` + `zip`), not SQL
  text — unlike SQL Studio's `SHOW_COMMANDS`, which return SQL strings
  to be run through Run's own pipeline, this tool executes these
  queries directly since it never accepts free-form user SQL.
- `ui/index.html` — single file, no build step, same convention as every
  other tool. Layout is a left `.sidebar` (Connection + Schema picker,
  both `<details>` cards) driving a right `.main` graph canvas — the
  inverse of SQL Studio's layout (editor-dominant, info sidebar) since
  this tool is graph-canvas-dominant. `renderGraph()` destroys and
  recreates the Cytoscape instance on every load (same "rebuild from
  scratch, don't try to diff" pattern df-studio's Tabulator usage
  already established) — node IDs are `schema.table` (not just
  `table`), so same-named tables in different schemas (already a real,
  verified case for SQL Studio's schema-fetch feature — `public.orders`
  vs. `analytics.orders`) get distinct graph nodes instead of colliding.

## Things that will bite you if you don't know them

- **Never fetches column data for tables that haven't been individually
  clicked — by design, not an oversight, not yet built either.** A
  schema with hundreds of tables shouldn't pay (in fetch size, transfer
  time, or render cost) for every table's full column list just to draw
  the graph. `introspection_postgres.py`'s queries deliberately stop at
  `{schema_name, table_name, row_estimate, total_size}` — no `columns`
  key at all yet. When Step 6 lands, column fetching will be a *separate*
  per-table endpoint, triggered only on click — don't "simplify" this by
  folding columns back into `get_tables()`'s bulk query.
- **Node sizing (`sizeFor()` in `ui/index.html`) uses `sqrt(row_estimate
  / maxRows)`, not a linear scale**, clamped to a 28–88px range. Linear
  scaling would make one huge table's node enormous and everything else
  an invisible speck; sqrt compresses that range while still keeping
  size meaningfully different. `row_estimate` itself is `pg_class.
  reltuples` (the same fast-estimate metric SQL Studio's "Show Table
  Sizes" uses), not `COUNT(*)` — a table that's never been `ANALYZE`d
  reports `-1`, clamped to 0 via `Math.max(t.row_estimate, 0)` before
  sizing, not treated as an error.
- **`cytoscape.js` is loaded as a classic `<script>` tag, not inside the
  `type="module"` script.** It's a UMD build exposing a global
  `cytoscape` function, not an ES module — attempting to `import` it the
  way SQL Studio imports CodeMirror from esm.sh would fail. The classic
  script tag runs during HTML parsing (synchronous, in document order);
  the module script is deferred until after parsing finishes — that
  ordering is what guarantees `cytoscape` already exists as a global by
  the time the module script's code that references it actually runs,
  not a race condition to worry about.
- **The graph endpoint's `schema` query param uses the empty string to
  mean "all schemas," not the string `"all"` or an omitted param in the
  literal sense** — `ui/index.html`'s schema `<select>` has an `"All
  schemas"` option with `value=""`, and `loadGraph()` checks
  `if (schema)` before appending `?schema=...` to the request URL, so an
  empty selection genuinely omits the query param rather than sending
  `schema=`. `server.py`'s `/graph` route's `schema: Optional[str] =
  None` then correctly falls through to
  `introspection_postgres.get_graph(conn, None)`, which its own
  `get_tables()`/`get_foreign_keys()` treat as "no schema filter." If
  you ever change the `<select>`'s "all" sentinel value, keep this
  empty-string-means-omit-the-param behavior in sync on both ends.
- Mounted at `/tools/schema-map/` by `main.py` in the repo root, same as
  every other tool — this folder never needs to know that.
- **`cy.resize()` must be called whenever `.detail-panel`'s visibility
  toggles** (`openTableDetail()`/`closeDetailPanel()` in `ui/index.html`
  both do this) — the graph canvas is a flex sibling of the detail
  panel, so showing/hiding the panel changes the canvas's actual
  available width, but Cytoscape doesn't observe layout/CSS changes on
  its own. Skipping this call leaves the canvas rendering at its old
  size, visibly cut off or with dead space, until the next explicit
  interaction happens to trigger a redraw.
- **Schema node colors are deterministic, not per-render-random** —
  `buildSchemaColorMap()` sorts schema names alphabetically and walks
  `SCHEMA_COLOR_PALETTE` in that fixed order, so the same schema keeps
  the same color across reloads and across toggling the size-mode
  radio (which re-renders from `lastGraphData` without re-fetching).
  Don't swap this for `Math.random()`-based color picking — two schemas
  landing on visually-similar random hues would defeat the point of
  coloring by schema in the first place. The palette has 10 entries and
  cycles (`% length`) past that — a schema-heavy database (this tool's
  whole reason to exist) hitting 11+ schemas gets color *reuse*, not an
  error; the legend (`renderSchemaLegend()`) only shows once 2+ schemas
  are present in the current graph, not for a single-schema view where
  a legend would just restate the obvious.
- **`keepLabelSizeConstant()` must never clamp its result with a fixed
  minimum floor — a real bug, caught by computing the actual on-screen
  result across zoom levels, not assumed correct.** An earlier version
  did `Math.max(2, BASE_FONT_SIZE / cy.zoom())` "defensively," which
  silently breaks the whole point of the function at high zoom: past
  the zoom level where `BASE_FONT_SIZE / cy.zoom()` would naturally dip
  below 2, the floor takes over and the model font-size stops shrinking
  — but cytoscape's zoom multiplier keeps growing, so the *rendered*
  size grows past `BASE_FONT_SIZE` instead of staying constant, exactly
  the "text zooms in with the graph" behavior this function exists to
  prevent. Fixed by removing the floor entirely and instead bounding
  `cy`'s own `minZoom`/`maxZoom` (0.05–8) at graph creation, so the
  division never needs a floor in the first place — cytoscape's default
  zoom range is effectively unbounded (1e-50 to 1e50), which is what
  made the floor feel necessary originally. If you ever change
  `BASE_FONT_SIZE` or the zoom bounds, recompute this by hand across a
  few zoom values (`BASE_FONT_SIZE / zoom`, then `× zoom` to confirm it
  round-trips to `BASE_FONT_SIZE`) rather than trusting it by inspection
  — this exact bug looked correct at zoom=1 and only showed up at the
  range's edges.
- **A foreign key can reference a table in a DIFFERENT schema than the
  one holding it — `introspection_postgres.py`'s FK queries must select
  the target's real schema (`fn.nspname AS to_schema`, via a
  `pg_namespace` join on `c.confrelid`), never assume `to_schema ==
  from_schema`.** This was a real latent bug, not a hypothetical: the
  original queries only ever joined `pg_namespace` for the *source*
  table, so every FK row's target was silently assumed same-schema —
  harmless purely by accident while every test fixture's FKs happened
  to be same-schema, until it wasn't. Found (by re-reading this code
  while building the Filter feature, not reported by the owner) and
  fixed, then verified against a genuine cross-schema FK added to the
  dev database (`analytics.orders.customer_id →
  public.customers.id`) — confirmed the API now reports `to_schema:
  "public"`, not the old buggy `"analytics"`. This matters *especially*
  now: `ui/index.html` builds every graph node id as `schema.table` (see
  "same-named tables in different schemas... get distinct graph nodes"
  above) and the Filter feature's BFS (`computeNeighborhood()`) walks
  those exact ids — a wrong `to_schema` wouldn't just mislabel one
  tooltip, it would point the traversal at a same-named table in the
  wrong schema (or a nonexistent node) and silently corrupt the
  blast-radius result. If you ever add a write path or another engine's
  introspection module, re-verify this same schema-qualification
  requirement holds there too — don't assume it's Postgres-specific
  paranoia.
- **Second, related bug in the SAME area, found right after the first:
  when one specific schema is selected (not "All schemas"),
  `_FOREIGN_KEYS_SQL_ONE_SCHEMA` must match the selected schema on
  EITHER side (`n.nspname = %s OR fn.nspname = %s`), not just the FROM
  side.** The original version only kept rows where the selected
  schema was the *source* — a table OUTSIDE the selected schema that
  references INTO it (`analytics.orders → public.customers`, while
  viewing just `public`) was silently dropped from the result entirely,
  so the Filter feature's traversal never even saw that edge to walk in
  the first place, regardless of how correct the BFS itself was. Caught
  by the owner testing the Filter feature and noticing a table's
  incoming dependency ("b to a") didn't show up, only its outgoing ones
  ("a to b"). Fixed by widening the `WHERE` to an `OR` and passing
  `schema` twice to `cur.execute()`; re-verified live — selecting just
  `public` now correctly includes the `analytics.orders →
  public.customers` edge (29 FKs total, same as "all schemas" returns,
  where before the one-schema view silently had only 28). If you ever
  touch `_TABLES_SQL_ONE_SCHEMA` or add a third query with a
  schema-scoping `WHERE`, check whether it has the same one-sided-filter
  shape before assuming it's fine — this exact mistake is easy to
  reintroduce because it reads as "obviously correct" at a glance (of
  course you filter by the schema you're looking at) while actually
  only covering half the real relationships that schema is part of.
- **`min-zoomed-font-size` and constant-size labels are mutually
  exclusive — don't add the first back as a "declutter" fix without
  removing the second.** An earlier version used
  `"min-zoomed-font-size": 6` to hide labels once they'd render too
  small to read when zoomed out, which is a real, valid Cytoscape.js
  feature — but it only works by *letting* font size shrink with zoom,
  which is exactly what `keepLabelSizeConstant()` was built to prevent.
  Decluttering at real scale is `LABEL_VISIBLE_THRESHOLD` instead (a
  table-count cutoff, currently 150 — **raised from an original 60**
  after a real 70-table single-schema legacy database tripped it and
  looked broken: no labels AND uniform node color (one schema = one
  palette entry, not a separate bug — see below), which reproduced
  pixel-for-pixel once the owner's actual paste-import data was tested
  directly. 60 was picked before Search/Insights/Filter existed, when
  labels were the ONLY way to identify a node at all; they're not
  anymore, so that number was too conservative for what's actually a
  completely ordinary schema size. Past the threshold, no persistent
  labels are drawn at all — `label: showLabels ? "data(label)" : ""` in
  the node style — and the hover tooltip becomes the only way to
  identify a node). That threshold is a stopgap for the current "the
  whole loaded scope renders at once" behavior, not a substitute for
  Step 4's progressive disclosure — the honest fix for "500 tables
  looks messy" is not rendering 500 tables in one view in the first
  place, not a smarter label-hiding rule. If you're ever tempted to
  raise this further, first check whether the actual complaint is
  really about labels, or (as it was here) about something else
  entirely that just LOOKS related — a single-schema database showing
  uniform node color, or a database with few/no real FK constraints
  (common in legacy schemas that enforce relationships in application
  code, not the database) producing a grid-like layout from `cose`'s
  physics on mostly-disconnected nodes, are both correct rendering of
  real data, not bugs, and raising the label threshold doesn't change
  either of those.
