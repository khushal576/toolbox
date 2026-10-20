"""
data-dumper/toc.py

Understands a custom-format dump's TABLE OF CONTENTS (`pg_restore --list`) so a
restore can be SELECTIVE — pure functions, no database and no subprocess, so it is
easy to test.

Why this exists instead of just `pg_restore -n schema -t table` (measured, not
assumed): `-t` restores the bare table + its data + its comment, but NOT its
indexes, constraints, triggers, policies or sequences; `-n` restores the objects in a
schema but NOT the CREATE SCHEMA itself. Neither pulls in anything the objects depend
on. So for schema / table / object selections this module builds a `pg_restore -L`
LIST FILE — the exact entries to restore — from the TOC, and works out which
index/sequence/partition/foreign key belongs to which table by reading the SQL that
`pg_restore -f -` would emit for the pre-data and post-data sections (the TOC line of
an INDEX names only the index, not its table).

A TOC line looks like:   `3623; 2606 17219 CONSTRAINT app customers customers_pkey postgres`
                         `3798; 0 17208 TABLE DATA app customers postgres`
i.e. `ID; catalogOid objectOid TYPE schema name... owner` (schema is `-` when the
object has none). Only the ID matters to pg_restore -L; the rest is for people.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Optional

# Every TOC `desc` pg_dump emits, longest-first so "TABLE DATA" beats "TABLE".
_TYPES = sorted([
    "ACL", "AGGREGATE", "BLOB", "BLOBS", "CAST", "COLLATION", "COMMENT", "CONSTRAINT", "CONVERSION", "DATABASE",
    "DEFAULT", "DEFAULT ACL", "DOMAIN", "EVENT TRIGGER", "EXTENSION", "FK CONSTRAINT", "FOREIGN DATA WRAPPER",
    "FOREIGN TABLE", "FUNCTION", "INDEX", "INDEX ATTACH", "LARGE OBJECT", "MATERIALIZED VIEW",
    "MATERIALIZED VIEW DATA", "OPERATOR", "OPERATOR CLASS", "OPERATOR FAMILY", "POLICY", "PROCEDURAL LANGUAGE",
    "PROCEDURE", "PUBLICATION", "PUBLICATION TABLE", "PUBLICATION TABLES IN SCHEMA", "ROW SECURITY", "RULE",
    "SCHEMA", "SECURITY LABEL", "SEQUENCE", "SEQUENCE OWNED BY", "SEQUENCE SET", "SERVER", "SHELL TYPE",
    "STATISTICS", "SUBSCRIPTION", "TABLE", "TABLE ATTACH", "TABLE DATA", "TEXT SEARCH CONFIGURATION",
    "TEXT SEARCH DICTIONARY", "TEXT SEARCH PARSER", "TEXT SEARCH TEMPLATE", "TRANSFORM", "TRIGGER", "TYPE",
    "USER MAPPING", "VIEW", "CHECK CONSTRAINT", "EXTENDED STATISTICS", "PROPERTY GRAPH", "REFRESH MATERIALIZED VIEW",
], key=len, reverse=True)

_LINE = re.compile(r"^(\d+); (\d+) (\d+) (.*)$")

DATA_TYPES = {"TABLE DATA", "SEQUENCE SET", "MATERIALIZED VIEW DATA", "BLOBS", "BLOB", "LARGE OBJECT"}
RELATION_TYPES = {"TABLE", "VIEW", "MATERIALIZED VIEW", "FOREIGN TABLE", "SEQUENCE"}
# entries that live ON a table and carry (schema, table, objectname)
_ON_TABLE = {"CONSTRAINT", "FK CONSTRAINT", "TRIGGER", "POLICY", "RULE", "DEFAULT", "ROW SECURITY", "CHECK CONSTRAINT"}
# objects a table can depend on that are not tables: restored alongside when "shared objects" is on
_SHARED = {
    "TYPE", "DOMAIN", "FUNCTION", "PROCEDURE", "AGGREGATE", "COLLATION", "OPERATOR", "OPERATOR CLASS",
    "OPERATOR FAMILY", "TEXT SEARCH CONFIGURATION", "TEXT SEARCH DICTIONARY", "TEXT SEARCH PARSER",
    "TEXT SEARCH TEMPLATE", "CAST", "CONVERSION", "SHELL TYPE",
}

_IDENT = r'(?:"(?:[^"]|"")+"|[A-Za-z_\u0080-￿][\w$\u0080-￿]*)'
_QNAME = rf"({_IDENT})\.({_IDENT})"


def _unq(s: str) -> str:
    return s[1:-1].replace('""', '"') if s.startswith('"') else s


def parse_toc(text: str) -> list[dict[str, Any]]:
    """Every real entry of `pg_restore --list` output, in archive order. Entry keys: id, type,
    schema (None if the object has none), name (display text), raw (the original line — what a
    -L list file needs), plus `tag` (the tokens after the schema, owner removed)."""
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line or line.startswith(";"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        rest = m.group(4)
        has_owner = not rest.endswith(" ")  # objects without an owner (extensions) end the line with a space
        typ = next((t for t in _TYPES if rest == t or rest.startswith(t + " ")), None)
        if typ is None:
            typ, after = "OTHER", rest
        else:
            after = rest[len(typ):].strip()
        parts = after.split(" ")
        schema: Optional[str] = None
        if parts and parts[0] == "-":
            parts = parts[1:]
        elif typ != "EXTENSION" and parts:
            schema, parts = parts[0], parts[1:]
        if has_owner and len(parts) > 1:  # the last token is the owner
            parts = parts[:-1]
        tag = " ".join(parts)
        entries.append({"id": int(m.group(1)), "type": typ, "schema": schema, "tag": tag, "name": tag, "raw": line})
    return entries


# ----------------------------------------------------------------- relations from the SQL

def parse_relations(pre_sql: str, post_sql: str) -> dict[str, Any]:
    """Which index / sequence / partition / foreign key belongs to which table — read from the
    SQL `pg_restore -f -` emits for --section=pre-data and --section=post-data. All keys are
    (schema, name) tuples of UNQUOTED names."""
    index_table: dict[tuple[str, str], tuple[str, str]] = {}
    for m in re.finditer(rf"CREATE (?:UNIQUE )?INDEX ({_IDENT}) ON (?:ONLY )?{_QNAME}", post_sql):
        # the index lives in its table's schema (pg_dump never emits an index in another one)
        index_table[(_unq(m.group(2)), _unq(m.group(1)))] = (_unq(m.group(2)), _unq(m.group(3)))
    seq_table: dict[tuple[str, str], tuple[str, str]] = {}
    for m in re.finditer(rf"ALTER SEQUENCE {_QNAME} OWNED BY {_QNAME}\.{_IDENT}", pre_sql + post_sql):
        seq_table[(_unq(m.group(1)), _unq(m.group(2)))] = (_unq(m.group(3)), _unq(m.group(4)))
    for m in re.finditer(
        rf"ALTER TABLE (?:ONLY )?{_QNAME}\s+ALTER COLUMN {_IDENT} ADD GENERATED [A-Z ]+ AS IDENTITY \(\s*SEQUENCE NAME {_QNAME}",
        pre_sql + post_sql, re.S,
    ):
        seq_table[(_unq(m.group(3)), _unq(m.group(4)))] = (_unq(m.group(1)), _unq(m.group(2)))
    for m in re.finditer(
        rf"ALTER TABLE (?:ONLY )?{_QNAME} ALTER COLUMN {_IDENT} SET DEFAULT nextval\('{_QNAME}'::regclass\)", pre_sql + post_sql
    ):
        seq_table.setdefault((_unq(m.group(3)), _unq(m.group(4))), (_unq(m.group(1)), _unq(m.group(2))))
    partitions: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for m in re.finditer(rf"ALTER TABLE (?:ONLY )?{_QNAME} ATTACH PARTITION {_QNAME}", pre_sql + post_sql):
        partitions[(_unq(m.group(1)), _unq(m.group(2)))].append((_unq(m.group(3)), _unq(m.group(4))))
    fks: dict[tuple[str, str, str], tuple[str, str]] = {}
    for m in re.finditer(
        rf"ALTER TABLE (?:ONLY )?{_QNAME}\s+ADD CONSTRAINT ({_IDENT}) FOREIGN KEY \([^)]*\) REFERENCES {_QNAME}", post_sql, re.S
    ):
        fks[(_unq(m.group(1)), _unq(m.group(2)), _unq(m.group(3)))] = (_unq(m.group(4)), _unq(m.group(5)))
    return {"index_table": index_table, "seq_table": seq_table, "partitions": dict(partitions), "fks": fks}


class Toc:
    """A parsed dump: entries + the relations between them."""

    def __init__(self, entries: list[dict[str, Any]], relations: dict[str, Any]):
        self.entries = entries
        self.rel = relations
        self.by_id = {e["id"]: e for e in entries}

    # ---- which table does an entry belong to? -> (schema, table) or None
    def owner_table(self, e: dict[str, Any]) -> Optional[tuple[str, str]]:
        t, s, tag = e["type"], e["schema"], e["tag"]
        first = tag.split(" ")[0] if tag else ""
        if s is None:
            return None
        if t in ("TABLE", "TABLE DATA", "TABLE ATTACH", "FOREIGN TABLE", "VIEW", "MATERIALIZED VIEW", "MATERIALIZED VIEW DATA"):
            return (s, tag)
        if t in _ON_TABLE:
            return (s, first)
        if t in ("INDEX", "INDEX ATTACH"):
            return self.rel["index_table"].get((s, tag))
        if t in ("SEQUENCE", "SEQUENCE OWNED BY", "SEQUENCE SET"):
            return self.rel["seq_table"].get((s, tag))
        if t == "COMMENT":
            # tag is "<OBJTYPE> <name>" e.g. "TABLE customers" / "COLUMN customers.email"
            objtype, _, name = tag.partition(" ")
            if objtype in ("TABLE", "VIEW", "MATERIALIZED VIEW", "FOREIGN TABLE"):
                return (s, name)
            if objtype == "COLUMN":
                return (s, name.split(".")[0])
        return None

    # ---- what the UI shows
    def summary(self) -> dict[str, Any]:
        schemas: dict[str, Counter] = defaultdict(Counter)
        rels: dict[tuple[str, str], dict[str, Any]] = {}
        for e in self.entries:
            if e["schema"]:
                schemas[e["schema"]][e["type"]] += 1
            if e["type"] in ("SCHEMA",):
                schemas.setdefault(e["tag"], Counter())
            if e["type"] in ("TABLE", "VIEW", "MATERIALIZED VIEW", "FOREIGN TABLE") and e["schema"]:
                rels[(e["schema"], e["tag"])] = {
                    "schema": e["schema"], "name": e["tag"], "kind": e["type"].lower().replace("materialized view", "matview"),
                    "has_data": False, "indexes": 0, "constraints": 0, "triggers": 0, "partition_of": None,
                }
        for parent, kids in self.rel["partitions"].items():
            for k in kids:
                if k in rels:
                    rels[k]["partition_of"] = f"{parent[0]}.{parent[1]}"
        for e in self.entries:
            o = self.owner_table(e)
            if o not in rels:
                continue
            r = rels[o]
            if e["type"] in ("TABLE DATA", "MATERIALIZED VIEW DATA"):
                r["has_data"] = True
            elif e["type"] in ("INDEX",):
                r["indexes"] += 1
            elif e["type"] in ("CONSTRAINT", "FK CONSTRAINT"):
                r["constraints"] += 1
            elif e["type"] == "TRIGGER":
                r["triggers"] += 1
        return {
            "schemas": [{"name": n, "counts": dict(c)} for n, c in sorted(schemas.items())],
            "relations": sorted(rels.values(), key=lambda r: (r["schema"], r["name"])),
            "types": dict(Counter(e["type"] for e in self.entries)),
            "has_data": any(e["type"] in DATA_TYPES for e in self.entries),
            "entry_count": len(self.entries),
            "extensions": [e["tag"] for e in self.entries if e["type"] == "EXTENSION"],
        }

    # ---- selections -> the list of TOC ids to restore
    def select(self, sel: dict[str, Any]) -> list[int]:
        """sel = {mode: 'schemas'|'tables'|'objects', schemas: [...], tables: ['schema.name',...],
        object_ids: [...], structure: bool, data: bool, shared: bool, foreign_keys: bool}.
        `structure`/`data` choose whether definitions, rows, or both are restored. `shared`
        (default on) also restores what the selection needs to exist: extensions, the schemas
        themselves, and the types/domains/functions of the involved schemas. Returns TOC ids in
        archive order (= a valid restore order)."""
        mode = sel.get("mode")
        structure, data = sel.get("structure", True), sel.get("data", True)
        shared = sel.get("shared", True)
        chosen: set[int] = set()

        if mode == "objects":
            chosen = {i for i in sel.get("object_ids", []) if i in self.by_id}
        elif mode == "schemas":
            wanted = set(sel.get("schemas", []))
            for e in self.entries:
                t, s = e["type"], e["schema"]
                if s in wanted:
                    chosen.add(e["id"])
                elif t == "SCHEMA" and e["tag"] in wanted:
                    chosen.add(e["id"])
                elif t == "COMMENT" and s is None and e["tag"].startswith("SCHEMA ") and e["tag"].split(" ", 1)[1] in wanted:
                    chosen.add(e["id"])
            involved = wanted
        elif mode == "tables":
            wanted_tables = {tuple(t.split(".", 1)) for t in sel.get("tables", []) if "." in t}
            # a partitioned parent brings its partitions
            stack = list(wanted_tables)
            while stack:
                for kid in self.rel["partitions"].get(stack.pop(), []):
                    if kid not in wanted_tables:
                        wanted_tables.add(kid)
                        stack.append(kid)
            for e in self.entries:
                o = self.owner_table(e)
                if o is None or o not in wanted_tables:
                    continue
                if e["type"] == "FK CONSTRAINT":
                    ref = self.rel["fks"].get((e["schema"], e["tag"].split(" ")[0], e["tag"].split(" ", 1)[1] if " " in e["tag"] else ""))
                    # include a foreign key only when the table it points at is restored too
                    if not sel.get("foreign_keys", True) or ref is None or ref not in wanted_tables:
                        continue
                if e["type"] == "TABLE ATTACH":
                    # attach only if the PARENT is also selected
                    parents = [p for p, kids in self.rel["partitions"].items() if o in kids]
                    if not any(p in wanted_tables for p in parents):
                        continue
                chosen.add(e["id"])
            involved = {s for s, _ in wanted_tables}
        else:
            raise ValueError(f"unknown selection mode {mode!r}")

        if mode != "objects" and shared:
            for e in self.entries:
                t, s = e["type"], e["schema"]
                if t == "EXTENSION" or (t == "COMMENT" and s is None and e["tag"].startswith("EXTENSION ")):
                    chosen.add(e["id"])
                elif t == "SCHEMA" and e["tag"] in involved:
                    chosen.add(e["id"])
                elif t in _SHARED and s in involved:
                    chosen.add(e["id"])

        out = []
        for e in self.entries:
            if e["id"] not in chosen:
                continue
            is_data = e["type"] in DATA_TYPES
            if is_data and not data:
                continue
            if not is_data and not structure and mode != "objects":
                continue  # data only: no CREATE SCHEMA / EXTENSION / TABLE — the structure must already be there
            out.append(e["id"])
        return out

    # ---- "replace existing": the statements that clear the way
    @staticmethod
    def _qi(name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    def schema_wipe_sql(self, schemas: list[str]) -> str:
        """DROP SCHEMA … CASCADE for each schema (everything inside goes — including objects that are
        NOT in this dump), recreating the ones the dump does not create itself (e.g. `public`)."""
        created = {e["tag"] for e in self.entries if e["type"] == "SCHEMA"}
        out = []
        for s in schemas:
            out.append(f"DROP SCHEMA IF EXISTS {self._qi(s)} CASCADE;")
            if s not in created:
                out.append(f"CREATE SCHEMA {self._qi(s)};")
        return "\n".join(out) + "\n" if out else ""

    def object_drop_sql(self, ids: list[int]) -> str:
        """Per-object DROP … IF EXISTS … CASCADE for the chosen entries, dependents first. Things that
        disappear with their table (its indexes, constraints, triggers, owned sequences) are not
        dropped separately — dropping them separately is exactly what breaks on partitions."""
        chosen = [self.by_id[i] for i in ids if i in self.by_id]
        tables = {(e["schema"], e["tag"]) for e in chosen if e["type"] in ("TABLE", "FOREIGN TABLE", "VIEW", "MATERIALIZED VIEW")}
        q = self._qi
        out = []
        for e in reversed(chosen):
            t, s, tag = e["type"], e["schema"], e["tag"]
            if s is None:
                continue
            owner = self.owner_table(e)
            if t in ("TABLE", "FOREIGN TABLE", "VIEW", "MATERIALIZED VIEW"):
                out.append(f"DROP {t} IF EXISTS {q(s)}.{q(tag)} CASCADE;")
            elif t == "SEQUENCE":
                if owner is None or owner not in tables:
                    out.append(f"DROP SEQUENCE IF EXISTS {q(s)}.{q(tag)} CASCADE;")
            elif t in ("FUNCTION", "PROCEDURE", "AGGREGATE"):
                name, _, args = tag.partition("(")
                out.append(f"DROP {t} IF EXISTS {q(s)}.{q(name)}({args} CASCADE;")
            elif t in ("TYPE", "DOMAIN"):
                out.append(f"DROP {t} IF EXISTS {q(s)}.{q(tag)} CASCADE;")
            elif owner is not None and owner in tables:
                continue
            elif t == "INDEX":
                out.append(f"DROP INDEX IF EXISTS {q(s)}.{q(tag)};")
            elif t in ("CONSTRAINT", "FK CONSTRAINT") and " " in tag:
                tbl, _, con = tag.partition(" ")
                out.append(f"ALTER TABLE IF EXISTS {q(s)}.{q(tbl)} DROP CONSTRAINT IF EXISTS {q(con)};")
            elif t == "TRIGGER" and " " in tag:
                tbl, _, trg = tag.partition(" ")
                out.append(f"DROP TRIGGER IF EXISTS {q(trg)} ON {q(s)}.{q(tbl)};")
            elif t == "POLICY" and " " in tag:
                tbl, _, pol = tag.partition(" ")
                out.append(f"DROP POLICY IF EXISTS {q(pol)} ON {q(s)}.{q(tbl)};")
            elif t == "RULE" and " " in tag:
                tbl, _, rule = tag.partition(" ")
                out.append(f"DROP RULE IF EXISTS {q(rule)} ON {q(s)}.{q(tbl)};")
        return "\n".join(out) + "\n" if out else ""

    def list_file(self, ids: list[int]) -> str:
        """The text of a `pg_restore -L` list file: just the chosen lines."""
        return "\n".join(self.by_id[i]["raw"] for i in ids if i in self.by_id) + "\n"

    def preview(self, ids: list[int]) -> dict[str, Any]:
        c = Counter(self.by_id[i]["type"] for i in ids if i in self.by_id)
        return {"entries": len(ids), "by_type": dict(c.most_common())}
