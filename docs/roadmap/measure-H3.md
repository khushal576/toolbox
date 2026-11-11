# Roadmap H3 — what does the start of an AI question cost as tools grow? (2026-11-11)

Question (ADR-AI-HELPER D5/D6): with 1,000 tools, is the AI helper token hungry? Method: `python3 tools/bench/ai_registry_tokens.py` builds N fake tools
(3 read actions each) and measures what the AI is shown for the **registry design** (what was built: 14 MCP tools + a bounded `toolbox_guide`, then `find_actions` /
`describe_action` on demand) against the **naive design** (one MCP tool per action, all listed up front). **Token counts are estimates (characters / 4).**

| Tools | Actions | **Registry**: shown up front | + one search | + one describe | **Naive** (a tool per action): shown up front | First search | Later searches |
|---|---|---|---|---|---|---|---|
| 25 | 86 | **~5,766** tokens | ~227 | ~133 | ~9,627 tokens | 0.12 s | 1.2 ms |
| 100 | 311 | **~5,962** tokens | ~227 | ~133 | ~25,152 tokens | 0.38 s | 2.4 ms |
| 300 | 911 | **~5,972** tokens | ~227 | ~133 | ~66,702 tokens | 0.91 s | 5.0 ms |
| 1,000 | 3,011 | **~5,972** tokens | ~228 | ~133 | ~212,127 tokens | 2.99 s | 18.7 ms |

## Reading it
- **The registry's start-of-question cost is flat:** ~5,800 tokens with 25 tools, ~6,000 with 1,000 (the 14 MCP tool descriptions, ~4,500, dominate; `toolbox_guide` is capped at 40
  tool names). The naive design grows with every tool and passes **210,000 tokens** at 1,000 tools — more than a context window holds.
- **One search ≈ 230 tokens, one describe ≈ 130** at every size (a search returns the best 5, never the list).
- **Speed:** the first search in a fresh process builds the index (read + validate every manifest): 0.12 s for 25 tools, **3 s for 1,000**; later searches are 1–19 ms (word sets are computed once).
  Each MCP session is one process, so the 3 s is paid once per session at 1,000 tools; with today's ~25 tools it is 0.12 s.
- **Target of the ADR met:** "about the same with 25 or 1,000 tools". Claude Code also caches the unchanging start of a request, so repeated questions cost less than the table says.

## Not measured / caveats
- Estimates, not the tokenizer's exact counts (no API key is used by design). Treat them as ±20 %.
- The fake tools are small; real manifests with longer summaries make each search result a little larger (summaries are capped at 200 characters, searches at 10 results).
- The 14 MCP tool descriptions (~4,500 tokens) are now the largest fixed part. If it ever matters, the older read-only tools can be hidden from `tools/list` and reached only through the registry
  (their `mcp.<name>` ids already work) — not done in H3 because it would change what existing clients see.
