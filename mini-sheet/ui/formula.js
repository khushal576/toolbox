/* mini-sheet/ui/formula.js — the Mini Sheet's formula language (roadmap M1).
 *
 * A cell whose text starts with "=" is a formula. It is NEVER passed to eval()/new Function(): the text is cut into
 * tokens, parsed by a small recursive-descent parser into a tree, and the tree is walked by evaluate(). Only the
 * node kinds and functions listed here exist; every unknown word is #NAME?, every malformed thing is #ERR!.
 *
 * Language:  numbers, "text" (quotes doubled to escape), TRUE/FALSE, cell refs A1 ($A$1 anchors), ranges A1:B9
 *            (only inside functions), + - * / ^ & (join text), = <> < > <= >=, ( ), unary + -  (Excel precedence: -2^2 = 4, 2^3^2 = 64),
 *            SUM AVERAGE MIN MAX COUNT IF ROUND CONCAT LEN UPPER LOWER TRIM ABS TODAY.
 *            Other sheets of the workbook: Sheet2!A1, 'My sheet'!A1:B9 (a name with spaces/odd characters is quoted, a quote inside it is
 *            doubled). A name that doesn't exist is #REF!. Sheet names are only ever looked up through the host's resolver (opts.sheet), never
 *            as object keys, so "__proto__!A1" is just an unknown sheet.
 * Refs are plain positions: A1 = first column, first data row (header row not counted). They do not move when rows
 * are inserted/sorted (Excel does that; this tool deliberately doesn't) — fill-down/right DOES shift them (shift()).
 * Errors: #ERR! (syntax / too deep / too big), #DIV/0!, #REF! (single ref outside the sheet), #CIRC! (a cell depends
 * on itself), #NAME? (unknown function/word), #VALUE! (text where a number is needed).
 * Numeric-looking text ("12", "3.5") counts as a number everywhere — cells pasted into a text column still add up.
 *
 * Works in the browser (window.MSFormula) and in node (module.exports) — tests/unit/test_mini_sheet.py runs it there.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.MSFormula = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const LIMITS = { maxLen: 1000, maxDepth: 40, maxTokens: 600, maxRangeCells: 5000000, maxEvalDepth: 250, maxRows: 1048576, maxCols: 18278 };

  class FErr {
    constructor(code) { this.code = code; }
    toString() { return this.code; }
  }
  const E = { ERR: "#ERR!", DIV: "#DIV/0!", REF: "#REF!", CIRC: "#CIRC!", NAME: "#NAME?", VALUE: "#VALUE!" };
  const fail = (code) => { throw new FErr(code); };

  // ---- column letters ------------------------------------------------------------------------------------------
  function colToLetters(n) {          // 0 → A, 25 → Z, 26 → AA
    let s = "";
    n = Math.floor(n) + 1;
    while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
    return s;
  }
  function lettersToCol(s) {          // A → 0
    let n = 0;
    for (const ch of s.toUpperCase()) n = n * 26 + (ch.charCodeAt(0) - 64);
    return n - 1;
  }
  const REF_RE = /^(\$?)([A-Za-z]{1,3})(\$?)(\d{1,7})$/;

  // ---- tokenizer -----------------------------------------------------------------------------------------------
  // token: {t: num|str|bool|ref|range|fn|name|op|err, v, s, e, ...}   s/e = start/end offsets in the source
  function tokenize(src) {
    if (typeof src !== "string") fail(E.ERR);
    if (src.length > LIMITS.maxLen) fail(E.ERR);
    const out = [];
    let i = 0;
    const n = src.length;
    const parseRef = (w) => {
      const m = REF_RE.exec(w);
      if (!m) return null;
      return { ac: m[1] === "$", c: lettersToCol(m[2]), ar: m[3] === "$", r: parseInt(m[4], 10) - 1 };
    };
    // a cell or range at position `at` (right after "Sheet!" when sh is set); pushes the token, returns the new offset
    const readCellOrRange = (at, start, sh) => {
      const m1 = /^[A-Za-z_$][A-Za-z0-9_$.]*/.exec(src.slice(at, at + 80));
      const ref = m1 && parseRef(m1[0]);
      if (!ref) fail(E.ERR);
      let j = at + m1[0].length;
      const extra = sh === undefined ? {} : { sh, pe: at };
      if (src[j] === ":") {                                           // range A1:B2
        const m2 = /^[A-Za-z_$][A-Za-z0-9_$.]*/.exec(src.slice(j + 1, j + 81));
        const ref2 = m2 && parseRef(m2[0]);
        if (!ref2) fail(E.ERR);
        j += 1 + m2[0].length;
        out.push({ t: "range", a: ref, b: ref2, s: start, e: j, ...extra });
      } else out.push({ t: "ref", ...ref, s: start, e: j, ...extra });
      return j;
    };
    while (i < n) {
      if (out.length > LIMITS.maxTokens) fail(E.ERR);
      const ch = src[i];
      if (ch === " " || ch === "\t" || ch === "\n" || ch === "\r") { i++; continue; }
      const start = i;
      if ((ch >= "0" && ch <= "9") || (ch === "." && src[i + 1] >= "0" && src[i + 1] <= "9")) {
        const m = /^(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?/.exec(src.slice(i, i + 40));
        i += m[0].length;
        if (/[A-Za-z_$]/.test(src[i] || "")) fail(E.ERR);              // 12abc
        out.push({ t: "num", v: Number(m[0]), s: start, e: i });
        continue;
      }
      if (ch === '"') {
        let s = "";
        i++;
        for (;;) {
          if (i >= n) fail(E.ERR);                                    // unterminated text
          if (src[i] === '"') { if (src[i + 1] === '"') { s += '"'; i += 2; continue; } i++; break; }
          s += src[i++];
        }
        out.push({ t: "str", v: s, s: start, e: i });
        continue;
      }
      if (ch === "'") {                                               // 'Quoted sheet'!A1
        let name = "";
        i++;
        for (;;) {
          if (i >= n || name.length > 64) fail(E.ERR);
          if (src[i] === "'") { if (src[i + 1] === "'") { name += "'"; i += 2; continue; } i++; break; }
          name += src[i++];
        }
        if (src[i] !== "!" || !name) fail(E.ERR);
        i = readCellOrRange(i + 1, start, name);
        continue;
      }
      if (ch === "#") {                                               // only "#REF!" (what shift() writes)
        if (src.slice(i, i + 5).toUpperCase() === "#REF!") { i += 5; out.push({ t: "err", v: E.REF, s: start, e: i }); continue; }
        fail(E.ERR);
      }
      if (/[A-Za-z_$]/.test(ch)) {
        const m = /^[A-Za-z_$][A-Za-z0-9_$.]*/.exec(src.slice(i, i + 80));
        const w = m[0];
        i += w.length;
        let j = i;
        while (src[j] === " ") j++;
        if (src[j] === "(" && /^[A-Za-z_][A-Za-z0-9_.]*$/.test(w)) { out.push({ t: "fn", v: w.toUpperCase(), s: start, e: i }); continue; }
        if (src[i] === "!" && /^[A-Za-z_][A-Za-z0-9_.]*$/.test(w)) {  // Sheet2!A1
          i = readCellOrRange(i + 1, start, w);
          continue;
        }
        const ref = parseRef(w);
        if (ref) {
          if (src[i] === ":") {                                       // range A1:B2
            const m2 = /^[A-Za-z_$][A-Za-z0-9_$.]*/.exec(src.slice(i + 1, i + 81));
            const ref2 = m2 && parseRef(m2[0]);
            if (!ref2) fail(E.ERR);
            i += 1 + m2[0].length;
            out.push({ t: "range", a: ref, b: ref2, s: start, e: i });
          } else out.push({ t: "ref", ...ref, s: start, e: i });
          continue;
        }
        const up = w.toUpperCase();
        if (up === "TRUE" || up === "FALSE") { out.push({ t: "bool", v: up === "TRUE", s: start, e: i }); continue; }
        if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(w)) { out.push({ t: "name", v: w, s: start, e: i }); continue; }
        fail(E.ERR);
      }
      const two = src.slice(i, i + 2);
      if (two === "<>" || two === "<=" || two === ">=") { out.push({ t: "op", v: two, s: start, e: i + 2 }); i += 2; continue; }
      if ("+-*/^&=<>(),".indexOf(ch) >= 0) { out.push({ t: "op", v: ch, s: start, e: i + 1 }); i++; continue; }
      fail(E.ERR);                                                    // ; [ ] { } ` \ ! ? @ ~ | % . … all rejected
    }
    return out;
  }

  // ---- parser (precedence low → high: comparison, &, + -, * /, ^, unary minus) ---------------------------------
  function parse(src) {
    const toks = tokenize(src);
    if (!toks.length) fail(E.ERR);
    let p = 0;
    let depth = 0;
    const peek = () => toks[p];
    const isOp = (v) => toks[p] && toks[p].t === "op" && toks[p].v === v;
    const enter = () => { if (++depth > LIMITS.maxDepth) fail(E.ERR); };
    const leave = () => { depth--; };

    function expr() {
      enter();
      let a = concat();
      while (peek() && peek().t === "op" && ["=", "<>", "<", ">", "<=", ">="].indexOf(peek().v) >= 0) {
        const op = toks[p++].v;
        a = { k: "bin", op, a, b: concat() };
      }
      leave();
      return a;
    }
    function concat() {
      let a = additive();
      while (isOp("&")) { p++; a = { k: "bin", op: "&", a, b: additive() }; }
      return a;
    }
    function additive() {
      let a = term();
      while (isOp("+") || isOp("-")) { const op = toks[p++].v; a = { k: "bin", op, a, b: term() }; }
      return a;
    }
    function term() {
      let a = power();
      while (isOp("*") || isOp("/")) { const op = toks[p++].v; a = { k: "bin", op, a, b: power() }; }
      return a;
    }
    // Excel's rules: a leading minus binds tighter than ^ (so -2^2 is 4) and ^ chains left to right (2^3^2 is 64)
    function power() {
      let a = unary();
      while (isOp("^")) { p++; a = { k: "bin", op: "^", a, b: unary() }; }
      return a;
    }
    function unary() {
      enter();
      let r;
      if (isOp("-") || isOp("+")) { const op = toks[p++].v; r = { k: "un", op, a: unary() }; }
      else r = primary();
      leave();
      return r;
    }
    function primary() {
      const t = toks[p++];
      if (!t) fail(E.ERR);
      switch (t.t) {
        case "num": return { k: "num", v: t.v };
        case "str": return { k: "str", v: t.v };
        case "bool": return { k: "bool", v: t.v };
        case "err": return { k: "err", v: t.v };
        case "ref": return t.sh === undefined ? { k: "ref", r: t.r, c: t.c } : { k: "ref", r: t.r, c: t.c, sh: t.sh };
        case "range": {
          const nd = { k: "range", r0: Math.min(t.a.r, t.b.r), c0: Math.min(t.a.c, t.b.c), r1: Math.max(t.a.r, t.b.r), c1: Math.max(t.a.c, t.b.c) };
          if (t.sh !== undefined) nd.sh = t.sh;
          return nd;
        }
        case "name": return { k: "name", v: t.v };
        case "fn": {
          if (!isOp("(")) fail(E.ERR);
          p++;
          const args = [];
          if (isOp(")")) { p++; return { k: "call", name: t.v, args }; }
          for (;;) {
            args.push(expr());
            if (isOp(",")) { p++; continue; }
            if (isOp(")")) { p++; break; }
            fail(E.ERR);
          }
          return { k: "call", name: t.v, args };
        }
        case "op":
          if (t.v === "(") { const e = expr(); if (!isOp(")")) fail(E.ERR); p++; return e; }
          fail(E.ERR);
      }
      fail(E.ERR);
    }
    const tree = expr();
    if (p < toks.length) fail(E.ERR);                                 // leftovers, e.g. "1 2"
    return tree;
  }

  const AST_CACHE = new Map();
  function parseCached(src) {
    let t = AST_CACHE.get(src);
    if (t === undefined) {
      try { t = parse(src); } catch (e) { t = e instanceof FErr ? e : new FErr(E.ERR); }
      if (AST_CACHE.size > 4000) AST_CACHE.clear();
      AST_CACHE.set(src, t);
    }
    if (t instanceof FErr) throw t;
    return t;
  }

  // ---- values ---------------------------------------------------------------------------------------------------
  const NUM_RE = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;
  const isNumLike = (v) => typeof v === "number" ? isFinite(v) : (typeof v === "string" && NUM_RE.test(v.trim()));
  function fmtNum(n) {                                                // 0.1+0.2 → 0.3, 1e21 stays readable
    if (!isFinite(n)) return String(n);
    if (Number.isInteger(n)) return String(n);
    return String(Number(n.toPrecision(12)));
  }
  function toNum(v) {
    if (v === null || v === undefined) return 0;
    if (typeof v === "number") return v;
    if (typeof v === "boolean") return v ? 1 : 0;
    if (typeof v === "string" && NUM_RE.test(v.trim())) return Number(v.trim());
    return fail(E.VALUE);
  }
  function toStr(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "number") return fmtNum(v);
    if (typeof v === "boolean") return v ? "TRUE" : "FALSE";
    return String(v);
  }
  function toBool(v) {
    if (typeof v === "boolean") return v;
    if (v === null || v === undefined) return false;
    if (typeof v === "number") return v !== 0;
    const s = String(v).trim().toUpperCase();
    if (s === "TRUE") return true;
    if (s === "FALSE") return false;
    if (NUM_RE.test(s)) return Number(s) !== 0;
    return fail(E.VALUE);
  }
  function compare(a, b) {                                            // -1 / 0 / 1; numbers by value, else text (case-insensitive)
    if (a === null || a === undefined) a = (typeof b === "string" && !isNumLike(b)) ? "" : 0;
    if (b === null || b === undefined) b = (typeof a === "string" && !isNumLike(a)) ? "" : 0;
    if (typeof a === "boolean" && typeof b === "boolean") return a === b ? 0 : (a ? 1 : -1);
    if (isNumLike(a) && isNumLike(b)) { const x = toNum(a), y = toNum(b); return x < y ? -1 : x > y ? 1 : 0; }
    const x = toStr(a).toLowerCase(), y = toStr(b).toLowerCase();
    return x < y ? -1 : x > y ? 1 : 0;
  }
  function round(x, d) {
    d = Math.trunc(d);
    if (d > 15 || d < -15) fail(E.ERR);
    const sign = x < 0 ? -1 : 1;
    const a = Math.abs(x);
    const r = Number(Math.round(Number(a + "e" + d)) + "e" + (-d));
    return isFinite(r) ? sign * r : fail(E.ERR);
  }

  // ---- evaluation -------------------------------------------------------------------------------------------------
  // ctx = { cell(r, c) → value | FErr, rows, cols, today() }
  function evalNode(n, ctx, depth) {
    if (depth > LIMITS.maxDepth * 4) fail(E.ERR);
    switch (n.k) {
      case "num": case "str": case "bool": return n.v;
      case "err": return fail(n.v);
      case "name": return fail(E.NAME);
      case "ref": return refValue(n, ctx);
      case "range": return fail(E.VALUE);                              // a range only makes sense inside a function
      case "un": { const v = toNum(evalNode(n.a, ctx, depth + 1)); return n.op === "-" ? -v : v; }
      case "bin": return binary(n, ctx, depth);
      case "call": return call(n, ctx, depth);
    }
    return fail(E.ERR);
  }
  // the sheet a ref/range points at: this one, or another through the host's resolver (unknown name → #REF!)
  function targetCtx(n, ctx) {
    if (n.sh === undefined) return ctx;
    const t = typeof ctx.sheet === "function" ? ctx.sheet(n.sh) : null;
    return t ? t : fail(E.REF);
  }
  function refValue(n, ctx) {
    const t = targetCtx(n, ctx);
    if (n.r < 0 || n.c < 0 || n.r >= t.rows() || n.c >= t.cols()) fail(E.REF);
    const v = t.cell(n.r, n.c);
    if (v instanceof FErr) throw v;
    return v === undefined ? null : v;
  }
  function binary(n, ctx, depth) {
    const a = evalNode(n.a, ctx, depth + 1);
    const b = evalNode(n.b, ctx, depth + 1);
    switch (n.op) {
      case "+": return finite(toNum(a) + toNum(b));
      case "-": return finite(toNum(a) - toNum(b));
      case "*": return finite(toNum(a) * toNum(b));
      case "/": { const d = toNum(b); if (d === 0) fail(E.DIV); return finite(toNum(a) / d); }
      case "^": return finite(Math.pow(toNum(a), toNum(b)));
      case "&": return toStr(a) + toStr(b);
      case "=": return compare(a, b) === 0;
      case "<>": return compare(a, b) !== 0;
      case "<": return compare(a, b) < 0;
      case ">": return compare(a, b) > 0;
      case "<=": return compare(a, b) <= 0;
      case ">=": return compare(a, b) >= 0;
    }
    return fail(E.ERR);
  }
  const finite = (x) => (isFinite(x) ? x : fail(E.ERR));

  // arguments of aggregate functions: scalars directly, ranges cell by cell (clamped to the sheet)
  function forEachArg(args, ctx, depth, onValue, inRange) {
    for (const a of args) {
      if (a.k === "range") {
        const t = targetCtx(a, ctx);
        const r1 = Math.min(a.r1, t.rows() - 1), c1 = Math.min(a.c1, t.cols() - 1);
        if (a.r0 > r1 || a.c0 > c1) continue;                         // entirely outside the sheet: empty
        if ((r1 - a.r0 + 1) * (c1 - a.c0 + 1) > LIMITS.maxRangeCells) fail(E.ERR);
        for (let r = a.r0; r <= r1; r++) {
          for (let c = a.c0; c <= c1; c++) {
            const v = t.cell(r, c);
            if (v instanceof FErr) throw v;
            onValue(v === undefined ? null : v, true);
          }
        }
      } else {
        onValue(evalNode(a, ctx, depth + 1), false);
      }
    }
  }
  function numbersOf(args, ctx, depth) {
    const nums = [];
    forEachArg(args, ctx, depth, (v, fromRange) => {
      if (fromRange) { if (isNumLike(v)) nums.push(toNum(v)); }       // text/blank/booleans in a range are skipped
      else nums.push(toNum(v));                                        // a typed-in argument must be a number
    });
    return nums;
  }
  const arity = (args, min, max) => { if (args.length < min || args.length > max) fail(E.ERR); };

  const FUNCS = Object.create(null);
  FUNCS.SUM = (a, x, d) => { let s = 0; for (const v of numbersOf(a, x, d)) s += v; return finite(s); };
  FUNCS.AVERAGE = (a, x, d) => { const v = numbersOf(a, x, d); if (!v.length) fail(E.DIV); return finite(v.reduce((s, y) => s + y, 0) / v.length); };
  FUNCS.MIN = (a, x, d) => { const v = numbersOf(a, x, d); return v.length ? v.reduce((m, y) => Math.min(m, y), Infinity) : 0; };
  FUNCS.MAX = (a, x, d) => { const v = numbersOf(a, x, d); return v.length ? v.reduce((m, y) => Math.max(m, y), -Infinity) : 0; };
  FUNCS.COUNT = (a, x, d) => {
    let n = 0;
    forEachArg(a, x, d, (v) => { if (isNumLike(v) || (typeof v === "number")) n++; });
    return n;
  };
  FUNCS.IF = (a, x, d) => {                                            // lazy: only the chosen branch is evaluated
    arity(a, 2, 3);
    const cond = toBool(evalNode(a[0], x, d + 1));
    if (cond) return evalNode(a[1], x, d + 1);
    return a.length === 3 ? evalNode(a[2], x, d + 1) : false;
  };
  FUNCS.ROUND = (a, x, d) => { arity(a, 1, 2); return round(toNum(evalNode(a[0], x, d + 1)), a.length === 2 ? toNum(evalNode(a[1], x, d + 1)) : 0); };
  FUNCS.CONCAT = (a, x, d) => { let s = ""; forEachArg(a, x, d, (v) => { s += toStr(v); if (s.length > 100000) fail(E.ERR); }); return s; };
  FUNCS.LEN = (a, x, d) => { arity(a, 1, 1); return toStr(evalNode(a[0], x, d + 1)).length; };
  FUNCS.UPPER = (a, x, d) => { arity(a, 1, 1); return toStr(evalNode(a[0], x, d + 1)).toUpperCase(); };
  FUNCS.LOWER = (a, x, d) => { arity(a, 1, 1); return toStr(evalNode(a[0], x, d + 1)).toLowerCase(); };
  FUNCS.TRIM = (a, x, d) => { arity(a, 1, 1); return toStr(evalNode(a[0], x, d + 1)).trim().replace(/\s+/g, " "); };
  FUNCS.ABS = (a, x, d) => { arity(a, 1, 1); return Math.abs(toNum(evalNode(a[0], x, d + 1))); };
  FUNCS.TODAY = (a, x) => { arity(a, 0, 0); return x.today ? x.today() : isoToday(); };
  function isoToday() {
    const t = new Date();
    const p = (n) => (n < 10 ? "0" : "") + n;
    return t.getFullYear() + "-" + p(t.getMonth() + 1) + "-" + p(t.getDate());
  }
  function call(n, ctx, depth) {
    const f = Object.prototype.hasOwnProperty.call(FUNCS, n.name) ? FUNCS[n.name] : null;   // own property only: no __proto__/constructor
    if (!f) fail(E.NAME);
    return f(n.args, ctx, depth);
  }

  /** evaluate("A1+2", ctx) → value or FErr. Never throws. */
  function evaluate(src, ctx) {
    try {
      return evalNode(parseCached(src), ctx, 0);
    } catch (e) {
      if (e instanceof FErr) return e;
      return new FErr(E.ERR);                                          // RangeError (stack), anything unexpected
    }
  }

  // ---- a sheet's worth of formulas: cache + circular-reference detection ------------------------------------------
  const isFormula = (raw) => typeof raw === "string" && raw.length > 1 && raw.charCodeAt(0) === 61;
  /** opts: {getRaw(r,c), rows(), cols(), today?()}. valueAt(r,c) is the displayed/saved value; clear() after any edit.
   *  Workbook use (several sheets): every sheet's evaluator gets the SAME opts.shared = {visiting: Set, depth: 0} (so a cycle that runs
   *  through two sheets is #CIRC!, not an endless walk), its own numeric opts.id, and opts.sheet(name) → {rows, cols, cell(r,c)} | null
   *  to reach the others (the host looks the name up in a Map; null = no such sheet = #REF!). */
  function createEvaluator(opts) {
    const cache = new Map();
    const shared = opts.shared || { visiting: new Set(), depth: 0 };
    const visiting = shared.visiting;
    const KEY = 20000;                                                 // > maxCols of any sheet we open
    const base = (opts.id || 0) * 1e10;                                // keeps keys of different sheets apart (ids stay far below 9e5)
    const ctx = {
      rows: opts.rows, cols: opts.cols, today: opts.today, sheet: opts.sheet,
      cell: (r, c) => valueAt(r, c),
    };
    function valueAt(r, c) {
      const raw = opts.getRaw(r, c);
      if (!isFormula(raw)) return raw === undefined ? null : raw;
      const key = base + r * KEY + c;
      if (cache.has(key)) return cache.get(key);
      if (visiting.has(key)) return new FErr(E.CIRC);
      if (shared.depth > LIMITS.maxEvalDepth) return new FErr(E.ERR); // a very long chain of formulas
      visiting.add(key);
      shared.depth++;
      let v;
      try { v = evaluate(raw.slice(1), ctx); } finally { shared.depth--; visiting.delete(key); }
      cache.set(key, v);
      return v;
    }
    return { valueAt, clear: () => cache.clear() };
  }

  /** Move the relative refs of a formula by (dr, dc) — what fill-down / fill-right do. $-anchored parts stay. */
  function shift(raw, dr, dc) {
    if (!isFormula(raw)) return raw;
    let toks;
    try { toks = tokenize(raw.slice(1)); } catch (e) { return raw; }
    const src = raw.slice(1);
    const fmt = (t, r, c) => {
      if (r < 0 || c < 0) return null;
      return (t.ac ? "$" : "") + colToLetters(c) + (t.ar ? "$" : "") + (r + 1);
    };
    let out = "", at = 0;
    for (const t of toks) {
      if (t.t !== "ref" && t.t !== "range") continue;
      out += src.slice(at, t.s);
      at = t.e;
      const pre = t.sh === undefined ? "" : src.slice(t.s, t.pe);   // "Sheet2!" / "'My sheet'!" stays exactly as typed
      if (t.t === "ref") {
        const g = fmt(t, t.ar ? t.r : t.r + dr, t.ac ? t.c : t.c + dc);
        out += g ? pre + g : "#REF!";
      } else {
        const a = fmt(t.a, t.a.ar ? t.a.r : t.a.r + dr, t.a.ac ? t.a.c : t.a.c + dc);
        const b = fmt(t.b, t.b.ar ? t.b.r : t.b.r + dr, t.b.ac ? t.b.c : t.b.c + dc);
        out += a && b ? pre + a + ":" + b : "#REF!";
      }
    }
    return "=" + out + src.slice(at);
  }

  // ---- sheet names inside formulas: quoting, renaming, deleting --------------------------------------------------
  const BARE_SHEET = /^[A-Za-z_][A-Za-z0-9_.]*$/;
  /** How a sheet name is written in a formula: bare when it can be, else 'quoted' with ' doubled. */
  function quoteSheet(name) { return BARE_SHEET.test(name) ? name : "'" + String(name).replace(/'/g, "''") + "'"; }
  const sameSheet = (a, b) => String(a).toLowerCase() === String(b).toLowerCase();
  /** Rewrite every ref/range that points at sheet `oldName` so it points at `newName` (null → #REF!, the sheet was deleted).
   *  Text that is not a formula, or doesn't parse, is returned untouched. */
  function retargetSheet(raw, oldName, newName) {
    if (!isFormula(raw) || raw.indexOf("!") < 0) return raw;
    let toks;
    try { toks = tokenize(raw.slice(1)); } catch (e) { return raw; }
    const src = raw.slice(1);
    let out = "", at = 0, hit = false;
    for (const t of toks) {
      if ((t.t !== "ref" && t.t !== "range") || t.sh === undefined || !sameSheet(t.sh, oldName)) continue;
      hit = true;
      out += src.slice(at, t.s);
      at = t.e;
      out += newName === null ? "#REF!" : quoteSheet(newName) + "!" + src.slice(t.pe, t.e);
    }
    return hit ? "=" + out + src.slice(at) : raw;
  }
  /** The sheet names a formula points at (for tests and for "does anything use this sheet"). */
  function sheetsUsed(raw) {
    const names = [];
    if (!isFormula(raw)) return names;
    try { for (const t of tokenize(raw.slice(1))) if (t.sh !== undefined && names.indexOf(t.sh) < 0) names.push(t.sh); } catch (e) { /* not a formula we can read */ }
    return names;
  }

  /** Syntax check only (for the formula bar's red outline while typing). Returns null or an error code. */
  function check(raw) {
    if (!isFormula(raw)) return null;
    try { parseCached(raw.slice(1)); return null; } catch (e) { return e instanceof FErr ? e.code : E.ERR; }
  }

  return { FErr, E, LIMITS, evaluate, createEvaluator, shift, check, isFormula, quoteSheet, retargetSheet, sheetsUsed, colToLetters, lettersToCol, fmtNum, isNumLike, toStr, compare };
});
