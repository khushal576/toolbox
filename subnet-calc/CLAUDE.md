# Subnet Calculator — tool-local notes

<!-- O3-pointer -->
> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log. Do not change anything outside this tool's folder unless the task says so.


Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

Interactive IPv4 subnetting: a calculator that shows *how* every answer was
derived (binary bit visualization, worked AND/OR math), not just the
answer — plus a same-subnet checker, a VLSM planner for uneven department
pools, an equal-split calculator, and a supernet/summarization tool. This
covers the full originally-planned scope (equal split + VLSM + supernetting
+ wildcard mask); quiz/practice mode and IPv6 were explicitly descoped.

## How it's built

- `server.py` — serves `ui/index.html` and nothing else. Entirely
  client-side; it's pure arithmetic, no secrets involved, but kept
  client-side anyway for consistency with the rest of the Toolbox and
  instant feedback (no round-trip needed for math this cheap).
- `ui/index.html` — single file, no build step. The `<script>` block is
  split into two clearly-labeled halves:
  1. **`CALCULATION ENGINE`** — pure functions, zero DOM access. This was
     built and verified first (`node -e` against the extracted engine code)
     before any UI was wired to it. Verify a change here the same way
     before touching the UI half.
  2. **`UI WIRING`** — tabs, inputs, rendering. Everything here just calls
     into the engine above it.

## The five tabs

- **Calculator** — IP + CIDR/mask (kept in sync both directions), live bit
  grid, IP-type classification banner, and a worked binary explanation.
- **Compare Two IPs** — same-subnet check, with the reasoning shown, not
  just yes/no.
- **Design Subnets (VLSM)** — one base network, N department rows each with
  a required host count → an allocation plan. Internally sorts
  largest-requirement-first for correct address alignment
  (`planVlsm()`/`minPrefixForHosts()`), but always displays results back in
  the order you typed them — allocation order and display order are
  deliberately different.
- **Split Equal Subnets** — one base network + "how many subnets" → every
  resulting same-size block (`prefixForEqualSplit()`/`splitEqualSubnets()`).
  The complement to VLSM: use this when every pool should be the same size,
  VLSM when they shouldn't.
- **Supernet / Summarize** — the reverse direction: N networks in →
  the one smallest CIDR block covering all of them
  (`commonPrefixLength()`/`summarizeNetworks()`), with overlap detection
  and a "how much unused space does this imply" figure.

## Things that will bite you if you don't know them

- **`maskOctetsToCidr()` returns `null` for anything that isn't a valid
  contiguous mask** (e.g. `255.255.0.1`) — the UI relies on that `null` to
  avoid reacting while the user is still mid-typing. Don't make it throw.
- **`/32` and `/31` are special-cased** in `hostInfo()` (no network/
  broadcast concept at those sizes) — `minPrefixForHosts()` reuses the same
  special-casing, so a 2-host VLSM request correctly comes back as `/31`
  with zero waste. That's correct, not a bug.
- **All bitwise ops use `>>> 0`** to force unsigned 32-bit values — plain
  JS bitwise operators are signed, and dropping this silently breaks any IP
  ≥ `128.0.0.0`.
- **`summarizeNetworks()`'s waste figure is measured against merged actual
  coverage, not the min-to-max span** — a gap between two non-contiguous
  networks correctly shows as waste, not just space beyond the outer edges.
- **The `raw` (originally-typed) label must survive the merge step** in
  `summarizeNetworks()` so overlap warnings can name both networks
  involved — this was lost once during development (merged entries only
  carried `start`/`end`) and produced a warning naming one side `null`.
  If you touch that merge loop, keep `raw` on every merged entry.
- Mounted at `/tools/subnet-calc/` by `main.py` in the repo root — this
  folder never needs to know that; it's a fully self-contained ASGI app
  either way.
