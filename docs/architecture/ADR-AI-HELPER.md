# ADR-AI-HELPER — an "Ask Claude" helper inside every tool

- **Status:** **APPROVED to build by the owner on 2026-11-11** ("lets start step 1"); H3 built the same day (see "As built" at the end). Open decisions in §4 are for H1–H2.
- **Owner's goal (2026-11-11, own words):** "a helper in each tool, in the same window, hidden by default, usable as a chat bot, but it knows everything and
  works as a helper" — to fill the gaps between tools (query → load → JSON → transform → load) and to "take help from you to speed up when needed",
  using the **Claude Pro subscription the owner already has** (no API purchase), without being token hungry even with 1000 tools.
- **Builds on:** `ADR-MCP.md` (the MCP server, its safety rules, grants, audit — all unchanged and reused), roadmap P1–P3, K1–K6.

## 1. What the owner will see

```
┌────────────────────────── Toolbox ───────────────────────────────┐
│ [SQL Studio] [DataFrame Studio] [Vault]                          │
├──────────────────────────────────────────────┬───────────────────┤
│                                              │ 🤖 Ask Claude   ✕ │
│   the tool, unchanged                        │ 📍 SQL Studio ·   │
│                                              │ dev-db · 40 rows  │
│                                              │ You: …            │
│                                              │ Claude: …         │
│                                              │ [type here…]   ➤  │
└──────────────────────────────────────────────┴───────────────────┘
        hidden by default · 🤖 button or Ctrl+J opens it beside the tool
```

- One panel, **built once in the workspace shell**, shown beside **every** tool tab — no code in each tool. Works for any tool opened in the workspace
  (a tool opened directly by its own URL, outside the workspace, has no panel — optional later).
- Chat **and** work: answers questions, and does things with Toolbox's own tools. Anything that changes data shows a **plan card** with **Approve** (PIN when needed).

## 2. Decisions

### D1 — Engine: the owner's local Claude Code in headless mode (`claude -p`), not the API
- `claude -p … --output-format stream-json` uses the **owner's Pro login** (verified installed: Claude Code 2.1.142 with `-p`, `--output-format stream-json`,
  `--resume`, `--allowedTools`, `--model`). **No API key, no extra bill.** Usage counts against the Pro limits (shared with claude.ai and VS Code; they reset every few hours).
- **Personal use only:** the owner's own subscription, on the owner's machine, for the owner. Toolbox is single-user and local, which fits. Letting other people use the
  subscription through Toolbox is not allowed — another reason Toolbox must stay on localhost. (Check Anthropic's current terms before any wider use.)
- `--bare` is NOT used: in bare mode Claude Code ignores the OAuth login and needs an API key.

### D2 — Where it runs: a small helper ("bridge") on the HOST, not in Docker
- Claude Code and its login live on the host (`~/.claude`). Copying the login into containers would spread the owner's credential into images and volumes — rejected.
- The bridge is a tiny local web service, **started automatically at login** (systemd user service), listening on **localhost only**. The workspace page talks to it through
  the gateway (a proxy route), so the browser never needs a second port.
- The bridge runs `claude -p` with: working directory = the Toolbox repo (so the root `CLAUDE.md` is its map), `--allowedTools` limited to the Toolbox MCP tools
  (**no Bash, no Edit, no file writes** from a web page), the MCP server configured as today (`docker compose run … python -m mcp_server`), one process per question.
- If Claude is logged out, the limit is reached or the bridge is down, the panel says so in plain words. It never retries silently.

### D3 — Other AIs: an "engine adapter" in the bridge
- The tools are MCP (an open standard), so any MCP-capable assistant could drive them. The bridge has one adapter per engine with one interface:
  `ask(thread, message, context) → stream of events`. **Claude Code is the only adapter built and tested first** (H1); Codex CLI / Gemini CLI / an API key / a local model
  are optional later (H6), each tested on its own before it is offered.

### D4 — Sessions: threads the owner controls
- A **thread** = one Claude Code session (`--resume <session id>`), plus metadata kept in Toolbox's Postgres (title, tool it started in, created/last used, engine).
  The transcript itself stays where Claude Code keeps it, on the host.
- **New chat** = new session (clean, cheapest). **Continue** = same session (remembers everything said). Long threads are summarised automatically by Claude Code.
- Each tool lists **its own recent threads**; a thread can **follow the owner across tools** ("now transform what we just loaded"). Recommended habit: one thread per task.

### D5 — Context: what the helper knows, and how it stays cheap
| Knows | How | Cost |
|---|---|---|
| Which tool is open | the panel knows the tab | free |
| What the owner is looking at (current query, table, selection, last error) | an optional **context hook**: the tool posts a small summary to the workspace (`postMessage`, size-capped); tools without the hook still send their name + description | ~300 tokens |
| What Toolbox can do | **searches** the capability registry (D6) when needed — never loads all tools | ~1,000 per search |
| What was said before | the thread (D4) | grows with the thread |
| The rules | a short "system card" (what Toolbox is, the safety rules, how to search) | ~1,500, cached |

- **Target:** the start of a question costs **about the same with 25 or 1,000 tools** (~6,000 tokens, estimated). H3 measures it with 1,000 generated tools; the number is
  recorded in `docs/roadmap/measure-H3.md` and the design is changed if it does not hold.
- Claude Code also caches the unchanging start of every request, so repeated questions are cheaper still.
- Data in results is data, never instructions (ADR-MCP D10, unchanged).

### D6 — Capability registry: how 1,000 tools stay searchable
- Each tool's `manifest.yaml` gets an optional `ai:` section listing its **actions**: name, one-line purpose, inputs (schema), reads or writes, which grant a write needs.
  `core_plugins` validates it like the rest of the manifest. A new tool (P2 template) teaches the AI about itself; a removed tool (P3) disappears from it.
- The MCP server stops growing one MCP tool per capability. It offers a few **general verbs**:
  `find_actions(query)` → best ~5 matches · `describe_action(name)` → full detail of one · `run_action(name, inputs)` → runs it through the existing safety path
  (audit first, kill switch, grants, dry-run + confirm code, read-back).
- The 11 existing MCP tools become registry actions too; their names keep working (no break for anything already using them).

### D7 — Approval in the panel (plan cards)
- Writes keep ADR-MCP D7 exactly (owner grant, dry-run, single-use confirm code, backup, read-back, audit). New: the **dry-run is shown to the owner as a card**
  (what, where, how many rows, prod/non-prod) with **Approve** / **Reject**. Approve issues a short, single-action permission and the confirm code — with the PIN when
  no grant covers it. The AI still cannot approve for itself (the approval comes from the owner's click in the page, not from the MCP channel).

### D8 — Recipes: do it once with AI, repeat without it
- After a pipeline works (e.g. *query dev-db → stage into Vault Data → flatten JSON → clean → load into sales.orders*), the helper offers **Save as recipe**: the exact
  actions and inputs, stored in Toolbox. **Run recipe** replays them with **no AI and no tokens**, through the same safety path (writes still need approval).
- Recipes are deterministic; a source table that changed is noticed (version check) and reported before anything is written.

### D9 — The gap actions (query → load → JSON → transform → load)
Missing pieces become registry actions: **stage query result into a Vault Data table** (exists as data-lake staging; needs an `ai:` entry), **flatten JSON columns**
(new), **load a Vault Data table into a database** (a write: grant + plan card + read-back; Postgres first). Existing ones are reused: `run_query`, `compare`,
`table_transform` (DataFrame Studio steps), `generate_insert_script`.

## 3. Safety summary (nothing weaker than ADR-MCP)
- No credential ever reaches the AI; the AI uses connections and servers by name. Prod / unlabelled = prod rules.
- The helper can only use Toolbox's MCP tools: no shell, no file edits on the owner's PC from a web page.
- Every call is in the audit log and the AI Access timeline; the kill switch stops the helper too.
- Bridge on localhost only; Toolbox must stay on localhost (no login, and the Pro subscription must not be shared).

## 4. Not decided yet (owner, during H1–H2)
1. Default thread behaviour when the owner reopens a tool: continue the last thread, or start fresh? *Recommended: show the last thread, start a new one on the first message after 1 hour.*
2. Which model by default: Claude Code's default, or always the fastest? *Recommended: Claude Code's default; a small switch in the panel.*
3. Keyboard shortcut: Ctrl+J (as drawn) — check it does not clash with a tool's own shortcut.

## 5. Risks
- **Pro usage limits** — heavy days may hit them; the panel must show it clearly. Recipes (D8) are the main defence: repeat work costs nothing.
- **Start-up time** — a few seconds per question (Claude Code + the MCP server start). H1 measures it; a warm MCP server is the fix if it is too slow.
- **Context hook drift** — a tool that changes its page may send stale context; hooks are small, tested per tool, and optional.

## 6. As built in H3 (2026-11-11) — D5, D6
- **Manifest `ai:` section** (`core_plugins/manifest.py` `AiAction`; spec in `plugin-manifest.md`): **only stateless read GETs can be declared** — `effect` can only be `read`, `method` only `GET` — so a manifest can never expose an unguarded write (writes stay in the MCP server's code, ADR-MCP D7).
  Inputs are flat (string / integer / number / boolean) and validated by `core_plugins/ai.py`; values placed in the address are character-restricted, so an action cannot leave its tool's `/tools/<name>/` prefix.
- **`mcp_server/registry.py` + three verbs** `find_actions` / `describe_action` / `run_action`. Manifest actions run as one GET through the gateway (`TOOLBOX_GATEWAY_URL`); the 11 existing MCP tools are `mcp.<name>` actions run through the same function (their guards are unchanged;
  a test shows a gated tool is still refused through the registry). They also remain listed as MCP tools, so nothing existing breaks. `run_action` is therefore annotated not-read-only. `toolbox_guide` is bounded (≤ 40 names).
- **Measured (`docs/roadmap/measure-H3.md`, tokens estimated as chars / 4):** start of a question ≈ 5,800 tokens with 25 tools and ≈ 6,000 with 1,000 (a tool-per-action design: 9,600 → 212,000); one search ≈ 230, one describe ≈ 130. First search over 1,000 tools builds the index in 3 s (once per session), later searches 19 ms.
- **Real actions so far:** `df-studio.formula_help`, `df-studio.list_templates`, `data-lake.list_column_maps` (the stateless GETs that work through the gateway; session-based endpoints such as Duck Lab's tables were deliberately not declared — the AI has no browser session).
- **Verified live** through the official MCP client: search → describe → run (a real GET through the gateway, 41 formula functions), unknown input refused before any request, a typo'd id gets suggestions, an `mcp.*` action, a switched-off tool says so, the kill switch blocks `run_action`.
- **Found by the tests:** searching 3,000 actions took 2.7 s because word sets were rebuilt per query (now computed once per index: 19 ms).
- **Left for later sessions:** more tools' `ai:` entries (each tool's owner decides which GETs are safe and useful), hiding the older read-only MCP tools from the list to trim ~4,500 tokens (optional), write actions in the registry (H5: they will carry grant + plan card).

## 7. As built in H1 (2026-11-11) — D1–D4
- **`ai-bridge/`** (host service, stdlib only): `engine.py` (adapter interface + `ClaudeCodeEngine`), `bridge.py` (`GET /status`, `POST /ask` as SSE, token header, one question at a time), `install.py` (systemd **user** unit, token file 0600, `--write-env`). Gateway side: `core_plugins/helper.py` (`/api/helper/status`, `/api/helper/ask`, passes the stream through; token stays in the gateway's environment).
- **Changed from D2:** the working directory is a **neutral folder**, not the repo (no `CLAUDE.md` read; own short system prompt — halves the fixed cost, ≈ 11k → 4.7k tokens). The question goes on stdin.
- **Safety flags (tested):** `--tools ""` (no Bash/Edit/Write/Read/web), `--strict-mcp-config` + only the Toolbox server (without it the account's Gmail/Drive connectors leak into the session even with no tools), `--allowedTools mcp__toolbox`; API-billing variables stripped from the child; no `--bare`, no skip-permissions; own process group killed on timeout / cancel / disconnect.
- **Network:** listens on 127.0.0.1 and the docker0 address (retries until Docker is up) — not the LAN. **A host firewall (ufw) blocks containers → host**: one owner-run rule is needed (see runbook). I could not run it (needs admin), so the gateway leg was verified with tests and from inside the container (timeout until the rule exists).
- **Measured live:** a plain question ≈ 3 s start; a question that uses a Toolbox tool ≈ 7–10 s total; 14 tools visible, Bash refused ("could not"); `--resume` remembers the earlier answer (cache read 4,760 tokens); killing the service → systemd restarted it within seconds.
- **Not verifiable here:** a real logout and a real Pro-limit hit (messages come from patterns + `rate_limit_event`; tested with fakes); survival of a full reboot (service is `enabled`; `enable-linger` is optional).

## 8. As built in H2 (2026-11-11) — D4, D5
- **One panel in the workspace shell** (`core_plugins/ui/workspace.html`), hidden by default; the 🤖 Ask Claude button or **Ctrl+J** opens it beside the active tool (full-height overlay on a phone). No tool's own code changed. Answers stream; each tool call shows as a small chip; Esc in the box stops an answer (the bridge kills the process).
- **Threads:** one current thread **follows the owner across tools**; **New chat** = new Claude session; **Chats ▾** lists earlier chats ("This tool" first, then others). Reopening continues the last chat if it is under an hour old, otherwise starts fresh (the recommendation in §4.1 — now the default). **Simplification:** the chat list (title, tool, last used) is in the browser's localStorage, not Postgres; clearing browser data loses the list, not Claude's transcripts. Move to Postgres only if the owner uses several browsers.
- **Context (D5):** every question carries "Open tool: <title> (id), <description>" (+ "On screen: …" when the tool sent it), ≤ 4,000 chars. A tool may send what is on screen with `parent.postMessage({type:"toolbox-context", text}, "*")` (capped at 1,500 chars; only the tool's own frame is believed). **No tool sends it yet** — adding it to SQL Studio, DataFrame Studio and Vault Data is a small optional follow-up.
- **Tested:** `tests/smoke/test_helper_panel.py` in headless Chromium with the helper stubbed (no Pro usage). **Verified live** after the owner added the ufw rule: a real question through the gateway streamed back (≈ 3 s, context used).
- Still open from §4: default model (Claude Code's default is used; no switch yet), Ctrl+J did not clash in the tools tried (no tool binds it; re-check when adding hooks).

## 9. As built in H4 (2026-11-11) — D7
- **Flow:** the AI asks to save → no live grant → `approvals.ask_owner` stores a **pending card** (what / where / rows / columns / source / steps / prod-or-not) and the refusal tells the AI to wait → the panel shows the card → the owner clicks **Approve** (PIN typed in the card) or **Reject** → Approve creates a **10-minute grant for that one target + action, limited to the plan's row count** (`created_via='card'`) → the panel tells Claude to go ahead → the call runs the normal path (dry-run, confirm code, write, read-back) → the grant is **spent right after the write** (single use).
- **What the AI can reach:** only `ask_owner` (stores a request, grants nothing) and `spend`. `approve`/`reject` exist only on the owner's AI Access endpoints; approving needs the PIN (`control.create_grant`). Tests scan `tools.py` for anything else. Cards: max 10 pending, one per plan, expire in 30 min, rejected plans make the AI stop asking.
- **Changed from the plan:** Approve always needs the PIN (a card exists only when no grant covers the write, so the "PIN only when no grant" rule is always true). Rejecting needs no PIN.
- **Live:** real question → refused → card with correct facts → rejected. **Left:** the Approve click with a real PIN (owner has none yet). Only `table_transform` makes cards; the H5 database load will too.

## 10. As built in H5 (2026-11-11) — D8, D9
- **Gap actions (all gated like table_transform):** `stage_query` (a SELECT on Vault Data or a saved Postgres connection → a Vault Data table; refused, never partial, over the row cap), `flatten_json` (an argument of `table_transform`, runs first; JSON text/dict columns → `col.key` columns, nested to `max_depth`, lists kept as JSON text, never dropped), `load_table` (a Vault Data table → an EXISTING Postgres table: target and columns checked first, INSERT only, one transaction, count checked before commit and again after; a failing row rolls everything back — verified live). Each write: owner grant via a **plan card** (connection cards show prod / non-prod and need a PROD tick), dry-run, `confirm_code` bound to a hash of the exact data (a source that changed in between is refused), read-back.
- **Recipes (D8):** `keep_recipe` (the AI; stores text, ≤ 12 steps, only the six data tools, no `confirm_code`, saving steps must use `mode: replace`). **Running is owner-only** (panel button → AI Access endpoint): no AI, no tokens, the same `protocol.call_tool` path, so the kill switch, audit rows and grants still apply and a write waits for its card. Tables a recipe reads are remembered with their version; a changed one stops the run before anything is done.
- **Limits worth knowing:** Postgres only (SQL Server / Oracle: `generate_insert_script` text); load is append-only (no update / upsert / delete, by design); rows capped 5,000 (500 prod / unlabelled); a recipe step's arguments are fixed (no parameters yet).
- **Cost:** three more MCP tools add ≈ 1,300 tokens to the start of every question (≈ 7,300 total); hiding the older read-only tools (§6, optional) would win it back.
- **Found by the tests:** a "flatten" of a column with no JSON silently did nothing (now refused); an error line from the child could be lost in a race (bridge now waits for it before classifying).

## 11. Follow-up to H2 (2026-11-11) — chat log, policy, action-first prompt
- **Chat log (D4 revised):** the panel kept chats only in browser storage and showed an empty window after a reload. The log now lives with the bridge on the host (`store.py`, SQLite, private file) — not in Postgres, so the gateway needs no database library and the log sits next to Claude Code's own transcripts. Written while the answer streams (also when the browser closes mid-answer). Loads newest-30-first, older pages on scroll / click — a long chat never loads whole.
- **Why the tool did not show the result:** Claude works on Toolbox's data through its tools (a preview, or a saved Vault Data table); it does not click inside a tool's page, and a tool's screen does not watch the database. Now: when a write really happened (`saved` flag on the tool event), the active tool is told (`postMessage {type:"toolbox-refresh"}`) and reloaded. **Still not done (next idea):** real "do it on screen" commands — a tool opts in to `toolbox-command` messages (open table, add step, run query) so the helper can drive the page you are looking at; start with DataFrame Studio.
- **Prompt:** action-first (do it, then 2–4 lines: what, numbers, where to check; no pasted rows unless asked), names the table to open, one-line plan before any write, offers a recipe after a working pipeline. Answers render small safe markdown (bold, code, lists, tables; everything escaped first).
- **Policy:** the owner's own text file, appended below the fixed card at every question; editable in the panel; capped; a missing file means no policy. It can shape style and habits only — the safety rules are enforced by Toolbox's code (grants, PIN, cards, read-only), not by the prompt, so a policy cannot weaken them. Suggested later: named policy presets (concise / explain-more / strict-approvals) and per-tool policy sections.
- **Per-tool policy + reviews (owner request, same day):** `~/.config/toolbox-helper/policies/<tool>.md` is appended after the general policy when that tool is open; starting texts exist for DataFrame Studio and SQL Studio. Improvement loop: the owner reviews answers (👍 / 👎 + a short note, stored with the chat log) → in ⚙️ the tool's 👎 notes are listed → **Make it a rule** appends the note under "## Learned" of that tool's policy → it applies from the next question; 👍/👎 counts per tool show whether it is getting better. **The AI never writes a policy** (a policy is standing instruction; only the owner's click changes it) — an AI-suggested-rule flow was considered and left out for that reason.
- **Mode (owner request):** *Command* (default) = Claude replies with one complete, copy-ready block in the format of the open tool (DataFrame Studio: `def transform(df): … return df`) plus 1–3 lines, runs nothing — fast and the owner stays in control; *Run* = Claude uses Toolbox's tools. The mode is sent as the first line of the question context.
- **Browser freeze (owner report), found by measuring:** the panel re-drew the whole answer (including a table) for every 3 characters that streamed in — a long answer took minutes of main-thread time. It now draws at most ~6 times a second, scrolls only when you are at the bottom, and a test streams a 60-row table + 1,500 words and requires it to finish in < 6 s. The AI itself runs on the host / in containers, never in the browser (the browser only draws text).
- **Cards:** a decided card now disappears by itself (Reject at once; Approve after ~3 s) and has a ✕.
- **DataFrame Studio = command only, pipeline-aware (owner request):** the mode switch is hidden there (`COMMAND_ONLY` in the panel). The page now tells the panel what is on screen after every pipeline change (`postHelperContext` in `df-studio/ui/index.html`: table, row count, current columns with types, the steps applied so far — last 12, code shortened); the prompt says new code runs AFTER those steps, so write only the new step and reuse existing columns. Verified live: with year/month/is_weekend already added, "add quarter and amount_band" returned only the two new columns. Without the hook (or outside the workspace) Claude is told to ask for the pipeline instead of guessing.
- **Staging (suggestion, no new code needed):** DataFrame Studio's own session already IS the staging area — steps stack on the current frame and nothing is written until the owner exports. Keep it that way for transformations. For the SQL part of the flow use a Vault Data workspace named `staging`: `stage_query` once → later SQL/transform runs on `staging.*` (Vault Data SQL is local and free) → only the final `load_table` into the database needs a card. To avoid a card per staging write, create ONE grant on the workspace `staging` (AI Access, up to 8 h) — cards then only appear for the real database.

