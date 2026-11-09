<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

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
