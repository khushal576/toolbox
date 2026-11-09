<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

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
