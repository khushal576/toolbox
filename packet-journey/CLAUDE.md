# Packet Journey — tool-local notes

<!-- O3-pointer -->
> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log. Do not change anything outside this tool's folder unless the task says so.


Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

**Deliberately different from the deleted "Layer Explorer" tool** (a
comprehensive per-layer reference tool, removed because the owner already
has a separate repo covering that ground). This tool is narrow and
concrete: **one single real scenario** — a browser's plain HTTP GET
request over TCP/IPv4/Ethernet — walked step by step from Physical (1) to
Application (7), showing at each step what header gets revealed, what the
resulting unit is called (the PDU name), and real sample field values.
Not a reference tool; a "watch the data actually change" tool, same spirit
as Subnet Calculator and VLAN Designer.

**Direction is intentional**: the owner asked to go Physical → Application,
which reads naturally as the RECEIVING side's perspective — start with raw
bits and reveal one more header at each step, ending at the plain HTTP
text. Every step's content still describes what that header does when
DATA IS SENT (since that's when it's actually added) — the walkthrough
direction and the "sending" framing of each header's job are deliberately
different things, not a contradiction.

**The core teaching point, called out explicitly at steps 5 and 6**: OSI's
7 layers don't all have a distinct header in a real HTTP/TCP/IP packet.
Session and Presentation add nothing on the wire in this stack — Session's
job is absorbed by TCP staying connected + application-level cookies;
Presentation's job (encryption) would only appear here if this were HTTPS
(TLS). This is presented as an honest structural fact, not smoothed over
by inventing headers that don't exist.

**Every step also correlates directly to Wireshark** (added after the
owner explicitly asked for this, so what's learned here transfers to
reading a real capture): each step's `.ws-block` shows the EXACT protocol
tree label Wireshark uses (e.g. "Internet Protocol Version 4", not just
"IP header"), a field-name mapping where our simplified name differs from
Wireshark's (e.g. our "TTL" → Wireshark's "Time to Live"), and real
display-filter syntax (`ip.addr == ...`, `tcp.flags.push == 1`, etc). Steps
1, 5, and 6 each explicitly note that Wireshark shows **no** entry at all
for Physical/Session/Presentation — the same structural gap the tool's
core teaching point makes, now confirmed against a real, independently-
verifiable tool instead of just this tool's own say-so.

Each step also lists a handful of **other protocols that operate at that
layer** (brief, one line each — e.g. UDP/SCTP alongside TCP at Transport,
ARP/PPP alongside Ethernet at Data Link) via `PROTOCOLS_BY_LAYER`. This is
intentionally NOT a deep-dive per protocol (that approach was tried once
for all 19 Application-layer protocols as part of the deleted Layer
Explorer and scoped back) — just enough context that "what else lives
here" isn't a total blank.

## How it's built

- `server.py` — serves `ui/index.html` and nothing else. Fully static, no
  network calls, no backend logic — same reasoning as Layer Explorer was:
  pure reference/illustrative content.
- `ui/index.html` — single file, no build step.
  - `STEPS` — the 7 layers in order, each with a name, PDU label, and
    identity color (same 7-color palette Layer Explorer used, reused here
    for visual consistency across any layer-related tool).
  - `RENDERERS` — one function per layer (`physical`, `datalink`,
    `network`, `transport`, `session`, `presentation`, `application`),
    each returning that step's full card HTML. `goToStep(n)` swaps the
    visible content and updates the step nav + prev/next button states.
  - `TERM_INFO` — the click-to-explain glossary. **Every entry is used,
    and every reference resolves** — verified with a script before
    shipping (see the commit that introduced this tool for the exact
    check), same convention as every other tool here. Unlike Subnet
    Calculator/DNS Lookup/VLAN Designer, there's no separate "engine"
    section to `node`-test — this tool has no calculation, so the
    verification here is entirely about the glossary integrity and a
    plain syntax check, not numeric correctness.
  - `PROTOCOLS_BY_LAYER` + `protocolListHtml()` — the brief "other
    protocols at this layer" list appended to every step, one source of
    truth per layer key.

## Things that will bite you if you don't know them

- **This tool's scenario is fixed, on purpose** — one example (HTTP GET,
  TCP, IPv4, Ethernet), not user-configurable. If asked to make it
  interactive (choose UDP, choose HTTPS, choose IPv6), that's a genuinely
  new scope decision, not a small tweak — check with the owner before
  doing it, since the tool's whole value right now is depth on one clear
  example rather than breadth across variations.
- **Steps 5 (Session) and 6 (Presentation) are intentionally "empty" of a
  header** — don't "fix" this by inventing a fake header field for
  consistency with the other steps. The absence IS the content at those
  two steps; that's the whole point being made there.
- **The direction (Physical → Application) and the "what gets added"
  framing (a sending-side concept) are deliberately reconciled, not
  accidentally mismatched** — see the note in "What this tool is" above.
  Don't flip the explanation to describe stripping/removing at each step
  just because the navigation order looks like decapsulation; the content
  still correctly describes each header's job from the sending side.
- **The Wireshark `.ws-block` field values must stay in sync with each
  step's own sample table** — both describe the same fixed scenario (same
  MACs, same IPs, same ports, same TTL). If the scenario's sample values
  ever change, update both places; they're currently two independent hand-
  written blocks, not generated from one shared source of field values.
- Mounted at `/tools/packet-journey/` by `main.py` in the repo root — this
  folder never needs to know that; it's a fully self-contained ASGI app
  either way.
