<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

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
