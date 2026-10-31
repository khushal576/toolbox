"""
data-lake/colmap.py — the COLUMN MAP of a load (roadmap L7): keep only some columns, rename them, cast types, fill
empty values and PROTECT sensitive columns (mask / hash / redact / empty / shuffle) while a file becomes a table.

`compile_select(source_sql, available, columns, only_listed)` turns the map into ONE DuckDB SELECT that sits on top of
the reader (`source_sql`) — the loader COPYs it to Parquet, so nothing is ever held in Python memory. Order of work per
column:  cast → fill empty values → protect.

  columns = [{"source": "cust_nm", "name": "customer_name", "include": true,
              "type": "text|integer|bigint|double|boolean|date|timestamp|json|decimal(p,s)", "format": "%d/%m/%Y",
              "cast_mode": "null|fail", "default": "unknown",
              "protect": {"kind": "none|mask|hash|redact|nullify|shuffle", ...params}}]
  only_listed: columns not mentioned are dropped (False: they pass through unchanged, after the listed ones).

Security rules (read before editing):
- Names, types, formats and literals NEVER reach SQL as raw text: identifiers go through `qi()`, string values through
  `ql()`, types only from the allow-list, numeric/date defaults are pattern-checked first (`typed_literal`).
- Salts / seeds are secrets-ish: they are never persisted (`public_summary` drops them), templates drop them
  (`template_columns`), and the server hands them to the worker through a short-lived side channel (`split_secrets`
  / `merge_secrets`) instead of the job arguments. Error messages and logs name columns, never values.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Optional


class ColmapError(ValueError):
    """A user-facing problem with the column map."""


NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
RESERVED = "__rn"
TYPES = {"text": "VARCHAR", "integer": "INTEGER", "bigint": "BIGINT", "double": "DOUBLE", "boolean": "BOOLEAN",
         "date": "DATE", "timestamp": "TIMESTAMP", "json": "JSON"}
_DECIMAL = re.compile(r"^(?:decimal|numeric)\(\s*(\d{1,2})\s*,\s*(\d{1,2})\s*\)$", re.I)
_FORMAT = re.compile(r"^[%A-Za-z0-9 :/.,_T\-]{1,40}$")
# source types a default / nullify can be written for (DuckDB's own spelling, as DESCRIBE reports it)
_SIMPLE = re.compile(r"^(VARCHAR|BIGINT|INTEGER|SMALLINT|TINYINT|UBIGINT|UINTEGER|USMALLINT|UTINYINT|HUGEINT|DOUBLE|FLOAT|"
                     r"BOOLEAN|DATE|TIME|TIMESTAMP|TIMESTAMP WITH TIME ZONE|TIMESTAMP_[A-Z]+|UUID|JSON|"
                     r"DECIMAL\(\d+,\s*\d+\))$")
PROTECT_KINDS = ("none", "mask", "hash", "redact", "nullify", "shuffle")
CAST_MODES = ("null", "fail")
MAX_COLUMNS = 1000
SECRET_KEYS = ("salt", "seed")      # protect params that must not be stored anywhere


# ---- quoting (the only way user text gets into SQL) ----------------------------------------------------------------

def qi(name: str) -> str:
    """A double-quoted SQL identifier."""
    if "\x00" in name:
        raise ColmapError("A column name contains an invalid character.")
    return '"' + name.replace('"', '""') + '"'


def ql(value: Any) -> str:
    """A single-quoted SQL string literal."""
    s = str(value)
    if "\x00" in s:
        raise ColmapError("A value contains an invalid character.")
    return "'" + s.replace("'", "''") + "'"


# ---- types and literals --------------------------------------------------------------------------------------------

def parse_type(text: Optional[str]) -> Optional[tuple[str, str]]:
    """'integer' → ('integer', 'INTEGER'); 'decimal(12,2)' → ('decimal', 'DECIMAL(12,2)'); blank → None."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in TYPES:
        return t, TYPES[t]
    m = _DECIMAL.match(t)
    if m:
        p, s = int(m.group(1)), int(m.group(2))
        if not (1 <= p <= 38 and 0 <= s <= p):
            raise ColmapError(f"Type '{text}': precision must be 1–38 and scale 0–precision.")
        return "decimal", f"DECIMAL({p},{s})"
    raise ColmapError(f"Unknown type '{text}' — use text, integer, bigint, decimal(p,s), double, boolean, date, "
                      f"timestamp or json.")


_INT = re.compile(r"^-?\d{1,38}$")
_NUM = re.compile(r"^-?\d+(\.\d+)?([eE][+-]?\d+)?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$")


def typed_literal(value: Any, duck_type: str, column: str = "") -> str:
    """`value` as a SQL expression of `duck_type`. Numbers / dates / booleans are pattern-checked, everything else is a
    quoted string cast — user text never becomes SQL."""
    if isinstance(value, bool):
        value = "true" if value else "false"
    v = str(value).strip() if duck_type != "VARCHAR" else str(value)
    t = duck_type.upper()
    where = f" for '{column}'" if column else ""
    if t in ("VARCHAR", "JSON", "UUID"):
        return f"CAST({ql(v)} AS {t})"
    if t in ("INTEGER", "BIGINT", "SMALLINT", "TINYINT", "UBIGINT", "UINTEGER", "USMALLINT", "UTINYINT", "HUGEINT"):
        if not _INT.match(v):
            raise ColmapError(f"The 'if empty' value{where} must be a whole number.")
        return f"CAST({ql(v)} AS {t})"
    if t in ("DOUBLE", "FLOAT") or t.startswith("DECIMAL"):
        if not _NUM.match(v):
            raise ColmapError(f"The 'if empty' value{where} must be a number.")
        return f"CAST({ql(v)} AS {t})"
    if t == "BOOLEAN":
        low = v.lower()
        if low in ("true", "1", "yes", "y"):
            return "TRUE"
        if low in ("false", "0", "no", "n"):
            return "FALSE"
        raise ColmapError(f"The 'if empty' value{where} must be true or false.")
    if t == "DATE":
        if not _DATE.match(v):
            raise ColmapError(f"The 'if empty' value{where} must be a date like 2026-10-31.")
        return f"CAST({ql(v)} AS DATE)"
    if t.startswith("TIMESTAMP"):
        if not _TS.match(v):
            raise ColmapError(f"The 'if empty' value{where} must be a timestamp like 2026-10-31 14:30:00.")
        return f"CAST({ql(v)} AS {t})"
    if t == "TIME":
        return f"CAST({ql(v)} AS TIME)"
    raise ColmapError(f"An 'if empty' value{where} needs a simple column type — set the Type first.")


# ---- the map -------------------------------------------------------------------------------------------------------

@dataclass
class Entry:
    source: str
    name: str
    include: bool = True
    type_key: Optional[str] = None
    duck_type: Optional[str] = None
    fmt: Optional[str] = None
    cast_mode: str = "null"
    default: Optional[str] = None
    protect: str = "none"
    params: dict[str, Any] = field(default_factory=dict)


def _int_param(p: dict, key: str, default: int, lo: int, hi: int, column: str) -> int:
    v = p.get(key, default)
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ColmapError(f"Protection of '{column}': {key} must be a whole number.") from None
    if not lo <= v <= hi:
        raise ColmapError(f"Protection of '{column}': {key} must be between {lo} and {hi}.")
    return v


def _protect_params(kind: str, p: dict, column: str) -> dict[str, Any]:
    if kind == "mask":
        ch = p.get("char") or "*"
        if not isinstance(ch, str) or len(ch) != 1 or ord(ch) < 32:
            raise ColmapError(f"Protection of '{column}': the mask character must be one visible character.")
        return {"keep_first": _int_param(p, "keep_first", 0, 0, 50, column),
                "keep_last": _int_param(p, "keep_last", 0, 0, 50, column), "char": ch, "email": bool(p.get("email"))}
    if kind == "hash":
        salt = str(p.get("salt") or "")
        if len(salt) > 200:
            raise ColmapError(f"Protection of '{column}': the salt is longer than 200 characters.")
        return {"salt": salt, "length": _int_param(p, "length", 64, 8, 64, column)}
    if kind == "redact":
        text = str(p.get("text") if p.get("text") not in (None, "") else "[REDACTED]")
        if len(text) > 100:
            raise ColmapError(f"Protection of '{column}': the replacement text is longer than 100 characters.")
        return {"text": text}
    if kind == "shuffle":
        seed = str(p.get("seed") or "")
        if len(seed) > 200:
            raise ColmapError(f"Protection of '{column}': the seed is longer than 200 characters.")
        return {"seed": seed}
    return {}


def normalize_entries(columns: Any) -> list[Entry]:
    """Check the shape of the map (no data needed) and return clean entries. Raises ColmapError."""
    if not isinstance(columns, list):
        raise ColmapError("The column map must be a list.")
    if len(columns) > MAX_COLUMNS:
        raise ColmapError(f"At most {MAX_COLUMNS} columns in a map.")
    out: list[Entry] = []
    for i, c in enumerate(columns, 1):
        if not isinstance(c, dict):
            raise ColmapError(f"Map row {i} is not an object.")
        src = c.get("source")
        if not isinstance(src, str) or not src:
            raise ColmapError(f"Map row {i} has no source column.")
        include = c.get("include", True) is not False
        name = c.get("name")
        name = src if (not name or name == src) else str(name).strip()
        if include and name != src and not NAME_RE.match(name):
            raise ColmapError(f"Column name '{name}': use letters, digits and _ (start with a letter or _, max 63).")
        if include and name.lower() == RESERVED:
            raise ColmapError(f"'{RESERVED}' is a reserved column name.")
        parsed = parse_type(c.get("type"))
        fmt = (c.get("format") or "").strip() or None
        if fmt is not None:
            if not parsed or parsed[0] not in ("date", "timestamp"):
                raise ColmapError(f"'{src}': a date format only applies to a date or timestamp type.")
            if not _FORMAT.match(fmt):
                raise ColmapError(f"'{src}': the date format has characters that aren't allowed.")
        mode = c.get("cast_mode") or "null"
        if mode not in CAST_MODES:
            raise ColmapError(f"'{src}': cast_mode must be null or fail.")
        default = c.get("default")
        if default is not None and not isinstance(default, (str, int, float, bool)):
            raise ColmapError(f"'{src}': the 'if empty' value must be plain text or a number.")
        if default is not None and not isinstance(default, bool) and str(default) == "":
            default = None
        prot = c.get("protect") or {"kind": "none"}
        if not isinstance(prot, dict):
            raise ColmapError(f"'{src}': protect must be an object.")
        kind = prot.get("kind") or "none"
        if kind not in PROTECT_KINDS:
            raise ColmapError(f"'{src}': unknown protection '{kind}'.")
        out.append(Entry(source=src, name=name, include=include, type_key=parsed[0] if parsed else None,
                         duck_type=parsed[1] if parsed else None, fmt=fmt, cast_mode=mode,
                         default=None if default is None else str(default), protect=kind,
                         params=_protect_params(kind, prot, src)))
    return out


def _cast_exprs(e: Entry, base: str, src_type: str) -> tuple[str, str]:
    """(the cast used for the output, the never-failing twin used to count values that don't convert). Text is trimmed
    first: it is what a cast ignores anyway, and it keeps the cast out of reach of DuckDB's CSV-reader push-down (a
    TRY_CAST right on a CSV column can otherwise raise instead of giving NULL on some versions)."""
    strict = e.cast_mode == "fail"
    inp = f"trim({base})" if src_type.upper() == "VARCHAR" else base
    if e.fmt:
        def conv(fn: str) -> str:
            inner = f"{fn}(CAST({inp} AS VARCHAR), {ql(e.fmt)})"
            return inner if e.type_key == "timestamp" else f"CAST({inner} AS DATE)"
        return conv("strptime" if strict else "try_strptime"), conv("try_strptime")
    return f"{'CAST' if strict else 'TRY_CAST'}({inp} AS {e.duck_type})", f"TRY_CAST({inp} AS {e.duck_type})"


@dataclass
class Compiled:
    select_sql: str
    columns: list[dict[str, Any]]                       # [{name, source, type, protect}] in output order
    cast_checks: list[tuple[str, str, str, str]]        # (target column, type, cast_mode, SQL "this value fails")
    uses_shuffle: bool = False


def compile_select(source_sql: str, available: dict[str, str], columns: Any, only_listed: bool = False) -> Compiled:
    """The map as one SELECT over `source_sql` (any SELECT; its columns are `available`: name → DuckDB type)."""
    entries = normalize_entries(columns)
    if not entries:
        raise ColmapError("The column map is empty.")
    excluded = {e.source for e in entries if not e.include}
    used = [e for e in entries if e.include]
    listed = {e.source for e in used}
    stage_a: list[str] = []
    stage_types: dict[str, str] = {}      # output name → DuckDB type after stage A
    final: list[tuple[str, str]] = []     # (output name, final expression)
    shuffles: list[tuple[int, str]] = []  # (index, output name)
    seeds: dict[int, str] = {}
    checks: list[tuple[str, str, str, str]] = []
    out_cols: list[dict[str, Any]] = []
    seen: set[str] = set()

    def claim(name: str) -> None:
        if name.lower() == RESERVED:
            raise ColmapError(f"'{RESERVED}' is a reserved column name.")
        if name.lower() in seen:
            raise ColmapError(f"Two columns would be called '{name}' — give one a different name.")
        seen.add(name.lower())

    for e in used:
        if e.source not in available:
            raise ColmapError(f"The data has no column '{e.source}'.")
        claim(e.name)
        base = qi(e.source)
        src_type = available[e.source]
        typ = src_type
        expr = base
        if e.duck_type:
            typ = e.duck_type
            cast, try_cast = _cast_exprs(e, base, src_type)
            if e.duck_type.upper() != src_type.upper() or e.fmt:
                expr = cast
                checks.append((e.name, e.duck_type, e.cast_mode,
                               f"({base} IS NOT NULL AND trim(CAST({base} AS VARCHAR)) <> '' AND {try_cast} IS NULL)"))
        if e.default is not None:
            if not _SIMPLE.match(typ.upper()):
                raise ColmapError(f"'{e.source}': set a Type to use 'if empty' on this kind of column.")
            lit = typed_literal(e.default, typ, e.source)
            if typ.upper() == "VARCHAR":
                expr = f"CASE WHEN {expr} IS NULL OR trim({expr}) = '' THEN {lit} ELSE {expr} END"
            else:
                expr = f"COALESCE({expr}, {lit})"
        stage_a.append(f"{expr} AS {qi(e.name)}")
        stage_types[e.name] = typ
        v = f"a.{qi(e.name)}"
        vs = f"CAST({v} AS VARCHAR)"
        out_type = typ
        if e.protect == "mask":
            p = e.params
            ch, kf, kl = ql(p["char"]), p["keep_first"], p["keep_last"]
            generic = (f"CASE WHEN {vs} IS NULL THEN NULL WHEN length({vs}) <= {kf + kl} THEN repeat({ch}, length({vs})) "
                       f"ELSE substr({vs}, 1, {kf}) || repeat({ch}, length({vs}) - {kf + kl}) || "
                       f"{('substr(' + vs + ', length(' + vs + ') - ' + str(kl - 1) + ')') if kl else repr('')} END")
            if p["email"]:
                at = f"strpos({vs}, '@')"
                keep = f"least({kf}, {at} - 2)"
                fexpr = (f"CASE WHEN {vs} IS NULL THEN NULL WHEN {at} > 1 THEN substr({vs}, 1, {keep}) || "
                         f"repeat({ch}, {at} - 1 - {keep}) || substr({vs}, {at}) ELSE {generic} END")
            else:
                fexpr = generic
            out_type = "VARCHAR"
        elif e.protect == "hash":
            fexpr = (f"CASE WHEN {vs} IS NULL THEN NULL ELSE left(sha256({ql(e.params['salt'])} || '|' || {vs}), "
                     f"{e.params['length']}) END")
            out_type = "VARCHAR"
        elif e.protect == "redact":
            fexpr = f"CASE WHEN {vs} IS NULL THEN NULL ELSE {ql(e.params['text'])} END"
            out_type = "VARCHAR"
        elif e.protect == "nullify":
            fexpr = f"CAST(NULL AS {typ if _SIMPLE.match(typ.upper()) else 'VARCHAR'})"
            out_type = typ if _SIMPLE.match(typ.upper()) else "VARCHAR"
        elif e.protect == "shuffle":
            k = len(shuffles)
            shuffles.append((k, e.name))
            seeds[k] = e.params.get("seed", "")
            fexpr = f"sh{k}.val"
        else:
            fexpr = v
        final.append((e.name, fexpr))
        out_cols.append({"name": e.name, "source": e.source, "type": out_type, "protect": e.protect})

    if not only_listed:
        for name, typ in available.items():
            if name in listed or name in excluded:
                continue
            claim(name)
            stage_a.append(f"{qi(name)} AS {qi(name)}")
            final.append((name, f"a.{qi(name)}"))
            out_cols.append({"name": name, "source": name, "type": typ, "protect": "none"})

    if not final:
        raise ColmapError("Every column is switched off — keep at least one.")

    uses_shuffle = bool(shuffles)
    if uses_shuffle:
        stage_a.insert(0, f"row_number() OVER () AS {qi(RESERVED)}")
    ctes = [f"a AS {'MATERIALIZED ' if uses_shuffle else ''}(SELECT {', '.join(stage_a)} FROM ({source_sql}) AS src)"]
    joins = ""
    for k, name in shuffles:
        order = ("random()" if not seeds[k] else f"hash(CAST({qi(RESERVED)} AS VARCHAR) || '|' || {ql(seeds[k])})")
        # (a window ORDER BY may not be volatile, so the random key is computed one level down)
        ctes.append(f"sh{k} AS (SELECT x.rn AS rn, y.val AS val FROM "
                    f"(SELECT rn, row_number() OVER (ORDER BY k, rn) AS p FROM "
                    f"(SELECT {qi(RESERVED)} AS rn, {order} AS k FROM a)) AS x "
                    f"JOIN (SELECT {qi(name)} AS val, row_number() OVER (ORDER BY {qi(RESERVED)}) AS p FROM a) AS y "
                    f"ON x.p = y.p)")
        joins += f" JOIN sh{k} ON a.{qi(RESERVED)} = sh{k}.rn"
    select = ("WITH " + ", ".join(ctes) + " SELECT " + ", ".join(f"{expr} AS {qi(name)}" for name, expr in final)
              + " FROM a" + joins)
    return Compiled(select_sql=select, columns=out_cols, cast_checks=checks, uses_shuffle=uses_shuffle)


def failing_count_sql(source_sql: str, checks: list[tuple[str, str, str, str]]) -> str:
    """One pass over the source counting, per cast column, the values that don't convert."""
    parts = ", ".join(f"count(*) FILTER (WHERE {c[3]}) AS f{i}" for i, c in enumerate(checks))
    return f"SELECT {parts} FROM ({source_sql}) AS src"


# ---- what may be stored / shown ------------------------------------------------------------------------------------

def public_summary(columns: Any, only_listed: bool = False) -> dict[str, Any]:
    """The map as stored in the table's `source` (Tables tab shows it): names, types and protection KINDS only —
    never salts, seeds, replacement texts or default values."""
    out = []
    for e in normalize_entries(columns):
        if not e.include:
            continue
        out.append({"source": e.source, "name": e.name, "type": e.type_key or None, "protect": e.protect,
                    **({"filled": True} if e.default is not None else {})})
    return {"columns": out, "only_listed": bool(only_listed)}


def template_columns(columns: Any) -> list[dict[str, Any]]:
    """What a saved template keeps: the map minus salts / seeds (re-enter them when you use it), and minus 'if empty'
    values of protected columns."""
    clean = []
    for c in copy.deepcopy(columns):
        prot = dict(c.get("protect") or {"kind": "none"})
        for k in SECRET_KEYS:
            prot.pop(k, None)
        if prot.get("kind") not in (None, "none"):
            c.pop("default", None)
        c["protect"] = prot
        clean.append(c)
    return clean


def split_secrets(columns: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    """(columns without salt/seed, {row index: {salt/seed}}) — the server keeps the second part out of the job args."""
    clean, secrets = copy.deepcopy(columns), {}
    for i, c in enumerate(clean):
        prot = c.get("protect")
        if isinstance(prot, dict):
            found = {k: str(prot.pop(k)) for k in SECRET_KEYS if prot.get(k)}
            if found:
                secrets[str(i)] = found
                prot["has_secret"] = True       # the worker fails clearly if the side channel expired
    return clean, secrets


def merge_secrets(columns: list[dict[str, Any]], secrets: Optional[dict[str, dict[str, str]]]) -> list[dict[str, Any]]:
    out = copy.deepcopy(columns)
    for i, found in (secrets or {}).items():
        try:
            prot = out[int(i)].setdefault("protect", {})
            prot.update(found)
            prot.pop("has_secret", None)
        except (ValueError, IndexError):
            continue
    return out


# ---- guessing what is sensitive ------------------------------------------------------------------------------------

def _tokens(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return [t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t]


def _luhn(digits: str) -> bool:
    total, flip = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if flip:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        flip = not flip
    return total % 10 == 0


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_AADHAAR = re.compile(r"^\d{4}[ -]?\d{4}[ -]?\d{4}$")
_PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_SSN = re.compile(r"^\d{3}-\d{2}-\d{4}$")
_PHONE = re.compile(r"^\+?\d[\d\s\-()]{8,17}\d$")
_NAME_PREFIX = {"first", "last", "full", "middle", "sur", "customer", "cust", "employee", "emp", "person", "patient",
                "user", "client", "contact", "owner", "applicant", "member"}


def suggest_protection(name: str, samples: list[Any]) -> Optional[dict[str, Any]]:
    """A guess at whether a column is sensitive and how to protect it: {"kind", "params", "reason"} or None. It only
    PRE-SELECTS in the UI — the user confirms by loading."""
    toks = _tokens(name)
    joined = "_".join(toks)
    vals = [str(v).strip() for v in samples if v is not None and str(v).strip()]

    def share(rx: re.Pattern) -> float:
        return sum(1 for v in vals if rx.match(v)) / len(vals) if vals else 0.0

    def has(*words: str) -> bool:
        return any(w in joined for w in words)

    if has("email", "e_mail") or share(_EMAIL) >= 0.6:
        return {"kind": "mask", "params": {"keep_first": 1, "keep_last": 0, "char": "*", "email": True},
                "reason": "looks like an email address"}
    if has("aadhaar", "aadhar", "uidai") or share(_AADHAAR) >= 0.8:
        return {"kind": "mask", "params": {"keep_first": 0, "keep_last": 4, "char": "*", "email": False},
                "reason": "looks like an Aadhaar number"}
    if "pan" in toks or has("pan_no", "pan_number") or share(_PAN) >= 0.8:
        return {"kind": "mask", "params": {"keep_first": 0, "keep_last": 4, "char": "*", "email": False},
                "reason": "looks like a PAN"}
    digits = [re.sub(r"[ -]", "", v) for v in vals]
    card_like = [d for d in digits if d.isdigit() and 13 <= len(d) <= 19 and _luhn(d)]
    if has("card", "credit", "debit", "cc_num") or (vals and len(card_like) / len(vals) >= 0.8):
        return {"kind": "mask", "params": {"keep_first": 0, "keep_last": 4, "char": "*", "email": False},
                "reason": "looks like a card number"}
    if has("ssn", "social_security") or share(_SSN) >= 0.8:
        return {"kind": "mask", "params": {"keep_first": 0, "keep_last": 4, "char": "*", "email": False},
                "reason": "looks like a social security number"}
    if has("phone", "mobile", "msisdn", "cell", "telephone", "contact_no", "contact_number") or "tel" in toks:
        return {"kind": "mask", "params": {"keep_first": 0, "keep_last": 2, "char": "*", "email": False},
                "reason": "looks like a phone number"}
    if has("password", "passwd", "secret", "token", "api_key", "apikey", "passport"):
        return {"kind": "redact", "params": {"text": "[REDACTED]"}, "reason": "looks like a secret or an ID document"}
    if has("address", "street") or "addr" in toks:
        return {"kind": "redact", "params": {"text": "[REDACTED]"}, "reason": "looks like an address"}
    if has("dob", "birth", "date_of_birth"):
        return {"kind": "shuffle", "params": {}, "reason": "looks like a date of birth"}
    named = ("name" in toks or "nm" in toks) and (len(toks) == 1 or any(t in _NAME_PREFIX for t in toks))
    if named or joined in ("fname", "lname", "firstname", "lastname", "fullname", "surname"):
        return {"kind": "shuffle", "params": {}, "reason": "looks like a person's name"}
    return None


# ---- saved templates (Postgres schema `data_lake`, table `colmaps`) -----------------------------------------------

def _query():
    try:
        from data_lake import query
    except ImportError:  # standalone
        import query
    return query


def list_templates() -> list[dict[str, Any]]:
    import json

    with _query()._connect() as con:
        rows = con.execute("SELECT * FROM colmaps ORDER BY name").fetchall()
    return [{"id": r["id"], "name": r["name"], "columns": json.loads(r["columns"]), "only_listed": bool(r["only_listed"]),
             "updated_at": r["updated_at"]} for r in rows]


def save_template(name: str, columns: Any, only_listed: bool = False) -> dict[str, Any]:
    """Store a map under a name (replaces the same name). Salts / seeds / protected defaults are dropped first."""
    import json

    q = _query()
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise ColmapError("Give the template a name (up to 120 characters).")
    normalize_entries(columns)                      # shape check
    clean = template_columns(columns)
    now = q._now()
    with q._connect() as con:
        old = con.execute("SELECT id FROM colmaps WHERE name = ?", (name,)).fetchone()
        tid = old["id"] if old else q.new_id()
        if old:
            con.execute("UPDATE colmaps SET columns = ?, only_listed = ?, updated_at = ? WHERE id = ?",
                        (json.dumps(clean), 1 if only_listed else 0, now, tid))
        else:
            con.execute("INSERT INTO colmaps (id, name, columns, only_listed, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                        (tid, name, json.dumps(clean), 1 if only_listed else 0, now, now))
    return {"id": tid, "name": name, "columns": clean, "only_listed": bool(only_listed), "updated_at": now}


def delete_template(tid: str) -> None:
    with _query()._connect() as con:
        con.execute("DELETE FROM colmaps WHERE id = ?", (tid,))
