# Knowledge Map

Purpose: a lookup table from "I need to change X" straight to the file that
owns it — so opening this repo with 10+ tools doesn't mean re-reading
everything to find where something lives. `CLAUDE.md` has the *rules*; this
file has the *floor plan*.

**Rule for every future tool**: when a tool is added, it gets its own
section below in the same shape as DataDiff Pro's. Keep this file in sync
with reality — a stale map is worse than no map, because it actively
misleads. If a file's job changes, update its row here in the same commit.

---

## Repo-wide (the Toolbox shell — not any one tool's code)

| If you need to change...                                    | Go to |
|---------------------------------------------------------------|-------|
| The home page layout / card styling                           | `main.py` (`_HOME_TEMPLATE`, `_render_card`) |
| Which tools show up as cards, their title/description/icon    | `registry.yaml` |
| Whether a tool defaults to shown or hidden (Tool vs Learn), the search box, the "Show learning tools" toggle | `registry.yaml` (`category:` field per tool) + `main.py`'s home page `<script>` block |
| Actually wiring a tool's app into the site (routing)           | `main.py` (`app.mount(...)` calls, bottom of file) |
| The Docker image / what gets copied into the container         | `Dockerfile` |
| Ports, restart policy, env vars for the whole site              | `docker-compose.yml` |
| Why the container runs `--workers 1` (not more)                 | `Dockerfile` (CMD comment) + `CLAUDE.md`'s "Standing rule: stateful tools and --workers" — check every stateful tool, not just df-studio, before ever raising this |
| The canonical color palette every new tool's `:root` should start from | `theme-tokens.css` — copy-source only, never served; see its own header for why |
| Architecture decisions, conventions, "why is it built this way" | `CLAUDE.md` |
| GitHub auth setup for this device                               | `GITHUB_AUTH.md` |
| Calling a tool's engine directly without a browser (headless), chaining two tools together | `orchestrator/` — see its own `CLAUDE.md`; not a mounted tool, no entry here or in `registry.yaml` |
| DataDiff Pro's mapping/equivalence/diff logic shared between the web UI and the orchestrator | `core/pipeline.py` (`run_compare`) |
| Connecting to Postgres safely (conninfo, credential pre-validation, SSH tunneling, password scrubbing) — shared by sql-studio, schema-map, and the orchestrator's Postgres connector | `core/postgres_conn.py` (`build_conninfo`, `verify_connection`, `open_ssh_tunnel`, `scrub_password`) |
| The pool+reaper lifecycle built on top of that — shared by sql-studio's and schema-map's own separate `_POOL` instances (NOT a shared connection, just shared mechanics) | `core/pooled_postgres.py` (`PooledPostgresConnection`) |
| Mapping a file extension to a DuckDB read function (csv/json/parquet) — shared by duck-lab and the orchestrator's file connector | `core/file_source.py` (`build_read_expr`, `detect_format`) |
| The shared encrypted secret store (saved DB connections, SSH credentials, anything else) — behind the Vault tool and sql-studio/schema-map's "Save/Load connection" controls | `core/vault.py` — see its own module docstring and `vault/CLAUDE.md` for the trust model |

---

## Tool: Packet Journey — mounted at `/tools/packet-journey/`

Fully static, no calculation and no network calls — a narrow, concrete
"watch one real request travel through the layers" tool, deliberately NOT
a comprehensive reference (that was tried once as "Layer Explorer" and
removed). One fixed scenario (HTTP/TCP/IPv4/Ethernet), walked Physical (1)
→ Application (7).

| If you need to change...                                    | Go to |
|-----------------------------------------------------------------|-------|
| The 7-step order, names, PDU labels, colors                      | `index.html` — `STEPS` array |
| Any individual layer's content (header fields, sample values, explanation) | `index.html` — `RENDERERS.<layerkey>` (e.g. `RENDERERS.transport`) |
| Step navigation / prev-next buttons                              | `index.html` — `goToStep()`, `renderStepsNav()` |
| Click-to-explain glossary                                        | `index.html` — `TERM_INFO` |
| The Wireshark correlation block per step (exact labels, filters) | `index.html` — the `.ws-block` markup inside each `RENDERERS.<layerkey>` |
| The brief "other protocols at this layer" list                   | `index.html` — `PROTOCOLS_BY_LAYER` + `protocolListHtml()` |
| Whether the backend does anything beyond serving the page        | `packet-journey/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **The scenario (HTTP GET over TCP/IPv4/Ethernet) is fixed, not
  configurable** — adding a UDP/HTTPS/IPv6 variant is a real scope
  decision, not a small tweak; check with the owner first, since the whole
  point right now is depth on one example over breadth across variants.
- **Steps 5 (Session) and 6 (Presentation) intentionally show NO header
  field** — that absence is the actual teaching content at those two
  steps (a real HTTP/TCP/IP packet has no Session or Presentation header
  at all). Don't "complete the pattern" by inventing fake fields for them.
- **Direction vs. framing are deliberately reconciled**: navigation goes
  Physical→Application (matches what the owner asked for, reads as the
  receiving side revealing headers one at a time), but each step's prose
  still explains that header's job from the SENDING side (since that's
  when it's actually added) — see `packet-journey/CLAUDE.md` for the full
  reasoning if this looks contradictory at a glance.
- **Every glossary reference was checked against `TERM_INFO` with a script
  before shipping** (0 missing, 0 unused) — same convention as every other
  tool here; re-run the same check after adding new content.
- **Each step's `.ws-block` uses the exact same sample values as that
  step's own field table** (same MACs/IPs/ports/TTL) — they're two
  independent hand-written blocks, not generated from one source, so a
  change to the scenario's values must be applied to both.
- **`PROTOCOLS_BY_LAYER`'s per-layer lists are deliberately brief** (one
  line each) — going deeper per protocol here would recreate the exact
  scope that got the standalone "Layer Explorer" tool removed.

---

## Tool: VLAN Designer — mounted at `/tools/vlan-designer/`

Entirely client-side, same pattern as Subnet Calculator — pure logic, no
secrets, no network calls. Built as one connected scenario (VLANs → switch
ports → router → reachability), not a reference tool. Phases 1-2 built;
see `vlan-designer/CLAUDE.md` for the phases still open (DHCP relay, ARP).

| If you need to change...                                    | Go to |
|-----------------------------------------------------------------|-------|
| VLAN-to-subnet allocation (largest-first, with gateway IP)       | `index.html` — `planVlans()` |
| The shared state driving tabs 1-4                                | `index.html` — `VLAN_PLAN` + `refreshDependentTabs()` |
| Switch access/trunk port planning + the 802.1Q frame diagram      | `index.html` — `renderPortsTab()`, "Tab 2" section |
| Router-on-a-stick sub-interfaces + generated CLI config           | `index.html` — `renderRouterTab()`, "Tab 3" section |
| The reachability checker (same-VLAN vs cross-VLAN path)           | `index.html` — `runReachCheck()`, "Tab 4" section |
| ACL rules blocking otherwise-valid routes                         | `index.html` — `checkAcl()` (engine), ACL rows card + `getAclRules()` (Tab 4 UI) |
| STP root-bridge election / port roles (fixed 2-switch topology)   | `index.html` — `computeStp()` (engine), `runStp()`, "Tab 5" section |
| Click-to-explain popovers                                        | `index.html` — `TERM_INFO` dict |
| Whether the backend does anything beyond serving the page        | `vlan-designer/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **IP-math functions are intentionally duplicated from Subnet Calculator**,
  not imported/shared — tools never import each other's code (see root
  `CLAUDE.md`). If a bug is found in one copy (e.g. `hostInfo()`'s /31//32
  handling), check whether the same bug exists in the other tool's copy too.
- **`planVlans()` sorts largest-first internally, re-sorts to input order
  for display** — identical reasoning to Subnet Calculator's `planVlsm()`.
  Don't display in allocation order.
- **Tabs 2-4 have no state of their own** — they're pure re-renders of
  `VLAN_PLAN`, called via `refreshDependentTabs()` whenever tab 1's plan
  changes. There's no per-tab memory across a VLAN-plan edit.
- **Every inline glossary reference was checked against `TERM_INFO` with a
  script before shipping** — a dangling reference silently produces an
  empty/broken popover, which is exactly the kind of thing easy to
  introduce and easy to miss by eye. Re-run that check after adding new
  inline `showInfoPopover(...)` references.
- **`checkAcl()` has no implicit "deny everything else"** unlike a real
  router ACL — only explicit rules matter, no match means permit. A
  deliberate, documented simplification (see the ACL card's hint text),
  not a bug to "fix" toward real Cisco behavior.
- **`computeStp()` models exactly one fixed topology** (two switches, two
  direct parallel links) — not a general spanning-tree algorithm. Tab 5 is
  intentionally NOT wired into `VLAN_PLAN`/`refreshDependentTabs()`; it has
  no relationship to the VLAN plan and was never meant to.

---

## Tool: DNS Lookup — mounted at `/tools/dns-lookup/`

Client-side, but genuinely needs internet access (the one tool in the
Toolbox that isn't fully offline) — `dns-lookup/server.py` only serves the
static page; every actual DNS query is a `fetch()` from the browser
straight to a public DNS-over-HTTPS provider (Cloudflare or Google).

| If you need to change...                                    | Go to |
|-----------------------------------------------------------------|-------|
| Domain input parsing/validation (`normalizeDomain`, `looksLikeDomain`) | `index.html` — `ENGINE` block |
| TTL formatting, MX/SOA/CAA parsing, TXT/CNAME cleanup for display | `index.html` — `humanizeTtl()` / `parseMx()` / `parseSoa()` / `parseCaa()` / `formatRecordData()` |
| Which record types get queried (currently 14: A, AAAA, CNAME, MX, TXT, NS, SOA, CAA, SRV, NAPTR, DNSKEY, DS, TLSA, SSHFP) | `index.html` — `RECORD_TYPES` array |
| Which DoH providers are offered                                  | `index.html` — `PROVIDERS` object |
| The actual `fetch()` call to the DNS provider                    | `index.html` — `dohQuery()` |
| CNAME-chain detection/labeling in results                        | `index.html` — `renderResults()` (`hasChain`, `DNS_TYPE_NAMES`) |
| NXDOMAIN handling (domain doesn't exist at all)                  | `index.html` — `renderNxdomain()` + the `allNxdomain` check in `runLookup()` |
| Click-to-explain popovers for each record type / TTL             | `index.html` — `TERM_INFO` dict |
| SOA's field-by-field breakdown (mname/rname/serial/refresh/retry/expire/minimum) | `index.html` — `renderSoaFieldGrid()` + the `soaMname`/`soaRname`/etc. `TERM_INFO` entries |
| Reverse DNS / PTR lookup (IP → hostname)                          | `index.html` — `ipToReverseArpaName()`, `parseIpv4()`, `runReverseLookup()`, "Reverse lookup tab" section |
| Private/reserved-IP short-circuit for reverse lookups             | `index.html` — `isPrivateOrReservedIpv4()` |
| Whether the backend does anything beyond serving the page        | `dns-lookup/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **An `A` query's answer can contain a `CNAME` row too** — DoH providers
  follow aliases automatically and return the whole chain. The renderer
  labels each row by its OWN type (not the queried type) specifically to
  show this. Don't collapse it to "just show A records."
- **NXDOMAIN (`Status: 3`) is checked separately from "no records of this
  type"** (`Status: 0` with empty/missing `Answer`) — the second case is
  normal and common (most domains lack a TXT record, say), the first means
  the domain doesn't exist anywhere. Conflating them produces a false
  "doesn't exist" for a perfectly real domain.
- **The DoH response omits the `Answer` key entirely on NXDOMAIN** — code
  relies on `data.Answer || []` for this; confirmed against the real
  Cloudflare API, not assumed from docs.
- **This tool's engine tests don't cover the network layer** (can't
  `node -e` a real `fetch`) — only the pure parsing/formatting functions
  are unit-tested that way. The `fetch`/response-shape assumptions were
  instead verified by curling the real provider endpoints directly.
- **Coverage was deliberately expanded from 6 to 14 record types** after
  initial feedback that "all 14 record types" was the actual expectation,
  not just the common six. All 14 are still queried on every lookup — that
  part hasn't changed.
- **Empty record types are hidden by default now (reversed from an earlier
  decision).** An earlier version of this file said "don't hide empty
  sections... the whole point is showing what was actually checked" — the
  owner later found seeing 8+ "no records found" sections on every lookup
  was confusing rather than informative, so `renderResults()` now shows
  only the record types with actual data, with the empty ones (still
  queried, not skipped) tucked behind a "Show N record types with no
  data" toggle (`buildRecordSection()` returns `{empty, html}`;
  `toggleEmptyRecordTypes()` reveals them). Nothing is deleted or
  unqueried — this is a default-visibility change, not a coverage
  rollback. If this gets revisited again, update this note rather than
  leaving both "don't hide" and "hide by default" claims in the file.
- **SOA now gets a dedicated field-by-field breakdown** (`renderSoaFieldGrid()`)
  instead of going through the generic per-record-type table — it's a
  special case inside `renderResults()`'s loop. CAA still just gets light
  inline formatting (`parseCaa()`), that wasn't upgraded to the same
  treatment and there's no plan to.
- **Reverse-DNS octet reversal is mandatory, not cosmetic** — confirmed by
  querying the SAME real IP both reversed and un-reversed: reversed
  succeeds, un-reversed returns `SERVFAIL` (Status 2), not just an empty
  answer. `ipToReverseArpaName()` is the only place this should happen;
  don't hand-construct an `.in-addr.arpa` name anywhere else.
- **Private/reserved IPv4 ranges are rejected BEFORE the network call**
  in the reverse-lookup tab (`isPrivateOrReservedIpv4()`) — querying public
  DNS for `192.168.x.x`'s PTR would just return nothing, which reads as a
  tool failure to someone who doesn't already know why; the upfront
  explanation is deliberate, not an unnecessary guard.

---

## Tool: Subnet Calculator — mounted at `/tools/subnet-calc/`

Entirely client-side, same pattern as Encode/Decode — `subnet-calc/server.py`
only serves the static page. No secrets involved here (it's just math), but
client-side keeps it instant and consistent with the rest of the Toolbox.

| If you need to change...                                    | Go to |
|-----------------------------------------------------------------|-------|
| Any core subnetting math (mask↔CIDR, network/broadcast, host range, same-subnet check) | `index.html` — "CALCULATION ENGINE" block at the top of the `<script>`, pure functions, no DOM |
| The bit-visualization grid (network vs host bit coloring)       | `index.html` — `bitGridHtml()` + `.bitgrid`/`.bit` CSS |
| The "how this was calculated" worked-binary explanation          | `index.html` — `.explain` block inside `runCalculator()` / `runCompare()` |
| The Calculator tab's inputs/results wiring                       | `index.html` — "Calculator tab" section of "UI WIRING" |
| The Compare-Two-IPs tab                                          | `index.html` — "Compare tab" section of "UI WIRING" |
| Public/private/reserved IP classification (the colored banner)   | `index.html` — `classifyIp()` (engine) + `renderIpTypeBanner()` (UI) |
| The click-to-explain "?" popovers on each result tile             | `index.html` — `TERM_INFO` dict + `showInfoPopover()`/`hideInfoPopover()` |
| VLSM planning — splitting a base block into per-department pools  | `index.html` — `minPrefixForHosts()` + `planVlsm()` (engine), "VLSM planner tab" section (UI) |
| Splitting a block into N *equal*-sized subnets                    | `index.html` — `prefixForEqualSplit()` + `splitEqualSubnets()` (engine), "Split Equal Subnets tab" section (UI) |
| Supernetting / route summarization (many networks → one CIDR block) | `index.html` — `commonPrefixLength()` + `summarizeNetworks()` (engine), "Supernet / Summarize tab" section (UI) |
| Shared widgets used by VLSM/Split/Supernet (proportional bar, results table, add/remove row buttons) | `index.html` — `.block-bar`/`.seg`, `.data-table`, `.add-row-btn`, `.row-remove-btn` CSS classes (generic on purpose — reused across all three dynamic-row tabs) |
| Whether the backend does anything beyond serving the page        | `subnet-calc/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **Engine functions are deliberately pure and DOM-free**, sitting above the
  `UI WIRING` comment block in the script. This was built "backend logic
  first" on purpose — verify any change to the engine with plain function
  calls (see the `node`-run test harness used during development) before
  touching how it's wired to the page.
- **Special-cased prefixes**: `/32` (single host, no network/broadcast
  concept) and `/31` (RFC 3021 point-to-point, both addresses usable) are
  handled explicitly in `hostInfo()` — don't let a generic "count − 2"
  formula regress onto these two sizes.
- **`planVlsm()` sorts largest-requirement-first internally** to guarantee
  correct address alignment (see the `vlsmOrder` popover for why), but
  `allocations` is re-sorted back to the *input* order before being
  returned/displayed — allocation order and display order are deliberately
  different. Don't "simplify" this by displaying in allocation order; that's
  the one thing users explicitly need to NOT have to think about.
- **`minPrefixForHosts()` can return `/31`** for a 2-host request — that's
  correct (RFC 3021: both addresses usable, zero waste), not a bug, even
  though it looks unintuitive next to a "department pool" framing.
- **`summarizeNetworks()` measures waste against actual merged coverage**,
  not just the min-to-max address span — a gap between two non-contiguous
  input networks correctly counts as waste too, not just space beyond the
  outer edges. If you touch the merge loop, keep the three test cases
  (exact tiling / gapped / overlapping) passing, not just the simple one.
- **Overlap detection carries the `raw` label through the merge step**
  (`merged[...].raw`) specifically so overlap warnings can name both
  networks involved — it's easy to "simplify" the merge loop and lose this,
  producing a warning that says `null` instead of a network name (this
  exact bug was caught and fixed once already during development).
- All three of VLSM / Split / Supernet share the same dynamic-row-list
  pattern (`addXRow()` appends a `.row` div with its own remove button,
  wired to re-run that tab's calc function) and the same `.block-bar` /
  `.data-table` CSS. Copy that pattern for any future tab needing a
  variable-length input list instead of inventing a new one.
- **`maskOctetsToCidr()` validates mask shape** (contiguous 1s then 0s) and
  returns `null` for anything else (e.g. `255.255.0.1`) — the UI relies on
  that `null` to avoid reacting to a mask the user hasn't finished typing.
- All bitwise ops use `>>> 0` to force unsigned 32-bit values — JS bitwise
  operators are signed 32-bit, and dropping this would silently break IPs
  in the upper half of the address space (anything ≥ `128.0.0.0`).

---

## Tool: Encode/Decode — mounted at `/tools/encode-decode/`

Entirely client-side — the Python backend (`encode-decode/server.py`) only
serves the static page; it has no other routes and never sees any input.

| If you need to change...                                    | Go to |
|-----------------------------------------------------------------|-------|
| Anything at all about behavior (every operation runs client-side) | `encode-decode/ui/index.html` (`<script>` block) |
| Base64 / Base64URL / Hex / URL / HTML entity logic              | `index.html` — "Text Encoding tab" section of the script |
| Gzip compress/decompress                                        | `index.html` — "Gzip tab" section (`CompressionStream`/`DecompressionStream`) |
| AES-GCM passphrase encryption                                   | `index.html` — "AES-GCM tab" section (`deriveAesKey`, PBKDF2 100k iterations) |
| RSA key generation / encrypt / decrypt                          | `index.html` — "RSA-OAEP tab" section |
| JWT signing/verification (HS256, RS256)                         | `index.html` — "JWT tab" section |
| SHA hashing                                                      | `index.html` — "Hash tab" section |
| Whether the backend does anything beyond serving the page        | `encode-decode/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **No backend processing, intentionally.** This was a deliberate security
  choice (see `CLAUDE.md` history / conversation) — real secrets
  (passphrases, private keys) must never be sent over the network, even
  locally. Don't add a `/encrypt`-style POST endpoint to `server.py` without
  re-raising that tradeoff with the owner first.
- **RSA-OAEP has a plaintext size limit** (~190 bytes at 2048-bit/SHA-256).
  It's meant for wrapping a small secret (like an AES key), not general
  data. The UI hints at this; don't remove the hint if touching that tab.
- **AES output packs `salt(16) + iv(12) + ciphertext` into one Base64
  blob** — the decrypt path assumes that exact layout. If the format ever
  changes, old ciphertexts become undecryptable; treat that as a breaking
  change worth flagging, not a silent tweak.

---

## Tool: cURL Builder — mounted at `/tools/curl-builder/`

Entirely client-side — the Python backend (`curl-builder/server.py`) only
serves the static page; it has no other routes and never sees any input.
This tool only ever generates a command string; it never issues the
request itself (deliberately, to avoid becoming an SSRF proxy — see its
own `CLAUDE.md`).

| If you need to change...                                            | Go to |
|---------------------------------------------------------------------|-------|
| Anything about the form fields (method, URL, auth, body, headers, cookies, flags) | `curl-builder/ui/index.html` — the relevant `<div class="card">`/`<details>` block |
| The generic dynamic key/value row list (used by query params, headers, cookies, urlencoded + multipart body fields) | `index.html` — `makeRowList(...)` |
| Shell-specific quoting/escaping (bash, cmd.exe, PowerShell)          | `index.html` — `quote()` and `contJoiner()` |
| How the final curl command string is assembled from form state      | `index.html` — `generate()` / `assemble(shell)` |
| Which manual headers get silently overridden by Auth/Body settings  | `index.html` — `autoHeaderKeys` inside `generate()` |
| Whether the backend does anything beyond serving the page            | `curl-builder/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **No backend processing, intentionally** — same rationale as
  Encode/Decode: nothing typed here (tokens, passwords, bodies) should
  ever leave the browser, and a "run this for me" endpoint would let any
  visitor make the server issue arbitrary outbound requests (SSRF). Don't
  add one without re-raising that tradeoff with the owner first.
- **Multipart bodies must never carry a manual `Content-Type` header** —
  curl sets its own with the boundary; the generator already strips a
  manual one and shows a warning, don't remove that guard.
- **File fields are typed paths, not real uploads.** The browser never
  reads the file; the path only needs to exist on whatever machine
  actually runs the generated command.
- Mounted at `/tools/curl-builder/` by `main.py` — this folder is a fully
  self-contained ASGI app and doesn't need to know that.

---

## Tool: HTTP Header Reference — mounted at `/tools/header-reference/`

Entirely client-side — the Python backend (`header-reference/server.py`)
only serves the static page; the glossary itself is a data array baked
into the page, no lookups of any kind happen over the network.

| If you need to change...                                            | Go to |
|-----------------------------------------------------------------------|-------|
| Add, correct, or re-categorize a header                              | `header-reference/ui/index.html` — `HEADERS` array |
| Add/edit a category or its plain-language definition                 | `index.html` — `CATEGORIES` array |
| Search/filter behavior                                                | `index.html` — `matches()` |
| The "Related" cross-reference chips (jump to another header)         | `index.html` — `jumpToHeader()` |
| Sidebar per-category counts                                           | Computed live in `renderSidebar()` from `HEADERS` — never hand-maintained |
| Whether the backend does anything beyond serving the page             | `header-reference/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **No backend processing, intentionally** — same rationale as
  Encode/Decode and cURL Builder: nothing the user types (search text)
  needs to leave the browser, and there's nothing to look up server-side
  since the glossary is static data.
- **Deliberately scoped to browse-only, not paste-and-analyze.** The user
  was offered a choice between a browsable glossary, a paste-your-headers
  analyzer, or both — they chose the glossary alone. Don't add a
  paste-and-analyze mode unprompted; it needs its own header-text parser
  that doesn't exist here.
- **Each header has exactly one canonical entry, in exactly one
  category** — a header relevant to more than one category (e.g. `Origin`
  matters to both Request Context and CORS) lives under whichever
  category best explains its primary purpose, and is cross-referenced via
  `related` from the other category's entries instead of being
  duplicated. Duplicating an entry would double-count it in search
  results and in the sidebar's per-category counts.
- **`related` array entries are exact, case-sensitive header names** —
  `jumpToHeader()` does a plain equality lookup; a typo there just fails
  silently (click does nothing) rather than erroring.
- Mounted at `/tools/header-reference/` by `main.py` — this folder is a
  fully self-contained ASGI app and doesn't need to know that.

---

## Tool: HTTP Methods & Status Codes — mounted at `/tools/http-methods-status/`

Entirely client-side — the Python backend (`http-methods-status/server.py`)
only serves the static page; both reference sets (methods, status codes)
are data arrays baked into the page.

| If you need to change...                                            | Go to |
|-----------------------------------------------------------------------|-------|
| Add/edit a method (examples, edge cases, best practices, mistakes)   | `http-methods-status/ui/index.html` — `METHODS` array |
| Add/edit a status code (meaning, when-to-return, examples, compare)  | `index.html` — `STATUS_CODES` array (grouped by `cls`) |
| Add/edit a Decision Guide question (either tab)                       | `index.html` — `METHOD_GUIDE` / `STATUS_GUIDE` arrays |
| Search/filter behavior                                                | `index.html` — `methodMatches()` / `statusMatches()` |
| Status class filter chips (1xx–5xx)                                   | `index.html` — `renderClassChips()` |
| Whether the backend does anything beyond serving the page             | `http-methods-status/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **The Decision Guide is the reason this tool exists, not a bonus
  feature.** It was built specifically to answer "which one do I pick"
  questions (PUT vs PATCH, 401 vs 403, 301 vs 308, 500 vs 502, etc.) — if
  you redesign this tool's layout, keep it prominent (open by default,
  above the searchable list), don't collapse it into an afterthought.
- **`compare` on a status-code entry is inserted as raw HTML, not
  escaped** (so it can bold the "vs NNN" lead-in) — every other field
  (`meaning`, `whenToReturn`, example notes) IS escaped via `escHtml()`.
  Only hand-written trusted text belongs in `compare`.
- **`compare` is deliberately sparse** — only set on the ~13 codes with a
  genuinely common real-world confusion, not added to every code for
  symmetry. Adding it everywhere would bury the comparisons that actually
  matter.
- **A method's `idempotent` field isn't always boolean** — PATCH uses the
  string `'Usually, not guaranteed'` because that's the honest, spec-
  accurate answer (idempotency there depends entirely on the patch
  document's semantics). `methodBadges()` already handles the
  string-vs-boolean split; don't assume boolean elsewhere.
- **No backend processing, intentionally** — same rationale as every
  other reference tool in this toolbox.
- Mounted at `/tools/http-methods-status/` by `main.py` — this folder is
  a fully self-contained ASGI app and doesn't need to know that.

---

## Tool: Cookie Lab — mounted at `/tools/cookie-lab/`

No backend processing (`cookie-lab/server.py` only serves the static
page) — but unlike every other client-side tool here, this one is **not
purely static**. Its frontend performs real, persistent reads and writes
against `document.cookie`, a live browser API — a deliberate live
playground, not a generator (see the tool's own `CLAUDE.md` for the full
rationale; don't mistake this for a "no backend processing" violation).

| If you need to change...                                            | Go to |
|-----------------------------------------------------------------------|-------|
| The cookie-string builder / pre-click validation warnings             | `cookie-lab/ui/index.html` — `buildCookieString()` / `validateForm()` |
| How a Set Cookie attempt is diagnosed (accepted/rejected + why)       | `index.html` — `setCookieLive()` / `diagnoseOutcome()` |
| Parsing `document.cookie` into the live "Current Cookies" view        | `index.html` — `parseDocumentCookie()` / `renderCurrentCookies()` |
| The "Configured This Session" memory + delete actions                 | `index.html` — `configuredCookies` Map, `recordConfigured()`, `deleteConfigured()` |
| Suggested Experiments cards                                           | `index.html` — `EXPERIMENTS` array |
| Theory/reference content, categories                                  | `index.html` — `THEORY` / `THEORY_CATEGORIES` arrays |
| Decision Guide questions                                              | `index.html` — `COOKIE_GUIDE` array |
| Whether the backend does anything beyond serving the page             | `cookie-lab/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **`Secure` will likely still succeed on `http://localhost:8000`, not
  get rejected** — browsers treat `localhost` as a trustworthy origin
  regardless of scheme, which is what the Secure check actually verifies.
  The tool's copy reflects this as an honest live diagnosis, not a
  canned "rejected" assumption — don't "correct" it to claim rejection.
- **`HttpOnly` set via `document.cookie` drops the ENTIRE write, not just
  that flag.** The checkbox stays enabled on purpose so the user can
  trigger and observe this, rather than being grayed out.
- **`Path` is validated differently than `Domain`** — an unrelated Path
  is never rejected at set-time, only invisible from documents whose
  path doesn't match it; `Domain` IS actively validated and can be
  rejected outright. Copy throughout keeps this distinction precise.
- **The "delete with wrong Path" demo deliberately omits `Max-Age`**
  rather than using `Max-Age=0` — a `Max-Age=0` write to a path with no
  existing cookie is a silent, invisible no-op that teaches nothing; the
  real classic bug (a second, visible, empty-valued sibling cookie
  appearing instead of a clean delete) requires the write to actually
  persist, which needs no expiry at all.
- **No true cross-subdomain `Domain` demo is possible** — this tool is a
  single page on a single host; genuinely testing subdomain-sharing
  behavior needs two real subdomains, which this deployment doesn't
  have. That stays theory-only, stated explicitly in the Reference tab.
- **jsdom (used during this tool's development) is not faithful for**:
  the localhost-Secure exception, `SameSite=None`-requires-`Secure`
  enforcement, HttpOnly's whole-write-drop behavior, `__Host-`/
  `__Secure-` prefix enforcement, and the ~4KB size limit (confirmed
  directly — a 5KB value round-tripped successfully under jsdom, where a
  real browser would drop it) — its `tough-cookie`-backed jar doesn't
  model these browser-specific behaviors. Changes touching them need
  manual verification in a real browser against the running deployment.
- Mounted at `/tools/cookie-lab/` by `main.py` — this folder is a fully
  self-contained ASGI app and doesn't need to know that. Its default
  cookie Path is `location.pathname` (not a hardcoded `/tools/cookie-lab/`)
  for the same relative-path reason every tool's own API calls use
  relative paths — see the root `CLAUDE.md`.

---

## Tool: DataDiff Pro — mounted at `/tools/datadiff-pro/`

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| How JSON / XML / CSV text gets parsed into Python objects              | `core/normalizer.py` |
| XML-specific quirks (attributes, `xsi:nil`, list detection)            | `core/normalizer.py` (`_parse_xml` and helpers) |
| CSV delimiter sniffing / cell type coercion                            | `core/normalizer.py` (`_parse_csv`, `_coerce_csv_value`) |
| Field renaming / restructuring rules ("Field Mapper" panel)            | `core/mapper.py` |
| Generic nested path lookup/insert/delete used by the mapper & validator | `core/path_resolver.py` |
| The actual left-vs-right comparison logic, MATCH/MISMATCH/EQUIVALENT   | `core/diff_engine.py` |
| How two lists of objects get paired up before comparing                | `core/list_resolver.py` |
| What counts as "equivalent but not equal" (null-likes, bool-likes, numeric tolerance, custom YAML groups) | `core/equivalence.py` |
| "Deep Mode" — parsing string-encoded JSON/XML found inside fields      | `core/deep_expander.py` |
| Post-mapping check for silently dropped fields                         | `core/validator.py` |
| The mapping → deep-expand → equivalence/list-resolver → diff sequence itself (shared with the headless orchestrator, see `orchestrator/CLAUDE.md`) | `core/pipeline.py` (`run_compare`) |
| The `/compare` API contract (request/response shape, error format) — now just validates raw text, calls `normalize()`, then `core.pipeline.run_compare()` | `api/app.py` |
| The FastAPI app object that `main.py` mounts                           | `api/app.py` (`app = FastAPI(...)`) |
| The frontend: layout, results table, filters, export (JSON/CSV/Excel)  | `ui/index.html` (single file, no build step) |
| "Load from Vault" (per side, size-capped at 2000 rows by default)     | `ui/index.html`'s `refreshVaultDatasetSelects()`/`loadVaultDataset()` — calls `vault/server.py`'s `GET /datasets/{id}/preview`, same-origin, no proxy |
| Example equivalence-rule / list-key YAML config                        | `environments/example.yaml` |
| Batch/large-file comparison outside the browser                        | `notebook/compare_automation.ipynb` |

### Data flow (in call order)

```
ui/index.html --POST /compare--> api/app.py
  -> core/normalizer.py     (parse both sides)
  -> core/deep_expander.py  (only if deep_mode)
  -> core/mapper.py         (only if a field mapping was supplied)
       -> core/path_resolver.py   (path lookups used internally)
  -> core/validator.py      (only if a mapping was applied)
  -> core/equivalence.py + core/list_resolver.py   (built inside api/app.py,
       then handed to DiffEngine)
  -> core/diff_engine.py    (the actual comparison, returns DiffResult)
<- api/app.py returns JSON -> ui/index.html renders the table
```

### Known non-obvious behavior (read before touching these areas)

- **Frontend API calls must stay relative** (`fetch('compare', ...)`, never
  `fetch('/compare', ...)`). This is what lets `ui/index.html` work both
  mounted at `/tools/datadiff-pro/` and if ever run standalone. Any new
  fetch call added to the frontend must follow this.
- **`core/mapper.py`'s `_apply_single`** used to silently drop intermediate
  target-path segments when the target path was deeper than the source path
  (e.g. `a` → `x.y` produced `{"y": ...}` instead of `{"x": {"y": ...}}`).
  Fixed — see git log for `core/mapper.py`. If touching the leaf-rename
  branch again, re-run the depth-mismatch case as a regression check.
- **`core/list_resolver.py`'s `resolve()`** used to silently drop any
  non-dict item sharing a list with dict items (no EXTRA_LEFT/RIGHT record
  at all). Fixed — mixed lists now get the dict items paired normally and
  the leftover scalar items paired by index, merged into one result. If
  touching `resolve()`, re-check a mixed dict+scalar list still surfaces
  every item.
- **XML root tag is deliberately kept as a data key**, not unwrapped (see
  `_unwrap_xml_lists`'s docstring in `core/normalizer.py`) — this is so XML
  and its JSON equivalent produce the same top-level shape. Don't "fix" this
  by unwrapping the root; it would break XML-vs-JSON comparisons.

---

## Tool: DataFrame Studio — mounted at `/tools/df-studio/`

Click-driven pandas: load CSV/JSON/XML/Parquet, transform via UI
(rename/drop/add column, filter, sort, or a free-form Query box with
Check/Add-to-pipeline modes and quick-insert snippets), inspect
(describe/info/nunique/value counts), export — as a file, as a standalone
`.py` script, or save the pipeline as a reusable named template. Every
step shows the pandas line it maps to. See `df-studio/CLAUDE.md` for the
full picture.

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| Session state, the replay model, file loading, insights, script export, template replay, the Check/Add split (`preview_step`/`apply_step`) | `df-studio/engine.py` |
| A transformation step's behavior or its generated pandas code line     | `df-studio/steps.py` (`STEP_HANDLERS`) |
| API endpoints (`/load`, `/load/vault`, `/step`, `/step/check`, `/insight`, `/export`, `/script`, `/template/*`) | `df-studio/server.py` |
| Saved-template storage (JSON on disk)                                  | `df-studio/templates_store.py` |
| The frontend: grid (Tabulator.js), "load from Vault" picker, form-based step fields, Query box (Check/Add + snippets), pipeline panel, script/template panels | `df-studio/ui/index.html` |
| Loading a saved Vault dataset in as a new session (the consumer side of duck-lab's/sql-studio's `/export/vault`) | `df-studio/server.py`'s `/load/vault` — decrypts via `core.vault.load_dataset_file()`, reads the bytes, then reuses the exact same `engine.load_dataframe()`/`create_session()` path `/load` uses for an upload |
| Adding a brand-new form-based step type                                | `steps.py` (handler) **and** `ui/index.html` (`#f-<type>` fieldset + `<option>`) |
| Adding a new Query-box quick-insert snippet                            | `ui/index.html` — `SNIPPETS` object only, no backend change |

### Known non-obvious behavior (read before touching these areas)

- **Sessions are in-memory only** (`engine.SESSIONS`) — restarting the
  server drops every open session. No persistence to disk by design.
- **The "current" DataFrame is always recomputed by replaying `steps` over
  `original_df`** (`engine.recompute`), never mutated in place — this is
  what makes removing a step from the middle of the pipeline just work.
- **`add_column`/`filter_rows` use `df.eval`/`df.query(engine="python")`** —
  arithmetic, comparisons, string concat on bare column names only, not
  arbitrary Python. The Query box's `custom_code` step is the escape hatch
  for that (real `exec()`, `pd`/`np` in scope, **no sandboxing** —
  deliberate, single-user local tool; revisit before this is ever exposed
  beyond one trusted user). Check mode (`/step/check`) still `exec()`s the
  code — it's a "don't commit yet" toggle, not a safer sandbox.
- **Step handlers raise plain `ValueError`, never `engine.StepError`** —
  `StepError` is a subclass, so `except StepError` alone misses them. This
  bit `engine.apply_template()` for real (a step failing mid-template
  crashed with an unhandled 500 instead of a clean `template_errors`
  response) — fixed by catching `ValueError`. Match that in any new
  per-step try/except.
- **The grid caps preview rows at `engine.PREVIEW_ROW_CAP` (5000)** but
  `/export` and `/script` always run against the full DataFrame — a bigger
  export than the table showed is expected, not a bug.
- **Templates persist `{type, params}` only, never the generated code** —
  code is regenerated from the live `STEP_HANDLERS` on every apply, so a
  codegen fix in `steps.py` automatically improves old saved templates.
- **This is the one tool copied as a whole folder in `../Dockerfile`**
  (`COPY df-studio/ ./df_studio/`) instead of the usual two-line
  `server.py` + `ui/` copy, because it has extra backend modules. Its
  `server.py`/`engine.py` use a try/except dual import so the tool still
  runs standalone from inside `df-studio/` for dev, not just mounted.
- **`/load/vault` reads the whole decrypted dataset into memory**
  (`content = await asyncio.to_thread(tmp_path.read_bytes)`) before
  calling `engine.load_dataframe()` — consistent with this tool's own
  accepted design (every upload is already fully materialized into
  pandas, unlike duck-lab), not a new ceiling introduced by this
  endpoint. Unlike duck-lab's equivalent endpoint, this one DOES wrap
  its vault/file calls in `asyncio.to_thread`, matching every other
  pandas-touching endpoint in this file (duck-lab's own convention is the
  opposite — direct synchronous calls — because duck-lab never runs
  pandas on the request path).

## Tool: SQL Studio — mounted at `/tools/sql-studio/`

A Postgres SQL workspace: paste/edit/pretty-print a query (arbitrary
complexity, comments preserved), an optional schema panel — paste
`{"table_name": {"column_name": "data_type"}}` to get table/column
autocomplete, or click "⚡ Fetch Schema" (in the main toolbar, next to
Run) to fetch and load it live once connected — a schema-filter dropdown
right next to it picks which schema(s) to pull from (one, several, or
"All schemas"; not hardcoded to `public`), with same-named tables across
different schemas auto-disambiguated as `schema.table` only when they'd
actually collide — several named query buffers/tabs, keyboard shortcuts
(Ctrl+Enter format, Ctrl+Shift+Enter Run, Ctrl+K template
search, Ctrl+F find/replace floating top-right of the editor VS
Code-style, auto-format on paste), a Templates panel (sidebar, between
Connection and Schema) with ~125 prebuilt Postgres/PL/pgSQL snippets that
insert at the cursor as real Tab-navigable fields, live-filtered against
whatever you're typing with the last word weighted highest — and a
**live Run against a real Postgres database**: a Connection panel (top of
the sidebar, collapsed by default, collapses to a compact status line
once connected) opens a server-side pool of up to 3 connections, Run
executes exactly one statement at a time with a hard 500-row cap enforced
by Postgres itself (`LIMIT`-wrapped, not fetched-then-truncated),
destructive statements (`DROP`/`TRUNCATE`/`DELETE`/`ALTER`) require an
explicit confirm, and results show in a dismissible overlay with CSV/JSON
export — plus **32 "show" commands** (`show tables`, `show table orders
definition`, `show functions`, `show triggers`, `show activity`, ...), a
`psql \d`-family equivalent typed as plain phrases: type one and press
Run, the real system-catalog SQL runs in its place, results show the
same way. They're listed in the Templates panel (typing "show" surfaces
them) and in a full cheatsheet behind the "?" button next to Run. Format,
Templates, and Schema autocomplete remain 100% client-side and
unaffected — only Run/Connect/Export/schema-fetch touch
`sql-studio/server.py`'s backend routes (`db_engine.py`/`query_guard.py`);
show commands are a pure client-side text substitution before Run's
normal pipeline, not a new backend capability.
**Only the header's old "🧩 Templates" nav button was removed** (at the
owner's explicit request) — the Templates panel itself was NOT removed
and is still fully present and always visible; `Ctrl+K` still jumps to
its search box the same way the button used to. See
`sql-studio/CLAUDE.md`'s "Live database connection (Run)" section for the
full Run design (why one global connection instead of df-studio's
per-cookie pattern, the row-cap mechanism's real limits, the
two-copies-kept-in-sync tokenizer).

| If you need to change...                                              | Go to |
|-------------------------------------------------------------------------|-------|
| The CodeMirror editor setup (extensions, basicSetup, keymap, search, paste handler, doc-change listener) | `sql-studio/ui/index.html` — `view`/`EditorState.create(...)` |
| How the pasted schema JSON becomes autocomplete suggestions             | `index.html` — `buildSchemaNamespace()` |
| Applying a newly-pasted schema without rebuilding the editor            | `index.html` — `sqlLangCompartment` / `makeSqlExtension()` / `applySchema()` |
| Format behavior (indentation, keyword case, dialect)                   | `index.html` — `formatQuery()` (`sqlFormat(...)`) — called from the Format button, Ctrl+Enter, and paste-triggered auto-format alike |
| Formatting inside a `$$...$$` stored procedure/function body            | `index.html` — `reformatDollarQuotedBodies()` + `formatPlpgsqlBody()` (sql-formatter itself never touches dollar-quoted content — see `sql-studio/CLAUDE.md` for the known limitations of this hand-rolled pass) |
| Buffer tabs (add/close/rename/switch), migration from the old single-query key | `index.html` — `loadBuffers()`, `switchBuffer()`/`addBuffer()`/`closeBuffer()`/`renameBuffer()`, `renderBufferTabs()` |
| Keyboard shortcuts (Ctrl+Enter format, Ctrl+Shift+Enter Run, Ctrl+K template search) | `index.html` — the `keymap.of([...])` extension in `view`'s config (Format/Run), and the global `keydown` listener near the bottom of the script (Ctrl+K) |
| Ctrl+F find/replace (functionality is stock CodeMirror; only its position/look is custom) | `index.html` — `search({ top: true })` extension + `#editor .cm-panel.cm-search` CSS block (see `sql-studio/CLAUDE.md` for the DOM structure this CSS targets) |
| Auto-format on paste                                                    | `index.html` — `EditorView.domEventHandlers({ paste: ... })` in `view`'s config, `chkAutoFormat` |
| Schema panel parsing/validation/persistence                            | `index.html` — `applySchema()`, `schemaErr` box |
| The "copy schema-fetch query" pgAdmin round-trip helper                 | `index.html` — `SCHEMA_FETCH_QUERY` const, `btnCopySchemaQuery` (uses `json_object_agg`, not `jsonb_object_agg` — see `sql-studio/CLAUDE.md` for a real ordering bug caught by testing against an actual Postgres) |
| Fetching + loading the schema live from the connected database          | `index.html` — `btnFetchSchema` click handler (runs `buildSchemaFetchQuery(getCurrentSchemaFilter())` via `POST /query`, then `applySchema()`) — shares the same query-builder as the manual-copy path (`btnCopySchemaQuery`) above |
| Which schema(s) Fetch Schema pulls from, adding/changing the schema-filter dropdown | `index.html` — `#btnSchemaFilter`/`#schemaFilterPanel`, `schemaFilterAll`/`selectedSchemas` state, `getCurrentSchemaFilter()`, `ensureSchemaListLoaded()`, `resetSchemaFilterState()` (called from `applyConnectionStatus()` on connect/disconnect) — see `sql-studio/CLAUDE.md` for the cross-schema table-name-collision handling in `buildSchemaFetchQuery()` |
| The Templates library (adding/editing snippets, categories, search)     | `index.html` — `TEMPLATES` array (one `{cat, name, sql}` per entry — add a template by adding an entry, nothing else to wire up) |
| The live "type to find it" ranking (last-word priority)                | `index.html` — `currentLineWords()` + `scoreTemplate()` (see `sql-studio/CLAUDE.md` for how the weighting works and how it was verified) |
| Templates panel rendering / search / insertion                          | `index.html` — `renderTemplateList()`, `insertTemplate()` (live mode replaces the trigger word via `currentLineLastWordSpan()`; blank-line padding uses `isAtLineStart()`/`isAtLineEnd()`, whitespace-aware not just single-character — see `sql-studio/CLAUDE.md` for two real bugs found here) |
| Which words in a template become Tab-stop fields, adding a new one     | `index.html` — `PLACEHOLDER_TOKENS` Set (whitelist, not auto-detected) + `toSnippetTemplate()` — see `sql-studio/CLAUDE.md` for how the whitelist was built and verified against all 125 templates |
| localStorage keys for restoring buffers/schema on reload                | `index.html` — `BUFFERS_KEY` (`sql_studio_buffers`), `ACTIVE_BUFFER_KEY` (`sql_studio_active_buffer`), `SCHEMA_KEY` (`sql_studio_schema`), `AUTOFORMAT_KEY` (`sql_studio_autoformat_on_paste`), `CONNECTION_KEY` (`sql_studio_connection` — host/port/database/username only, password never persisted); `QUERY_KEY` (`sql_studio_query`) is legacy, read-only, for one-time migration into buffer #1 |
| The live Postgres connection pool (connect/disconnect/status, idle reaper) | `sql-studio/db_engine.py`'s `_POOL` — a `core.pooled_postgres.PooledPostgresConnection` (module-level, singular — see `sql-studio/CLAUDE.md` for why NOT a per-cookie dict). The pool+reaper mechanics (`connect()`/`disconnect()`/`status()`/`_reaper_loop()`) live in `core/pooled_postgres.py`, shared with `schema-map/db_engine.py`'s own separate instance — see `../CLAUDE.md`'s connector-consolidation note |
| Whether a query is allowed to run, the destructive-statement check, the `LIMIT 500` wrap | `sql-studio/query_guard.py` — `prepare()` (entry point), `classify()`, `split_statements()` — the server-side, authoritative copy; `index.html`'s `splitTopLevelStatements()`/`firstStatementKeyword()` is the client-side UX-only twin, kept in sync by hand |
| Connect/Disconnect/Run/Export backend routes                            | `sql-studio/server.py` — `/connect`, `/disconnect`, `/status`, `/query`, `/export/csv`, `/export/json`, `/export/vault` (the uncapped, streamed-to-Vault export — see `db_engine.export_to_file`) |
| Connection panel UI (collapsed-by-default ↔ full-form ↔ collapsed-status-line, localStorage persistence) | `index.html` — `applyConnectionStatus(status, forceOpen)`, `loadConnectionFields()`/`saveConnectionFields()`, `#detConnection` (see `sql-studio/CLAUDE.md` for the `forceOpen` rule — only Disconnect's click handler passes `true`) |
| Run button, the results overlay, the destructive-confirm dialog          | `index.html` — `runQuery()`/`sendQuery()`, `renderResults()` (`#resultsDialog`), `openConfirmDialog()` (`#confirmDialog`) |
| The "show tables"/"show table X definition"/etc. commands — adding one, changing the mapped SQL, the "?" cheatsheet | `index.html` — `SHOW_COMMANDS` array (single source of truth for matching AND the cheatsheet AND the Templates entries), `matchShowCommand()`, `buildHelpDialog()` (`#helpDialog`) — see `sql-studio/CLAUDE.md`'s "Show commands" section before touching array order |

### Known non-obvious behavior

- **Loaded via `<script type="module">`, not a plain `<script>`** — the
  only tool in the Toolbox that does this. CodeMirror 6 is ESM-only, so its
  packages (and `sql-formatter`) are imported directly from esm.sh rather
  than a classic `<script src>` tag like df-studio's Tabulator.js.
- **CodeMirror 6 needs all its packages to resolve to one shared instance**
  of `@codemirror/state`/`@codemirror/view`, or importing them separately
  causes an "Unrecognized extension value" runtime error — hit for real
  while building this tool. Fixed by importing `@codemirror/state` as the
  version *range* `@^6.0.0` (matching the range baked into `codemirror`'s
  own bundle) via esm.sh, so both resolve to the same shim URL. See
  `sql-studio/CLAUDE.md` for the full verification trail — don't change
  these import URLs without re-reading it.
- **`sql-formatter` throws on unparseable SQL** rather than best-effort
  formatting — surfaced in the red error box under the editor, not
  swallowed silently.
- **A structure Outline panel (parsed DECLARE/IF/LOOP/CASE tree, click to
  jump, click-a-variable-to-highlight-its-uses) existed briefly and was
  removed** at the owner's request — too much sidebar/scroll weight for
  this tool's actual workflow. It's not recoverable from git history
  (`sql-studio/` — really the whole repo — is untracked, no VCS at all) —
  see `sql-studio/CLAUDE.md` for the approach if it's ever rebuilt. The
  Templates panel is a **different** case — it's still fully present, see
  the next bullet; only its header nav button was removed.
- **Only the header's old "🧩 Templates" nav button was removed, NOT the
  Templates panel** — the panel (~125-snippet searchable library with
  live-filtering and Tab-stop snippet fields) is still fully present and
  always visible in the sidebar, between Connection and Schema. The
  button just used to open/scroll to it and focus search; `Ctrl+K` still
  does that exact same thing. Don't confuse this with the Outline panel
  above, which really was removed entirely — these are two different
  histories for two different features.
- **The sidebar (`.col-right`) DOES cap its own height and scroll
  independently** (`max-height: calc(100vh - 40px); overflow-y: auto`,
  still `position: sticky`) — **this is a reversal of an earlier
  decision, not an oversight.** The identical change was tried once right
  after the Outline panel shipped, explicitly reverted at the owner's
  request, and documented here as "don't reintroduce without asking
  again." The owner then asked again, once Connection + Templates + 32
  show commands + Schema stacked in one column made an unbounded sidebar
  genuinely unusable (confirmed by the owner's own screenshot). See
  `sql-studio/CLAUDE.md`'s "What this tool is" section for the full
  history — if this gets reverted a second time, treat that the same way
  as the first revert (don't silently re-add it without being asked).
- **Ctrl+F's find/replace panel floats top-right of the editor instead of
  its library-default full-width bottom bar** — the find/replace
  functionality itself is 100% stock `@codemirror/search` (bundled into
  `basicSetup`'s `searchKeymap`, no custom logic); only its position and
  look are overridden (`search({ top: true })` + `#editor .cm-panel.cm-
  search` CSS, `position: absolute` anchored to `#editor`). See
  `sql-studio/CLAUDE.md` for the DOM structure that CSS depends on.
- **Buffer tabs replaced a single flat `sql_studio_query` key** with an
  array (`sql_studio_buffers`) — an existing user's previously-saved query
  is migrated into buffer #1 automatically on first load after this
  shipped, verified against fresh-install/migration/existing-buffers/
  corrupted-JSON scenarios with a standalone Node test before shipping.
- **The paste event fires before CodeMirror inserts the pasted text** —
  auto-format-on-paste's handler has to `setTimeout(fn, 0)` before calling
  `formatQuery()`, or it formats the doc as it was *before* the paste.
- **The live Postgres connection is one global value, not per browser
  tab** — every open tab shares the same connection/pool and sees the same
  `GET /status`. This is deliberate (the owner asked for "a single
  database at a time" with "a pool of 3"), not a missed per-session-cookie
  pattern — see `sql-studio/CLAUDE.md` for why copying df-studio's
  per-cookie `SESSIONS` shape here would have broken that constraint.
- **The idle-connection reaper starts lazily on first successful
  `/connect`, not via a FastAPI `lifespan` hook** — `main.py` mounts every
  tool via `app.mount(...)`, and Starlette does not forward lifespan
  events into mounted sub-apps, so a `lifespan=` handler here would
  silently never run. See `sql-studio/CLAUDE.md`'s "Live database
  connection (Run)" section.
- **Run is hard-limited to exactly one statement, and rejects `COPY`
  outright** — both checked via `query_guard.py`'s statement splitter
  (server-side, authoritative) and `index.html`'s `splitTopLevelStatements()`
  (client-side, UX-only fast path). A `;` or a keyword inside a string,
  comment, or `$$...$$` dollar-quoted body is never mistaken for a
  statement boundary — both implementations reuse the same
  string/comment/dollar-quote-aware tokenizing rules as the PL/pgSQL
  formatter's own `tokenizePlpgsqlBody()`.
- **Export never re-runs the query — it serializes the last cached
  result** (`db_engine._last_result`, a module-level variable local to
  sql-studio — deliberately not part of the shared pool class, since
  it's this tool's own concern — set on every successful rows-shaped
  `/query`, cleared on every non-rows one and explicitly on disconnect).
  Re-querying on export would double-execute a `DELETE`/`UPDATE`; this is
  why it doesn't.
- **The 500-row cap is enforced by an outer `LIMIT` at Postgres itself**
  (`SELECT * FROM (<query>) AS _sq LIMIT 500`), not fetched-then-truncated
  in Python — guarantees the row count returned, but does **not** by
  itself guarantee bounded query *cost* for aggregate/`GROUP BY`/window
  queries over a huge table (Postgres still computes the full aggregation
  before the outer `LIMIT` trims output). Runtime is bounded separately —
  see the next bullet.
- **A 15-second `statement_timeout` applies to every query, set on the
  connection pool's conninfo** (`db_engine.STATEMENT_TIMEOUT_MS`, passed
  as `statement_timeout_ms` to `PooledPostgresConnection`) — this
  is what actually bounds a slow query, since the row cap above doesn't. A
  query that runs long gets cancelled by Postgres (`QueryCanceled`) and
  surfaced as a clean error instead of hanging one of the pool's 3
  connections indefinitely.
- **The live connection already survives an ordinary browser refresh —
  no session/cookie/client-side storage involved.** `_POOL.state` lives
  in server-process memory; `GET /status` (polled on every page load)
  reports it regardless of how many times the page reloads. Only three
  things actually drop it: the 20-minute idle reaper (passed as
  `idle_timeout_seconds` to `PooledPostgresConnection`), an explicit
  Disconnect click, or the
  server process itself restarting (e.g. `docker-compose up --build` to
  ship a code change) — the last one is easy to mistake for "refresh
  drops it" if a rebuild and a refresh happen close together during
  active development. Verified directly (connect, then poll `/status`
  repeatedly with nothing else touched — stayed connected). Don't add
  session storage or client-side reconnect logic to "fix" this.
- **Run honors a text selection (pgAdmin/DataGrip-style)** — a non-empty
  selection in the editor runs only that selected text
  (`view.state.sliceDoc(...)`), not the whole buffer; no selection falls
  back to the previous whole-document behavior. Covers the Run button,
  `Ctrl+Shift+Enter`, and the destructive-confirm preview all at once,
  since they all just consume whatever `runQuery()` decides `sqlText` is.
- **A `<dialog>`'s `display` CSS must stay scoped to `[open]`** — a real
  bug: `dialog#resultsDialog { display: flex; ... }` with no `[open]`
  qualifier out-specificities the browser's own `dialog:not([open]) {
  display: none; }` (an ID selector beats a type+pseudo-class one), so the
  results panel showed permanently, inline in the page, instead of only
  via `showModal()` on Run. Fixed by moving `display: flex;
  flex-direction: column;` to `dialog#resultsDialog[open]`; sizing rules
  stayed unscoped since they don't affect visibility. See
  `sql-studio/CLAUDE.md` before adding more dialog CSS.
- **The Connection panel starts collapsed and stays that way on a silent
  page-load status check** — only an explicit Disconnect click passes
  `forceOpen: true` to re-expand it. A silent `GET /status` on load must
  never force it open; an earlier version did, which is what the owner
  flagged as "connection should not [be] shown [by] default." See
  `sql-studio/CLAUDE.md`'s "Live database connection (Run)" section.
- **The header has no trust badge at all now** — just the title. Both
  badges that ever existed (the original "100% client-side" one, and a
  later Run-specific second line) plus the descriptive subtitle line were
  each tried and explicitly removed at the owner's request ("wasting
  space, no use case" the first time, "make more space" the second).
  Don't reintroduce any of them without asking again.
- **The "⚡ Fetch Schema" button lives in the main editor toolbar (next to
  Run), not inside the Schema panel** — moved there at the owner's
  request so it's reachable without expanding/scrolling the sidebar. Its
  id (`btnFetchSchema`) and all its JS (click handler, the disabled/title
  toggling in `updateConnectionGatedButtons()`) are unchanged — only its
  HTML position moved, `getElementById` doesn't care where in the page an
  element lives.
- **The Schema panel's two explanatory hint paragraphs were removed**
  ("no one reads this") — `btnLoadExample` survived, relocated to a small
  link next to `btnApplySchema`. The third hint (explaining
  `btnCopySchemaQuery`, directly above that button) was left alone.
- **"show" commands are a pure client-side text substitution, not a new
  backend capability** — `matchShowCommand()` swaps the typed phrase for
  real SQL entirely in the browser, before `POST /query` is ever called;
  `query_guard.py` never sees or knows about "show tables" text. All 32
  are verified against a real Postgres (not written from memory) — see
  `sql-studio/CLAUDE.md`'s "Show commands" section.
- **`SHOW_COMMANDS` array order matters for literal-phrase commands that
  share a prefix with a generic parameterized one** — e.g. `show table
  sizes` must be listed before the generic `show table <name>` pattern,
  or "sizes" gets matched as if it were a table name. Parameterized
  patterns with a trailing suffix (`show table X definition`) don't have
  this problem — they're strictly anchored and can't collide with the
  bare `show table X` form regardless of order.
- **Object definitions are looked up by bare name via explicit catalog
  joins, not `'name'::regclass`/`'name'::regproc` casts** — those depend
  on the connection's `search_path` and silently do the wrong thing for
  anything outside it. See `sql-studio/CLAUDE.md` for the specific bug
  this was rewritten to avoid.
- **Clicking a "?" cheatsheet row runs it immediately for a no-parameter
  command, but only inserts it into the editor for a parameterized one**
  — a real reported friction point, not a design nicety: "Show
  Materialized Views" used to just paste text requiring a manual Run
  press, exactly backwards when the whole point was seeing the list of
  names right away. Each row's small right-aligned tag ("▶ run now" / "✎
  fill in & run") tells you which one to expect before clicking. See
  `sql-studio/CLAUDE.md` for the detection mechanism and its one sharp
  edge (a future parameterized command not written with a `(\S+)`
  capture group would be silently misclassified as run-now).
- **`show table X definition`/`show function X definition`/etc. used to
  render as one unreadable line** — the results `<table>`'s CSS needs
  `white-space: nowrap` for ordinary short-value rows, which silently
  collapsed the real embedded newlines in these DDL results. Fixed by
  detecting the *shape* (one row, one column, the cell is a string
  containing `\n`) and rendering that case as preformatted text instead
  of a table — see `sql-studio/CLAUDE.md` for `.results-definition` and
  why it uses `pre-wrap` rather than plain `pre`.

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
| Projects/Versions (storage + entry-point UI, v2 design Phase A)         | `schema-map/project_store.py` (SQLite, `schema_map_data` Docker volume), endpoints in `schema-map/server.py`, `#projectsScreen`/`#detProject`/`openProject()`/`switchToVersion()` in `schema-map/ui/index.html` — see `schema-map/CLAUDE.md`'s "v2 design, Phase A" |
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

## Tool: Duck Lab — mounted at `/tools/duck-lab/`

Load several CSV/JSON/Parquet/XML files, join/analyze them with SQL via
embedded DuckDB. The gap this fills: DataFrame Studio loads one file fully
into pandas memory; SQL Studio queries a live *Postgres* database, not
local files. CSV/JSON/Parquet are scanned straight off disk by DuckDB
(never read into Python); a query's result is materialized once inside
DuckDB and the UI pages through it with `LIMIT`/`OFFSET` — only one page
of rows is ever sent to the browser. Schema-aware SQL autocomplete (built
from the loaded tables) and a per-table row preview round out the editing
experience. See `duck-lab/CLAUDE.md` for the full picture.

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| Session state, DuckDB connection setup (memory/spill config), CSV/JSON/Parquet/XML loading, query materialization, pagination, export, table preview | `duck-lab/engine.py` |
| API endpoints (`/upload`, `/load/vault`, `/tables`, `/table/remove`, `/preview/{name}`, `/query`, `/page`, `/export`, `/export/vault`, `/session/reset`) | `duck-lab/server.py` |
| The frontend: upload/table list, "load from Vault" picker, preview panel, CodeMirror SQL editor + schema autocomplete, results table + pagination, query time | `duck-lab/ui/index.html` |
| Loading a saved Vault dataset in as a new table (the consumer side of `/export/vault`) | `duck-lab/server.py`'s `/load/vault` — decrypts via `core.vault.load_dataset_file()`, moves the result into the session's own `data_dir` (not a tempfile) since `engine.load_file()` builds a LAZY view backed by that path, then loads it exactly like an upload |

### Known non-obvious behavior (read before touching these areas)

- **Sessions are in-memory only** (`engine.SESSIONS`), same accepted
  tradeoff as df-studio — a restart drops every open session and its
  uploaded files/DuckDB connection.
- **CSV/JSON/Parquet never touch Python memory** — `read_csv_auto()`/
  `read_json_auto()`/`read_parquet()` point DuckDB directly at the saved
  file path. **XML is the one exception**: parsed once via
  `core.normalizer.normalize()` (same code DataDiff Pro uses) into a
  `pandas.DataFrame`, then `con.register()`ed into DuckDB — fully in
  Python memory, same ceiling DataDiff Pro's XML handling already has.
- **Schema autocomplete is reconfigured, not rebuilt, on every table
  change** — `ui/index.html`'s `sqlCompartment` (a CodeMirror
  `Compartment`, same technique as sql-studio's pasted-schema box) gets a
  fresh `sql({schema: ...})` via `refreshSchemaAutocomplete()` inside
  `refreshTables()`. A code path that mutates `STATE.tables` without going
  through `refreshTables()` will leave autocomplete stale.
- **`/preview/<name>` is unrelated to `/query`'s `_result`** — it reads
  the named source directly, independent of whatever query was last run.
- **`/load/vault` reuses `engine.load_file()` as-is** — the decrypted
  file gets a fresh UUID-prefixed name under the session's `data_dir`
  (same naming scheme `/upload` already uses), so the resulting table
  name is sanitized/de-duplicated the same way an upload's would be; it
  doesn't come back out named exactly what you typed in the "load from
  Vault" picker. Check `/tables`'s `name` field (not `source_file`) for
  what to actually type in SQL, same caveat as any upload.
- **A query result is a session-scoped DuckDB TEMP TABLE
  (`_result`), not a Python value.** `/query` materializes it once;
  `/page` just re-slices it with `LIMIT`/`OFFSET` — no recomputation of
  the join per page. `CREATE OR REPLACE` means only one `_result` exists
  per session at a time.
- **`PRAGMA memory_limit='512MB'` + a session-scoped `temp_directory`**
  are set on every connection at creation (`engine._new_connection()`) —
  this is what lets DuckDB spill a big materialized result to disk
  instead of the container OOMing, not just the pagination on top of it.
- **This is a THIRD stateful tool under `--workers 1`** (alongside
  df-studio and sql-studio) — see `../Dockerfile`'s CMD comment and
  `../CLAUDE.md`'s "Standing rule: stateful tools and `--workers`".
- **Copied as a whole folder in `../Dockerfile`**
  (`COPY duck-lab/ ./duck_lab/`), same reason as df-studio/sql-studio —
  extra backend module (`engine.py`) beyond `server.py`. Imports
  `core.normalizer` directly for XML, so it must be copied after `core/`.

## Tool: Vault — mounted at `/tools/vault/`

A management page for `core/vault.py`'s shared, encrypted secret store —
list/delete/clear only, no add-new-secret form (creating one is always
done from the tool that uses it, e.g. sql-studio's "Save this
connection"). Started to fix one pain: sql-studio/schema-map's idle
reaper drops the live DB connection after 20 minutes, and retyping
credentials every time was real friction. **Grew a second, bigger
purpose**: a generic hand-off point for feeding one tool's output into
another as input (e.g. a transformed Postgres query result → DataDiff
Pro), with memory use bounded regardless of dataset size — see
`vault/CLAUDE.md`'s "datasets" section. See that file for the full
picture, especially its security posture (no master password, by
deliberate owner choice).

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| The actual encryption/storage (SQLite + Fernet, on the `vault_data` volume) | `core/vault.py` |
| Credential save/load (small, whole-value encryption) | `core/vault.py` (`save_secret`, `get_secret`, `get_secret_by_name`) |
| Dataset save/load (chunked encryption, bounded memory regardless of size) | `core/vault.py` (`save_dataset`, `load_dataset_file`, `load_dataset_file_by_name`, `CHUNK_SIZE`) |
| API endpoints (`GET /secrets`, `POST /secrets`, `GET /secrets/{id}/reveal`, `DELETE /secrets/{id}`, `POST /clear`) | `vault/server.py` |
| The management page itself (list/delete/clear) | `vault/ui/index.html` |
| Producing a dataset to save (Postgres → Vault, DuckDB result → Vault) | `sql-studio/server.py`'s `/export/vault` (streaming cursor), `duck-lab/server.py`'s `/export/vault` (DuckDB `COPY TO`) |
| Consuming a saved dataset headlessly, any size | `orchestrator/recipes/compare.py`'s `"vault_dataset"` source kind |
| Consuming a saved dataset in a browser, size-capped (DataDiff Pro only) | `vault/server.py`'s `GET /datasets/{id}/preview`, `core.vault.preview_dataset_as_csv()`, wired up in `ui/index.html`'s "Load from Vault" buttons — the ONE path that enforces a row cap, since DataDiff Pro's textarea is paste-based |
| Consuming a saved dataset in a browser as a brand-new table/session, uncapped (Duck Lab, DataFrame Studio) | `duck-lab/server.py`'s `/load/vault` (via `core.vault.load_dataset_file()`, loads into a new DuckDB table), `df-studio/server.py`'s `/load/vault` (same function, loads into a new pandas session) — uncapped because each tool already owns its own size story for an ordinary upload (DuckDB disk-backed views, pandas full-materialization) and this just sources the same path from a vault blob instead of an HTTP upload, not a second size policy to keep in sync |

### Known non-obvious behavior (read before touching these areas)

- **`list_secrets()` must never return decrypted data** — that's the one
  invariant that keeps this page safe to leave open. `get_secret()`/
  `get_secret_by_name()` (credentials) and `load_dataset_file()`/
  `load_dataset_file_by_name()` (datasets) are the only functions that
  decrypt anything, and are called only at the moment a tool is actually
  about to use the secret/dataset — sql-studio/schema-map's "Load saved
  connection," the orchestrator's `--left-vault`/`--right-vault`
  (connections) or `--left-vault-dataset`/`--right-vault-dataset` (data
  — a deliberately different flag, see `orchestrator/CLAUDE.md`).
- **A dataset entry's bulk data is NEVER in `ciphertext`** — that column
  holds only small metadata (`format`/`columns`/`row_count`) for a
  dataset row; the real data is chunk-encrypted separately into a file
  under `blobs/`, named by the row's `blob_path`. This split is what
  keeps `save_dataset()`/`load_dataset_file()`'s memory use bounded by
  `CHUNK_SIZE` (4 MiB) instead of by dataset size — verified directly:
  saving/loading a 61 MB generated file showed essentially the same
  process RSS as an 8 MB one.
- **`has_data` in `list_secrets()`'s output is just `blob_path IS NOT
  NULL`** — `false` for an ordinary credential, `true` for a dataset.
  Doesn't decrypt anything to compute this.
- **No vault master password, by deliberate owner choice** — the
  encryption key lives in a `0600` file on the same volume as the
  encrypted data. Protects against casually reading the DB file or a
  stray backup; does NOT protect against anyone with access to the
  running container. See `vault/CLAUDE.md` for the full writeup and what
  would need to change if the threat model ever does.
- **`core/vault.py` has no opinion on what a given `kind`'s data shape
  is** — sql-studio/schema-map both save `{host, port, database,
  username, password, ssh_tunnel}` under `kind: "postgres_connection"`
  by convention, not because this module enforces it. A new consuming
  tool is free to use its own `kind` and shape.
- **This is a THIRD stateful... actually, it's NOT** — unlike df-studio/
  sql-studio/schema-map/duck-lab, Vault has no in-memory per-worker
  state at all (every call reads/writes SQLite through
  `asyncio.to_thread`, same as `schema-map/project_store.py`) — it
  doesn't add a new entry to `../CLAUDE.md`'s "Standing rule: stateful
  tools and `--workers`" list, even though it's backend-touching.
