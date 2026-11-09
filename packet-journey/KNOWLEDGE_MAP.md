<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

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
