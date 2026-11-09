# DNS Lookup — tool-local notes

<!-- O3-pointer -->
> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log. Do not change anything outside this tool's folder unless the task says so.


Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

Live DNS record lookup for any domain, covering all 14 record types a
domain could realistically have (A, AAAA, CNAME, MX, TXT, NS, SOA, CAA,
SRV, NAPTR, DNSKEY, DS, TLSA, SSHFP), with a click-to-explain "?" on every
record type and TTL, so the answer comes with *why it matters* attached.
Two tabs: **Forward Lookup** (domain → records, Phase 1) and **Reverse
Lookup / PTR** (IP → hostname, Phase 2), plus a full field-by-field SOA
breakdown (also Phase 2) instead of the one-line summary Phase 1 shipped
with. Still open for later: a resolution-hierarchy visual, SPF/DKIM/DMARC
parsing.

## The one thing that makes this tool different from the other three

Subnetting and Encode/Decode are fully offline — pure math or pure browser
crypto. **This tool genuinely needs internet access.** There's no offline
substitute for "show me this real domain's real records." It stays
client-side-only (no backend logic, consistent with the rest of the
Toolbox) by calling a public DNS-over-HTTPS (DoH) API directly from the
browser via `fetch()` — Cloudflare (`cloudflare-dns.com/dns-query`) or
Google (`dns.google/resolve`), user's choice via a dropdown. If neither is
reachable (offline, or the provider is blocked on some network), the
lookup fails with a message suggesting the other provider — that's
expected and correct, not a bug to route around.

## How it's built

- `server.py` — serves `ui/index.html` and nothing else, same as every
  other tool here.
- `ui/index.html` — single file, no build step. Same two-part `<script>`
  split as Subnet Calculator:
  1. **`ENGINE`** — pure functions only (`normalizeDomain`,
     `looksLikeDomain`, `humanizeTtl`, `parseMx`, `parseSoa`, `parseCaa`,
     `parseIpv4`, `ipToReverseArpaName`, `isPrivateOrReservedIpv4`,
     `formatRecordData`). No DOM, no `fetch`. Verified with plain `node -e`
     calls before any UI touched them — do the same before changing this
     section.
  2. **`UI WIRING`** — the actual `fetch()` calls to the DoH provider, plus
     rendering (including the tab switching, shared with the Forward and
     Reverse panels). This part can't be node-tested (needs a real network
     call and a DOM), so it was instead checked by curling the real
     Cloudflare/Google endpoints directly and comparing their JSON shape
     against what the code expects (see the exact `curl` commands in the
     commits that introduced this tool if you need to re-verify after a
     change — this includes explicitly proving octet-reversal is mandatory
     for reverse DNS, not optional: the un-reversed name returns SERVFAIL).

## Things that will bite you if you don't know them

- **A record's `Answer` array can contain MORE than one record type.**
  Querying `A` for a domain that's actually a CNAME returns the CNAME row
  *and* the resolved A row it points to, in the same answer. The renderer
  reads each answer's own `type` field (via `DNS_TYPE_NAMES`) rather than
  assuming every row matches the type that was queried — don't "simplify"
  this into just showing the queried type, you'll silently drop the CNAME
  hop that's the whole point of showing it.
- **NXDOMAIN (`Status: 3`) means the domain doesn't exist at all** — it's
  detected separately from "this record type has no answers" (`Status: 0`
  with an empty/missing `Answer`), which is a normal, healthy result (e.g.
  most domains have no TXT SPF record). Conflating the two would tell
  someone their perfectly real domain "doesn't exist."
- **The DoH JSON response has no `Answer` key at all on NXDOMAIN** (only
  `Authority`) — `data.Answer || []` is there specifically to not crash on
  that shape. Confirmed against the real API, not assumed.
- **TXT record `data` comes back wrapped in literal quote characters**
  (`"v=spf1 ..."` as a string containing quotes) — `formatRecordData`
  strips them for display. Don't remove that or every TXT value will show
  with stray quote marks.
- **Reverse DNS requires reversing the IP's octets before querying** —
  `8.8.4.4` becomes `4.4.8.8.in-addr.arpa`, not `8.8.4.4.in-addr.arpa`.
  Getting this backwards doesn't degrade gracefully: the real Cloudflare
  API returns `SERVFAIL` (Status 2) for the un-reversed name, confirmed by
  testing both orders against the same real IP side by side. `ipToReverseArpaName()`
  is the only place this conversion should happen.
- **Private/reserved IPv4 ranges are checked BEFORE firing a reverse-DNS
  request**, not after getting an empty result back — `isPrivateOrReservedIpv4()`
  short-circuits with an explanation instead of a wasted network round-trip
  followed by a confusing blank result.
- **SOA gets a dedicated field-by-field render (`renderSoaFieldGrid`)**,
  bypassing the generic per-record-type table entirely — it's the one
  record type where the `renderResults()` loop branches early. If you
  change the generic table rendering, remember SOA doesn't go through it.
- **Record types with no data are hidden by default, not skipped.** All 14
  types are still queried every time — `buildRecordSection()` just tags
  each result `empty: true/false`, and `renderResults()` only inlines the
  non-empty ones, stashing the rest behind a "Show N record types with no
  data" toggle (`toggleEmptyRecordTypes()`). A failed query (`fetchError`)
  is never treated as empty — that's a real problem, always shown. This
  reversed an earlier "always show all 14 inline" decision after it turned
  out to just read as clutter/confusion on ordinary domains; see
  `../KNOWLEDGE_MAP.md`'s DNS Lookup section for the fuller history if you
  touch this again.
- Mounted at `/tools/dns-lookup/` by `main.py` in the repo root — this
  folder never needs to know that; it's a fully self-contained ASGI app
  either way.
