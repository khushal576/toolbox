# VLAN Designer — tool-local notes

<!-- O3-pointer -->
> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log. Do not change anything outside this tool's folder unless the task says so.


Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

A hands-on VLAN/switch/router designer, deliberately built as one connected
scenario rather than a reference/glossary tool (that approach was tried as
a separate "Layer Explorer" tool and removed — the owner wanted practical
design tools, not more reading material). You plan VLANs, see the switch
ports and trunk that result, see the router's inter-VLAN routing config
generated from that plan, then check whether two specific devices can
actually reach each other — with the real mechanism shown, not just yes/no.

**Multi-phase build** (own idea from the owner, followed the same way
Subnet Calculator and DNS Lookup were staged):
- Phase 1: VLAN planning, access/trunk ports, router-on-a-stick inter-VLAN
  routing, reachability checker. **Built.**
- Phase 2: STP (why redundant switch links need loop prevention) and ACLs
  (policy blocking reachability even when a route exists). **Built** — ACLs
  extend the existing reachability checker rather than becoming a separate
  tab; STP is its own tab (tab 5) since it's a genuinely separate scenario
  (a fixed illustrative 2-switch topology, not tied to the VLAN plan).
- Phase 3 (next): DHCP relay per VLAN, ARP/default-gateway mechanics.
- Later, optional: NAT, native VLAN mismatches, port security, voice VLANs.

## How it's built

- `server.py` — serves `ui/index.html` and nothing else. Fully client-side,
  same reasoning as Subnet Calculator: pure arithmetic/logic, no secrets,
  kept client-side for consistency and instant feedback.
- `ui/index.html` — single file, no build step, two-part `<script>` split:
  1. **`CALCULATION ENGINE`** — pure functions, zero DOM access. The IP-math
     functions (`parseIp`, `cidrToMaskOctets`, `hostInfo`, etc.) are
     **intentionally duplicated from Subnet Calculator**, not shared — see
     the root `CLAUDE.md` rule that tools never import each other's code.
     `planVlans()` is the VLAN-specific piece: same largest-first
     allocation algorithm as Subnet Calculator's `planVlsm()`, plus a
     computed `gateway` (first usable address) per VLAN. Verified with
     `node -e` before any UI touched it, same convention as every other
     tool here.
  2. **`UI WIRING`** — five tabs. Tabs 1-4 are driven by one shared piece
     of state: `VLAN_PLAN` (the result of tab 1's `planVlans()` call, or
     `null`). Tabs 2-4 all check `VLAN_PLAN` first and show a "plan your
     VLANs in tab 1 first" message if it's null — they have no independent
     state of their own, they're views over tab 1's result. **Tab 5 (STP)
     is the one exception** — it's a fixed illustrative 2-switch topology
     unrelated to the VLAN plan, so it doesn't go through `VLAN_PLAN` or
     `refreshDependentTabs()` at all; it has its own `runStp()` call.

## The five tabs

- **VLAN Planner** — base network + VLAN rows (name, ID, host count) →
  a subnet + gateway IP per VLAN. VLAN ID is deliberately kept independent
  of subnet assignment in the data model (`{id, name, hosts}` in, `{id,
  network, gateway, ...}` out) — they're unrelated concepts assigned
  together only by convention, and the UI says so explicitly.
- **Switch Ports** — assign devices to access ports (one VLAN each), see
  the automatic trunk port carrying all VLANs, and the 802.1Q frame tag
  that makes trunking possible.
- **Inter-VLAN Routing** — router-on-a-stick: one sub-interface per VLAN
  on a single physical link, using each VLAN's gateway IP from tab 1.
  Includes generated Cisco-style CLI config (structurally accurate, not
  claimed to be copy-paste-ready for a real device) and a short contrast
  with an L3 switch/SVI alternative.
- **Reachability Checker** — pick two VLANs, get either "same VLAN, pure
  Layer 2, switch handles it" or the full hop-by-hop path through the
  trunk and router sub-interfaces for the cross-VLAN case. Now also
  factors in the ACL rules card on the same tab: a route existing doesn't
  mean the router allows the traffic — `checkAcl()` is evaluated after
  the routing check, and a matching `deny` rule produces a distinct
  "blocked by policy" verdict with its own explanation, not just a
  generic failure.
- **Redundancy (STP)** — a fixed 2-switch, 2-link topology (not tied to
  the VLAN plan at all) where you set each switch's bridge priority and
  see the computed root bridge and each port's role (Designated / Root
  Port / Blocking), via `computeStp()`.

## Things that will bite you if you don't know them

- **`planVlans()` sorts largest-first internally, then re-sorts to input
  order for display** — identical reasoning to Subnet Calculator's
  `planVlsm()`. Don't "simplify" this into displaying allocation order;
  users shouldn't have to think about which order VLANs were allocated in.
- **VLAN ID uniqueness is validated in the UI layer (`runVlanPlan`), not
  the engine** — `planVlans()` itself doesn't check for duplicate IDs, the
  caller does, before ever calling it. If you add a way to construct VLANs
  outside that one code path, you need to re-add the duplicate check there.
- **Tabs 2-4 have no state of their own** — they're pure functions of
  `VLAN_PLAN` (`renderPortsTab()`, `renderRouterTab()`, `renderReachTab()`,
  all called from `refreshDependentTabs()` whenever tab 1 recalculates).
  Adding per-tab state (e.g. remembering port assignments across a VLAN
  plan change) would need deliberate design, not just a new variable.
- **Every inline `showInfoPopover(this, 'key')` reference was checked
  against `TERM_INFO` with a script before shipping** (a dangling
  reference was an actual bug caught this way in a previous tool). Run the
  same check after adding new inline term references — see the commit
  that introduced this tool for the exact one-liner.
- **`checkAcl()` deliberately does NOT implement a real router's implicit
  "deny everything else" once any ACL exists** — only explicit rules the
  user adds have any effect; no rule matching means permit, always. This
  is a documented, intentional simplification (see the hint text on the
  ACL card) to teach "policy can override routing" without also requiring
  the separate, more confusing implicit-deny-all concept. Don't "fix" this
  to match real Cisco behavior without discussing it — it would silently
  block traffic the UI never told the user to expect blocked.
- **`computeStp()` only handles the ONE fixed topology this tool models**
  (exactly two switches, exactly two direct parallel links) — it is not a
  general spanning-tree algorithm. If STP ever needs to support a
  user-editable topology, this function gets replaced, not extended.
- **STP's tab (tab 5) intentionally has no connection to `VLAN_PLAN`** —
  don't wire it into `refreshDependentTabs()`; that would imply a
  relationship between the illustrative STP topology and the VLAN plan
  that doesn't exist and was never designed to exist.
- Mounted at `/tools/vlan-designer/` by `main.py` in the repo root — this
  folder never needs to know that; it's a fully self-contained ASGI app
  either way.
