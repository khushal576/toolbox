"""
df-studio/formula.py

The expression bar (roadmap Phase DF, DF2): `ratio = a / b` — one line per new column instead of a whole
`def transform(df)` function.

This is NOT a way to run arbitrary Python. The text is parsed with `ast`, every node is checked against a small
allow-list (numbers, text, column names, + - * / // % **, comparisons, & | ~ and/or/not, `x if c else y`, and calls of
the functions in FUNCS — nothing else: no attributes, no subscripts, no lambdas, no comprehensions, no imports), and
then the code the step runs is GENERATED from the checked tree (`df['ratio'] = (df['a'] / df['b'])`) — the user's
text itself is never executed. Column names are only ever looked up in df.columns and written out with repr().

Names with spaces or odd characters go in backticks: `unit price` * qty. Handlers raise plain ValueError (CLAUDE.md).
"""

from __future__ import annotations

import ast
import difflib
import re
from typing import Any

import pandas as pd

try:  # package import inside the toolbox
    from df_studio import clean_steps as cs
except ImportError:  # standalone / tests
    import clean_steps as cs

MAX_LINES = 50
MAX_EXPR_CHARS = 2000
MAX_NODES = 250
MAX_CONST_STR = 2000
MAX_INT = 10**18
_NOCONST = object()

# name → (min args, max args, one-line help). The emitters are in Emitter._call.
FUNCS: dict[str, tuple[int, int, str]] = {
    "where": (3, 3, "where(condition, if_true, if_false) — also: a if condition else b"),
    "coalesce": (2, 10, "coalesce(a, b, …) — the first value that isn't empty"),
    "ifnull": (2, 2, "ifnull(x, fallback) — x, or fallback when x is empty"),
    "isnull": (1, 1, "isnull(x) — true when empty"),
    "notnull": (1, 1, "notnull(x) — true when not empty"),
    "abs": (1, 1, "abs(x)"),
    "sqrt": (1, 1, "sqrt(x)"),
    "exp": (1, 1, "exp(x)"),
    "log": (1, 1, "log(x) — natural logarithm"),
    "log10": (1, 1, "log10(x)"),
    "floor": (1, 1, "floor(x) — round down"),
    "ceil": (1, 1, "ceil(x) — round up"),
    "round": (1, 2, "round(x, digits) — digits is optional"),
    "clip": (3, 3, "clip(x, low, high) — keep x between low and high"),
    "greatest": (2, 2, "greatest(a, b) — the larger of two values"),
    "least": (2, 2, "least(a, b) — the smaller of two values"),
    "cut": (2, 3, "cut(x, [0, 18, 65], ['child', 'adult']) — group numbers into ranges (labels optional)"),
    "qcut": (2, 3, "qcut(x, 4) — group into 4 equal-count groups (labels optional)"),
    "lower": (1, 1, "lower(text)"),
    "upper": (1, 1, "upper(text)"),
    "strip": (1, 1, "strip(text) — trim spaces at both ends"),
    "title": (1, 1, "title(text) — Capitalise Each Word"),
    "len": (1, 1, "len(text) — number of characters"),
    "concat": (2, 10, "concat(a, b, …) — join text (numbers are turned into text)"),
    "contains": (2, 2, "contains(text, 'abc') — true when it appears"),
    "startswith": (2, 2, "startswith(text, 'abc')"),
    "endswith": (2, 2, "endswith(text, 'abc')"),
    "replace": (3, 3, "replace(text, 'old', 'new')"),
    "left": (2, 2, "left(text, n) — first n characters"),
    "right": (2, 2, "right(text, n) — last n characters"),
    "to_number": (1, 1, "to_number(x) — text to number (bad values become empty)"),
    "to_date": (1, 1, "to_date(x) — text to date (bad values become empty)"),
    "to_text": (1, 1, "to_text(x)"),
    "year": (1, 1, "year(date)"),
    "month": (1, 1, "month(date)"),
    "day": (1, 1, "day(date)"),
    "hour": (1, 1, "hour(date)"),
    "minute": (1, 1, "minute(date)"),
    "weekday": (1, 1, "weekday(date) — 0 = Monday … 6 = Sunday"),
    "quarter": (1, 1, "quarter(date)"),
    "dayofyear": (1, 1, "dayofyear(date)"),
}

_DT = {"year": "year", "month": "month", "day": "day", "hour": "hour", "minute": "minute", "weekday": "dayofweek",
       "quarter": "quarter", "dayofyear": "dayofyear"}
_NP1 = {"abs": "np.abs", "sqrt": "np.sqrt", "exp": "np.exp", "log": "np.log", "log10": "np.log10",
        "floor": "np.floor", "ceil": "np.ceil"}
_STR1 = {"lower": "lower()", "upper": "upper()", "strip": "strip()", "title": "title()", "len": "len()"}
_BIN = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**",
        ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^"}
_CMP = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}
_NICE = {
    "Attribute": "dots (like .str or df.col) aren't allowed — use a function such as lower(col)",
    "Subscript": "square brackets on a value aren't allowed — write the column name directly",
    "Lambda": "lambda isn't allowed here — use the Query box for full Python",
    "ListComp": "loops and comprehensions aren't allowed here — use the Query box for full Python",
    "GeneratorExp": "loops and comprehensions aren't allowed here — use the Query box for full Python",
    "DictComp": "loops and comprehensions aren't allowed here — use the Query box for full Python",
    "SetComp": "loops and comprehensions aren't allowed here — use the Query box for full Python",
    "JoinedStr": "f-strings aren't allowed — use concat(a, b)",
    "Dict": "dictionaries aren't allowed here",
    "Set": "sets aren't allowed here",
    "NamedExpr": "':=' isn't allowed",
    "Starred": "'*' unpacking isn't allowed",
    "Await": "await isn't allowed",
    "Yield": "yield isn't allowed",
}


def _bad(node: ast.AST) -> ValueError:
    kind = type(node).__name__
    return ValueError(f"This isn't allowed in a formula: {_NICE.get(kind, kind)}. "
                      "For anything else use the Query box (full pandas).")


# ---------------------------------------------------------------------------------------------------------------
# text → list of (target, ast expression)
# ---------------------------------------------------------------------------------------------------------------

_BT = re.compile(r"`([^`\n]+)`")


def _lines(params: dict[str, Any]) -> list[tuple[str, str]]:
    """The formulas as [(target, expression text)] — accepts {"text": "a = 1\\nb = 2"} or {"lines": [{target, expr}]}.
    Targets/expressions may contain `backticked names`."""
    out: list[tuple[str, str]] = []
    if params.get("lines"):
        for ln in params["lines"]:
            out.append((str(ln.get("target") or "").strip(), str(ln.get("expr") or "").strip()))
    else:
        for raw in str(params.get("text") or "").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            out.append(("", raw))
    return out


class _Line:
    def __init__(self, target: str, expr: ast.AST, names: dict[str, str]):
        self.target, self.expr, self.names = target, expr, names


def _parse_line(target: str, text: str, n: int) -> _Line:
    if len(text) > MAX_EXPR_CHARS:
        raise ValueError(f"Formula {n} is too long.")
    names: dict[str, str] = {}

    def sub(m: re.Match) -> str:
        key = f"_bt{len(names)}_"
        names[key] = m.group(1)
        return key

    t_text = _BT.sub(sub, target)
    e_text = _BT.sub(sub, text)
    if "`" in t_text or "`" in e_text:
        raise ValueError(f"Formula {n}: a ` backtick is not closed.")
    if not target:  # "name = expression" typed on one line
        try:
            tree = ast.parse(e_text.strip(), mode="exec")
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            raise ValueError(f"Formula {n}: I can't read that. Write it like  total = price * qty") from None
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assign) or len(tree.body[0].targets) != 1 \
                or not isinstance(tree.body[0].targets[0], ast.Name):
            raise ValueError(f"Formula {n}: write it like  total = price * qty  (a new column name, '=', then the formula).")
        tname = tree.body[0].targets[0].id
        expr = tree.body[0].value
    else:
        tname = t_text.strip()
        try:
            expr = ast.parse(e_text.strip(), mode="eval").body
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            raise ValueError(f"Formula {n}: I can't read '{text[:60]}'.") from None
    real = names.get(tname, tname)
    if not real or len(real) > 200 or "\n" in real:
        raise ValueError(f"Formula {n}: give the new column a name.")
    if not target and not names.get(tname) and not tname.isidentifier():
        raise ValueError(f"Formula {n}: put names with spaces or symbols in backticks, like `unit price`.")
    if sum(1 for _ in ast.walk(expr)) > MAX_NODES:
        raise ValueError(f"Formula {n} is too complicated — split it into two lines.")
    return _Line(real, expr, names)


# ---------------------------------------------------------------------------------------------------------------
# AST → pandas source
# ---------------------------------------------------------------------------------------------------------------

class Emitter:
    """Checks the tree node by node and writes the pandas source. emit() returns (code, has_column, constant)."""

    def __init__(self, known: set[str], names: dict[str, str], line_no: int):
        self.known, self.names, self.n = known, names, line_no

    def fail(self, msg: str) -> ValueError:
        return ValueError(f"Formula {self.n}: {msg}")

    def emit(self, node: ast.AST) -> tuple[str, bool, Any]:
        m = getattr(self, "_" + type(node).__name__, None)
        if m is None:
            raise _bad(node)
        return m(node)

    # --- leaves
    def _Constant(self, node: ast.Constant):
        v = node.value
        if isinstance(v, bool) or v is None:
            return repr(v), False, v
        if isinstance(v, int):
            if abs(v) > MAX_INT:
                raise self.fail("that number is too large.")
            return repr(v), False, v
        if isinstance(v, float):
            if v != v or v in (float("inf"), float("-inf")):
                raise self.fail("that number isn't usable.")
            return repr(v), False, v
        if isinstance(v, str):
            if len(v) > MAX_CONST_STR:
                raise self.fail("that text is too long.")
            return repr(v), False, v
        raise _bad(node)

    def _Name(self, node: ast.Name):
        name = self.names.get(node.id, node.id)
        if name in self.known:
            return f"df[{name!r}]", True, _NOCONST
        close = difflib.get_close_matches(name, list(self.known), n=3, cutoff=0.6) if len(self.known) < 20000 else []
        hint = f" Did you mean {', '.join(repr(c) for c in close)}?" if close else ""
        extra = "" if name.isidentifier() else " (names with spaces go in backticks)"
        if name in FUNCS:
            raise self.fail(f"'{name}' is a function — use it like {name}(…).")
        raise self.fail(f"there's no column '{name}'.{hint}{extra}")

    # --- operators
    def _UnaryOp(self, node: ast.UnaryOp):
        c, h, k = self.emit(node.operand)
        if isinstance(node.op, ast.USub):
            return f"(-{c})", h, (-k if isinstance(k, (int, float)) and not isinstance(k, bool) else _NOCONST)
        if isinstance(node.op, ast.UAdd):
            return f"(+{c})", h, k
        if isinstance(node.op, (ast.Not, ast.Invert)):
            return f"(~{c})", h, _NOCONST
        raise _bad(node)

    def _BinOp(self, node: ast.BinOp):
        sym = _BIN.get(type(node.op))
        if sym is None:
            raise self.fail("that operator isn't allowed.")
        a, ha, ka = self.emit(node.left)
        b, hb, kb = self.emit(node.right)
        if sym == "*" and (isinstance(ka, str) or isinstance(kb, str)):
            raise self.fail("repeating text isn't allowed.")
        if sym == "**" and not hb:
            if not (isinstance(kb, (int, float)) and not isinstance(kb, bool) and abs(kb) <= 100):
                raise self.fail("a power must be a number between -100 and 100 (or a column).")
        return f"({a} {sym} {b})", ha or hb, _NOCONST

    def _BoolOp(self, node: ast.BoolOp):
        sym = " & " if isinstance(node.op, ast.And) else " | "
        parts = [self.emit(v) for v in node.values]
        return "(" + sym.join(p[0] for p in parts) + ")", any(p[1] for p in parts), _NOCONST

    def _Compare(self, node: ast.Compare):
        left = node.left
        pieces: list[str] = []
        has = False
        for op, right in zip(node.ops, node.comparators):
            lc, lh, lk = self.emit(left)
            if isinstance(op, (ast.In, ast.NotIn)):
                try:
                    items = ast.literal_eval(right)
                except (ValueError, SyntaxError):
                    raise self.fail("after 'in' write a list of values, like  country in ['IN', 'US'].") from None
                if not isinstance(items, (list, tuple)) or len(items) > 500 or not all(
                        i is None or isinstance(i, (int, float, str, bool)) for i in items):
                    raise self.fail("after 'in' write a short list of numbers or text.")
                body = f"{lc}.isin({list(items)!r})"
                pieces.append(f"(~{body})" if isinstance(op, ast.NotIn) else f"({body})")
                has = has or lh
            elif isinstance(op, (ast.Is, ast.IsNot)):
                if not (isinstance(right, ast.Constant) and right.value is None):
                    raise self.fail("'is' only works with None (empty).")
                pieces.append(f"({lc}.{'isna' if isinstance(op, ast.Is) else 'notna'}())")
                has = has or lh
            elif type(op) in _CMP:
                rc, rh, rk = self.emit(right)
                if rk is None and type(op) in (ast.Eq, ast.NotEq):  # x == None  → x is empty
                    pieces.append(f"({lc}.{'isna' if isinstance(op, ast.Eq) else 'notna'}())")
                else:
                    pieces.append(f"({lc} {_CMP[type(op)]} {rc})")
                has = has or lh or rh
            else:
                raise _bad(node)
            left = right
        code = pieces[0] if len(pieces) == 1 else "(" + " & ".join(pieces) + ")"
        return code, has, _NOCONST

    def _IfExp(self, node: ast.IfExp):
        return self._where(node.test, node.body, node.orelse)

    def _where(self, test: ast.AST, a: ast.AST, b: ast.AST):
        tc, th, _ = self.emit(test)
        ac, ah, _k = self.emit(a)
        bc, bh, _k2 = self.emit(b)
        if not th:
            raise self.fail("the condition of a choice must use a column.")
        return f"pd.Series(np.where(({tc}).fillna(False), {ac}, {bc}), index=df.index)", True, _NOCONST

    # --- calls
    def _Call(self, node: ast.Call):
        if not isinstance(node.func, ast.Name):
            raise self.fail("only the listed functions can be called (see the function list).")
        fname = node.func.id
        if node.keywords:
            raise self.fail(f"{fname}() takes plain values, not name=value options.")
        if any(isinstance(a, ast.Starred) for a in node.args):
            raise _bad(node.args[0])
        spec = FUNCS.get(fname)
        if spec is None:
            raise self.fail(f"'{fname}' isn't an available function. Available: {', '.join(sorted(FUNCS))}.")
        lo, hi, _help = spec
        if not lo <= len(node.args) <= hi:
            raise self.fail(f"{fname}() needs {lo if lo == hi else f'{lo} to {hi}'} value(s) — {_help}")
        if fname == "where":
            return self._where(*node.args)
        # literal-list arguments are checked with literal_eval, everything else is emitted
        if fname in ("cut", "qcut"):
            return self._binning(fname, node.args)
        args = [self.emit(a) for a in node.args]
        codes = [a[0] for a in args]
        has = any(a[1] for a in args)
        x = codes[0]

        def need_col() -> None:
            if not args[0][1]:
                raise self.fail(f"{fname}() needs a column as its first value.")

        def const_str(i: int) -> str:
            if not isinstance(args[i][2], str):
                raise self.fail(f"{fname}() needs plain text in quotes as value {i + 1}.")
            return codes[i]

        def const_int(i: int, lo_: int, hi_: int) -> str:
            v = args[i][2]
            if isinstance(v, bool) or not isinstance(v, int) or not lo_ <= v <= hi_:
                raise self.fail(f"{fname}() needs a whole number between {lo_} and {hi_} as value {i + 1}.")
            return codes[i]

        if fname in _NP1:
            return f"{_NP1[fname]}({x})", has, _NOCONST
        if fname == "round":
            digits = const_int(1, -20, 20) if len(args) == 2 else "0"
            return f"np.round({x}, {digits})", has, _NOCONST
        if fname == "clip":
            return (f"({x}).clip({codes[1]}, {codes[2]})" if args[0][1] else f"np.clip({x}, {codes[1]}, {codes[2]})"), has, _NOCONST
        if fname in ("greatest", "least"):
            return f"{'np.maximum' if fname == 'greatest' else 'np.minimum'}({codes[0]}, {codes[1]})", has, _NOCONST
        if fname in ("isnull", "notnull"):
            need_col()
            return f"({x}).{'isna' if fname == 'isnull' else 'notna'}()", True, _NOCONST
        if fname in ("ifnull", "coalesce"):
            need_col()
            chain = "".join(f".fillna({c})" for c in codes[1:])
            return f"({x}){chain}", True, _NOCONST
        if fname in _STR1:
            need_col()
            return f"({x}).astype('string').str.{_STR1[fname]}", True, _NOCONST
        if fname == "concat":
            if not has:
                raise self.fail("concat() needs at least one column.")
            parts = []
            for c, a in zip(codes, args):
                if a[1]:
                    parts.append(f"({c}).astype('string').fillna('')")
                elif a[2] is _NOCONST:
                    raise self.fail("concat() takes columns and plain text or numbers.")
                else:
                    parts.append(repr("" if a[2] is None else str(a[2])))
            return "(" + " + ".join(parts) + ")", True, _NOCONST
        if fname in ("contains", "startswith", "endswith"):
            need_col()
            t = const_str(1)
            call = (f"contains({t}, regex=False, na=False)" if fname == "contains" else f"{fname}({t}, na=False)")
            return f"({x}).astype('string').str.{call}", True, _NOCONST
        if fname == "replace":
            need_col()
            return f"({x}).astype('string').str.replace({const_str(1)}, {const_str(2)}, regex=False)", True, _NOCONST
        if fname in ("left", "right"):
            need_col()
            n = const_int(1, 1, 100000)
            sl = f"slice(0, {n})" if fname == "left" else f"slice(-{n})"
            return f"({x}).astype('string').str.{sl}", True, _NOCONST
        if fname == "to_number":
            need_col()
            return f"pd.to_numeric({x}, errors='coerce')", True, _NOCONST
        if fname == "to_date":
            need_col()
            return f"pd.to_datetime({x}, errors='coerce')", True, _NOCONST
        if fname == "to_text":
            need_col()
            return f"({x}).astype('string')", True, _NOCONST
        if fname in _DT:
            need_col()
            return f"({x}).dt.{_DT[fname]}", True, _NOCONST
        raise self.fail(f"'{fname}' isn't available.")  # unreachable while FUNCS and the branches agree

    def _binning(self, fname: str, args: list[ast.AST]):
        x, hx, _ = self.emit(args[0])
        if not hx:
            raise self.fail(f"{fname}() needs a column as its first value.")
        try:
            second = ast.literal_eval(args[1])
            labels = ast.literal_eval(args[2]) if len(args) == 3 else None
        except (ValueError, SyntaxError):
            raise self.fail(f"{fname}() needs plain numbers / text in [ ] for its options.") from None
        lab = ""
        if labels is not None:
            if not isinstance(labels, (list, tuple)) or not labels or not all(isinstance(i, str) for i in labels):
                raise self.fail("the labels must be a list of text, like ['low', 'high'].")
            lab = f", labels={list(labels)!r}"
        if fname == "cut":
            if not isinstance(second, (list, tuple)) or len(second) < 2 or len(second) > 200 or not all(
                    isinstance(i, (int, float)) and not isinstance(i, bool) for i in second) \
                    or list(second) != sorted(set(second)):
                raise self.fail("cut() needs the edges as a list, smallest first, like [0, 18, 65].")
            if labels is not None and len(labels) != len(second) - 1:
                raise self.fail(f"cut(): {len(second) - 1} group(s) need {len(second) - 1} label(s).")
            return f"pd.cut({x}, bins={list(second)!r}{lab}, include_lowest=True).astype('string')", True, _NOCONST
        if isinstance(second, bool) or not isinstance(second, int) or not 2 <= second <= 100:
            raise self.fail("qcut() needs the number of groups (2 to 100), like qcut(price, 4).")
        if labels is not None and len(labels) != second:
            raise self.fail(f"qcut(): {second} group(s) need {second} label(s).")
        return f"pd.qcut({x}, q={second}{lab}, duplicates='drop').astype('string')", True, _NOCONST


# ---------------------------------------------------------------------------------------------------------------
# the step
# ---------------------------------------------------------------------------------------------------------------

def _friendly(exc: Exception) -> str:
    msg = str(exc)
    if "Can only use .dt accessor" in msg:
        return "year(), month(), … need a date column — use 'Change type → date' on it first."
    if "Can only use .str accessor" in msg:
        return "A text function was used on a column that isn't text."
    if "unsupported operand" in msg or "can only concatenate" in msg or "cannot be added" in msg.lower():
        return "Those values can't be combined with that operator (text and numbers mixed?): " + msg[:150]
    return msg[:300]


def compile_lines(df: pd.DataFrame, params: dict[str, Any]) -> list[tuple[str, str]]:
    """[(target, generated pandas line)] — validates everything, runs nothing."""
    raw = _lines(params)
    if not raw:
        raise ValueError("Type a formula, like  total = price * qty")
    if len(raw) > MAX_LINES:
        raise ValueError(f"At most {MAX_LINES} formulas at a time.")
    known = {c for c in df.columns if isinstance(c, str)}
    out: list[tuple[str, str]] = []
    for i, (target, text) in enumerate(raw, 1):
        line = _parse_line(target, text, i)
        code, has, _k = Emitter(known, line.names, i).emit(line.expr)
        if not has and not isinstance(line.expr, ast.Constant):
            pass  # a constant formula (e.g. 2 * 3) just fills the column with that value — fine
        out.append((line.target, f"df[{line.target!r}] = {code}"))
        known.add(line.target)
    return out


def expression(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    compiled = compile_lines(df, params)
    code = "\n".join(c for _t, c in compiled)
    try:
        out = cs.run(df, code)
    except ValueError as exc:
        raise ValueError(_friendly(exc)) from None
    new = [t for t, _ in compiled if t not in df.columns]
    old = [t for t, _ in compiled if t in df.columns]
    if new:
        cs.note("Added column(s): " + ", ".join(f"'{t}'" for t in dict.fromkeys(new)) + ".")
    if old:
        cs.note("Replaced existing column(s): " + ", ".join(f"'{t}'" for t in dict.fromkeys(old)) + ".")
    return out, code


def function_help() -> list[dict[str, str]]:
    return [{"name": n, "help": h} for n, (_lo, _hi, h) in sorted(FUNCS.items())]
