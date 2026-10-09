# Toolbox

A Dockerized, single-container website that bundles multiple internal tools
behind one home page. Each tool is self-contained and mounted in-process
(no reverse proxy, no per-tool container) — see `CLAUDE.md` for the
architecture and how to add a new tool.

---

## Quick Start

```bash
# 1. Clone the repo, then enter the project directory
cd toolbox

# 2. Build and start (builds the one image containing every tool)
docker-compose up --build -d

# 3. Open the home page
http://localhost:8000
```

Each tool is also reachable directly at `http://localhost:8000/tools/<name>/`.

To stop:
```bash
docker-compose down
```

---

## Tools

| | Tool | What it does |
|---|---|---|
| 🔍 | **DataDiff Pro** (`datadiff-pro`) | Deep smart diff for JSON, XML & CSV — nested objects, list keys, equivalence rules |
| 🔐 | **Encode/Decode** (`encode-decode`) | Base64, URL, Hex, HTML entities, Gzip, AES, RSA, JWT, hashing — all client-side |
| 🧮 | **Subnet Calculator** (`subnet-calc`) | Interactive IPv4 subnetting with binary bit visualization and worked explanations |
| 🌐 | **DNS Lookup** (`dns-lookup`) | Live DNS records for any domain — 14 record types, plain-language explanations |
| 🧩 | **VLAN Designer** (`vlan-designer`) | Design VLANs, switch ports, and inter-VLAN routing |
| 📦 | **Packet Journey** (`packet-journey`) | One real HTTP request, traced layer by layer |
| ⌨️ | **cURL Builder** (`curl-builder`) | Build complex curl commands from a form — copy-pasteable for bash, cmd.exe, PowerShell |
| 📖 | **HTTP Header Reference** (`header-reference`) | Browsable glossary of ~90 widely-used HTTP headers |
| 🧭 | **HTTP Methods & Status Codes** (`http-methods-status`) | Every HTTP method and status code with real examples and an architect's decision guide |
| 🍪 | **Cookie Lab** (`cookie-lab`) | Live `document.cookie` playground plus full theory |
| 🐼 | **DataFrame Studio** (`df-studio`) | Click-driven pandas — load, transform, export, save reusable templates |
| 🗄️ | **SQL Studio** (`sql-studio`) | Paste, edit, pretty-print Postgres SQL — 125+ templates, live run, `show`-style commands |
| 🗺️ | **Schema Map** (`schema-map`) | Explore a Postgres database's tables and foreign-key structure as a graph |

`category: tool` entries (practical, act on real data) show on the home page
by default; `category: learn` entries (educational/reference) are shown via
the "Show learning tools" toggle. See `registry.yaml`.

---

## Project Structure

```
toolbox/
├── core/                  DataDiff Pro's diff engine (normalizer, equivalence, mapper, list_resolver, diff_engine)
├── api/                   DataDiff Pro's FastAPI app
├── ui/                    DataDiff Pro's frontend
├── encode-decode/         each tool below follows the same shape:
├── subnet-calc/           its own package (server.py / engine code + ui/),
├── dns-lookup/            plus its own CLAUDE.md
├── vlan-designer/
├── packet-journey/
├── curl-builder/
├── header-reference/
├── http-methods-status/
├── cookie-lab/
├── df-studio/
├── sql-studio/
├── schema-map/
├── environments/          DataDiff Pro's example YAML config
├── notebook/
├── main.py                 THE entrypoint — home page + mounts every tool
├── registry.yaml            home-page card metadata (display only)
├── theme-tokens.css          canonical color palette — copy-source only
├── KNOWLEDGE_MAP.md           symptom → file lookup table, per tool
├── CLAUDE.md                  architecture, conventions, how to add a tool
├── Dockerfile                builds the one image (copies every tool)
├── docker-compose.yml        one service, host port 8000
└── requirements.txt           shared dependency set for the whole image
```

---

## DataDiff Pro — detailed usage

DataDiff Pro (tool #1, and the one this repo started as) compares JSON, XML,
and CSV side by side. Paste two documents, click **Compare**, and instantly
see every match, mismatch, equivalent value, and extra field — including
inside deeply nested objects and lists. Both sides can be **different
formats** — compare a JSON API response against an XML export or a CSV file
from the same dataset.

### Basic compare

1. Paste your left-side data into the **Left Input** panel
2. Paste your right-side data into the **Right Input** panel
3. Select the correct format (JSON / XML / CSV) from the dropdown for each side
4. Click **Compare**

The results appear below with:
- A **summary bar** showing counts per status
- A **table** of every field with its status colour-coded and left / right values side by side

### Status colours

| Colour | Status | Meaning |
|--------|--------|---------|
| grey text | MATCH | Values are identical |
| blue row | EQUIVALENT | Different values, but covered by an equivalence rule |
| red row | MISMATCH | Genuinely different values |
| yellow row | EXTRA LEFT | Field/item exists only on the left side |
| yellow row | EXTRA RIGHT | Field/item exists only on the right side |

### Filtering results

- Use the checkboxes above the table to show/hide each status category
- **Hide Matches** is on by default so you only see differences
- Type in the **Filter by path** box to instantly narrow rows by field path

### Export

Click **Export JSON** to download the full diff result as a `.json` file.

### Field Mapper (optional)

Use this when the same data has different field names on each side.
Expand the **Field Mapper** panel and paste one mapping per line:

```
source_path,target_path
```

Examples:
```
banks,BankData
nominee.nomineeName,nominee.name
user.address.city,person.location.city
```

- Uses dot notation for nested fields
- Applied to the **left** side before diffing
- Lines starting with `#` are treated as comments and ignored
- Leave blank if both sides already use the same field names — mapping is optional

### Environment / Rules (optional)

Expand the **Environment / Rules** panel and paste a YAML config.
See `environments/example.yaml` for the full annotated reference.

**Equivalence rules** — group values that should count as equal:

```yaml
equivalence_rules:
  - [pending, not_started, queued]
  - [USD, usd, "US Dollar"]
  - ["0001-01-01", "1900-01-01", "N/A", ""]
```

Built-in rules (always active):
- `null / none / na / n/a / nil / undefined / ""` are all equivalent
- `true / 1 / yes / y / on` are equivalent
- `false / 0 / no / n / off` are equivalent
- Numbers represented as strings are equivalent to their numeric form (`"1.0"` = `1`)

**List keys** — tell the engine how to pair items in a list of objects:

```yaml
list_keys:
  nominees: [nomineeName, relationship]   # composite key (two fields)
  accounts: [accountId]                   # single key
  products: [sku]
```

If no key is specified, the engine auto-detects one by looking for fields
whose values are unique across the list (tries `id`, `key`, `code`, `name`,
suffix matches like `*_id`, then pairs of candidates). Falls back to
index-based pairing if nothing unique is found. The strategy used is shown
in the results panel.

### Supported Input Formats

| Format | Notes |
|--------|-------|
| **JSON** | Any valid JSON — object `{}` or array `[]` |
| **XML** | Single root element; attributes are automatically normalized to plain fields; `xsi:nil="true"` becomes null; mixed-content elements (text + attributes) are correctly hoisted |
| **CSV** | First row is the header; delimiter is auto-detected (comma, tab, semicolon, pipe); JSON-encoded columns (arrays/objects stored as strings) are automatically parsed back to their native types |

### XML Attribute Handling

| XML | Parsed as |
|-----|-----------|
| `<address type="home">` | `{"type": "home", ...}` |
| `<amount currency="INR">2599.75</amount>` | `{"amount": 2599.75, "currency": "INR"}` |
| `<last_login xsi:nil="true"/>` | `null` |

Namespace declarations (`xmlns:*`) are silently ignored. Unknown namespace
prefixes (e.g. `xsi:`) are auto-declared so the parser never fails on
real-world XML.

### CSV Complex Columns

| CSV cell value | Parsed as |
|----------------|-----------|
| `["Python","SQL"]` | Python list |
| `{"city":"Ahmedabad"}` | Python dict |
| `true` / `false` | Boolean |
| `42` / `3.14` | Number |
| `null` / `""` | None |

This means a JSON array field and its CSV export will compare as **MATCH**
rather than MISMATCH.

### API Reference

### `POST /tools/datadiff-pro/compare`

**Request body (JSON):**

```json
{
  "left_data":        "<raw text>",
  "right_data":       "<raw text>",
  "left_format":      "json | xml | csv",
  "right_format":     "json | xml | csv",
  "mapper_csv":       "<optional mapping lines>",
  "environment_yaml": "<optional YAML config>"
}
```

**Success response:**

```json
{
  "ok": true,
  "summary": {
    "MATCH": 5,
    "MISMATCH": 2,
    "EQUIVALENT": 1,
    "EXTRA_LEFT": 0,
    "EXTRA_RIGHT": 1
  },
  "records": [
    {
      "path":        "nominees[nomineeName=John,relationship=Son].percent",
      "left_value":  50,
      "right_value": 60,
      "status":      "MISMATCH"
    }
  ],
  "list_strategies": [
    "List 'nominees': environment key (nomineeName, relationship)"
  ],
  "meta": {
    "left_format":         "json",
    "right_format":        "xml",
    "mapping_applied":     true,
    "environment_applied": true
  }
}
```

**Error response:**

```json
{
  "ok": false,
  "error": "Left side — JSON parse error on line 4, column 12: Expecting ',' delimiter.\n  Near: '\"score\": 95'\nHint: Check for missing commas..."
}
```

For the other tools' APIs (if any), see each tool's own `CLAUDE.md`.

---

## Development (without Docker)

```bash
# Install dependencies
pip install -r requirements.txt

# Run the whole Toolbox from the repo root
PYTHONPATH=. uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

`--reload` watches for file changes and restarts automatically — useful when
editing any tool's backend. For frontend changes, just refresh the browser.

---

## Requirements

- Docker 20.10+ and docker-compose 1.29+ (or Docker Desktop)
- No other dependencies — everything runs inside the container

---

## Built with Claude

This project was designed and built entirely with
[Claude](https://claude.ai) (Anthropic's AI) using
[Claude Code](https://claude.ai/claude-code) — including the architecture,
every tool's backend and frontend, and the Docker setup.
