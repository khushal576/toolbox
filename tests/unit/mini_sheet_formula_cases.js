// Run by tests/unit/test_mini_sheet.py (node). Prints one line per failed case and exits 1 if any failed.
const path = require("path");
const F = require(path.join(__dirname, "..", "..", "mini-sheet", "ui", "formula.js"));
const fails = [];
const show = (v) => (v instanceof F.FErr ? v.code : (v === null ? "null" : typeof v === "string" ? JSON.stringify(v) : String(v)));

function sheet(grid) {                       // grid[r][c] raw values; evaluates cell (r, c) of a fresh evaluator
  const nr = grid.length, nc = Math.max(...grid.map((r) => r.length));
  return F.createEvaluator({ getRaw: (r, c) => (grid[r] ? grid[r][c] : undefined), rows: () => nr, cols: () => nc, today: () => "2026-11-01" });
}
function ev(src, grid) {                     // evaluate a formula typed in an extra cell below the grid
  const g = (grid || [[1, 2, "x"], [3, "4", null]]).map((r) => r.slice());
  g.push(["=" + src]);
  return sheet(g).valueAt(g.length - 1, 0);
}
function eq(src, expected, grid) {
  const got = show(ev(src, grid));
  if (got !== expected) fails.push(`=${src.slice(0, 70)}  expected ${expected}  got ${got}`);
}

// ---- arithmetic, precedence, text, comparison
eq("1+2*3", "7"); eq("(1+2)*3", "9"); eq("2^3^2", "64"); eq("-2^2", "4"); eq("2^-1", "0.5"); eq("--3", "3"); eq("-(2+1)^2", "9"); eq("10/4", "2.5"); eq("7-2-1", "4");
eq("0.1+0.2", "0.30000000000000004");                           // the raw value; display rounds via fmtNum
eq('"a"&"b"&1', '"ab1"'); eq('1&2', '"12"'); eq("1=1", "true"); eq("1<>1", "false"); eq('"a"<"B"', "true"); eq("2>=2", "true"); eq("3<2", "false");
eq('"abc"="ABC"', "true"); eq("TRUE", "true"); eq("true+1", "2");
eq("A1+B1", "3"); eq("A2+B2", "7");                             // "4" is numeric text and counts as a number
eq("C1+1", "#VALUE!"); eq("D9", "#REF!"); eq("A1+Z1", "#REF!");
eq("1/0", "#DIV/0!"); eq("A1/(B1-2)", "#DIV/0!");
// ---- functions
eq("SUM(A1:B2)", "10"); eq("SUM(A1,B1,10)", "13"); eq("SUM(A1:C2)", "10"); eq('SUM(1,"x")', "#VALUE!");
eq("AVERAGE(A1:B2)", "2.5"); eq("AVERAGE(C1:C2)", "#DIV/0!"); eq("MIN(A1:B2)", "1"); eq("MAX(A1:B2)", "4"); eq("MIN(C1:C2)", "0");
eq("COUNT(A1:C2)", "4"); eq("COUNT(1,2,3)", "3");
eq("IF(A1=1,\"yes\",\"no\")", '"yes"'); eq("IF(A1=2,\"yes\",\"no\")", '"no"'); eq("IF(FALSE,1)", "false");
eq("IF(TRUE,1,1/0)", "1"); eq("IF(FALSE,1/0,2)", "2");          // only the chosen branch runs
eq("ROUND(2.5)", "3"); eq("ROUND(-2.5)", "-3"); eq("ROUND(1.2345,2)", "1.23"); eq("ROUND(1234.5,-2)", "1200"); eq("ROUND(2.675,2)", "2.68");
eq('CONCAT("a",1,TRUE)', '"a1TRUE"'); eq("CONCAT(A1:B1)", '"12"');
eq('LEN("héllo")', "5"); eq("LEN(12.5)", "4"); eq('UPPER("aB")', '"AB"'); eq('LOWER("aB")', '"ab"'); eq('TRIM("  a   b ")', '"a b"');
eq("ABS(-3)", "3"); eq("TODAY()", '"2026-11-01"'); eq("sum(a1:b1)", "3");
eq("SUM(1,2", "#ERR!"); eq("SUM()", "0"); eq("ROUND()", "#ERR!"); eq("IF(1)", "#ERR!"); eq("LEN(1,2)", "#ERR!");
eq("NOPE(1)", "#NAME?"); eq("foo", "#NAME?"); eq("A1:B2", "#VALUE!");
// ---- syntax errors
for (const s of ["1 2", "1+", "*2", "(", ")", "1,2", '"abc', "A1:", ":A1", "1..2", "12abc", "a;b", "[1]", "{1}", "A1!", "'x'", "`x`", "1 % 2", "@A1", "A1 B1"]) eq(s, "#ERR!");
// ---- injection / hostile input: never code, always an error value, prototype untouched
const hostile = ["__proto__", "constructor", "prototype", "toString", "hasOwnProperty", "constructor(1)", "constructor.constructor('return 1')()", "alert(1)", "window", "globalThis",
  "this", "process", "require('fs')", "eval('1')", "Function('return 1')()", "(function(){return 1})()", "()=>1", "a=>a", "1;2", "${1}", "`${1}`", "SUM(__proto__)", "IF(constructor,1,2)",
  "A1.constructor", "A1['constructor']", "[].constructor", "new Date()", "import('x')", "while(1){}", "x=1", "1==1", "!1", "~1", "1<<2", "A1\\u0020"];
for (const h of hostile) { const v = ev(h); if (!(v instanceof F.FErr)) fails.push(`hostile =${h} was accepted: ${show(v)}`); }
if (typeof Object.prototype.polluted !== "undefined" || ({}).constructor !== Object) fails.push("prototype was touched");
eq("A1".repeat(400), "#ERR!");                                  // longer than the 1000-character limit once repeated 400 times? ("A1"*400 = 800 chars -> a bad token)
{ const long = "1" + "+1".repeat(600); eq(long, "#ERR!"); }     // > 600 tokens
{ const deep = "(".repeat(300) + "1" + ")".repeat(300); eq(deep, "#ERR!"); }
{ let nest = "1"; for (let i = 0; i < 100; i++) nest = "-(" + nest + ")"; eq(nest, "#ERR!"); }
{ let ifs = "1"; for (let i = 0; i < 100; i++) ifs = "IF(TRUE," + ifs + ",0)"; eq(ifs, "#ERR!"); }
eq("SUM(A1:ZZZ99999999)", "#ERR!");                              // a row number with 8 digits isn't a cell reference
{ // a range is clamped to the sheet, so a mad one costs no more than the sheet is big
  const small = F.evaluate("SUM(A1:ZZZ9999999)", { cell: () => 1, rows: () => 2, cols: () => 3 });
  if (show(small) !== "6") fails.push("clamped range: " + show(small));
  // ...and one that is still too big once clamped is refused up front (no multi-million-cell loop)
  const t0 = Date.now();
  const g = F.evaluate("SUM(A1:ZZZ9999999)", { cell: () => 1, rows: () => 3000, cols: () => 3000 });
  if (!(g instanceof F.FErr) || Date.now() - t0 > 1000) fails.push("huge range not refused quickly: " + show(g) + " " + (Date.now() - t0) + "ms");
}
// ---- cycles and chains
{
  const g = [["=B1", "=A1"], ["=A2", "=A2+1"], ["=C3", 5, 7]];
  const e = sheet(g);
  const out = [e.valueAt(0, 0), e.valueAt(0, 1), e.valueAt(1, 0), e.valueAt(1, 1)].map(show).join(",");
  if (out !== "#CIRC!,#CIRC!,#CIRC!,#CIRC!") fails.push("cycle detection: " + out);
  const ok = sheet([[1, "=A1+1", "=B1*2"]]); if (show(ok.valueAt(0, 2)) !== "4") fails.push("chain A1→B1→C1");
}
{ // a 5,000-long chain of formulas is an error value, never a crash
  const n = 5000, g = []; for (let i = 0; i < n; i++) g.push([i === 0 ? 1 : "=A" + i + "+1"]);
  const v = sheet(g).valueAt(n - 1, 0); if (!(v instanceof F.FErr) && v !== n) fails.push("long chain: " + show(v));
}
{ // edits: clear() drops the cache
  const grid = [[1, "=A1*2"]]; const e = sheet(grid);
  if (e.valueAt(0, 1) !== 2) fails.push("first value"); grid[0][0] = 5; if (e.valueAt(0, 1) !== 2) fails.push("cache should still hold"); e.clear(); if (e.valueAt(0, 1) !== 10) fails.push("after clear");
}

// ---- several sheets: Sheet2!A1, 'My sheet'!A1:B9, rename, delete, cross-sheet cycles, hostile names
function workbook(defs) {                    // defs: {name: grid}; returns {valueAt(sheetName, r, c), ev: {name: evaluator}, grids}
  const shared = { visiting: new Set(), depth: 0 }, evs = new Map(), by = new Map();
  let id = 1;
  for (const name of Object.keys(defs)) by.set(name.toLowerCase(), { name, grid: defs[name], id: id++ });
  for (const sh of by.values()) {
    const g = sh.grid, nc = Math.max(1, ...g.map((r) => r.length));
    sh.ev = F.createEvaluator({
      id: sh.id, shared, getRaw: (r, c) => (g[r] ? g[r][c] : undefined), rows: () => g.length, cols: () => nc, today: () => "2026-11-01",
      sheet: (n) => { const t = by.get(String(n).toLowerCase()); return t ? { rows: () => t.grid.length, cols: () => Math.max(1, ...t.grid.map((r) => r.length)), cell: (r, c) => t.ev.valueAt(r, c) } : null; },
    });
  }
  return { by, valueAt: (name, r, c) => by.get(name.toLowerCase()).ev.valueAt(r, c) };
}
function wbEq(label, defs, name, r, c, expected) {
  const got = show(workbook(defs).valueAt(name, r, c));
  if (got !== expected) fails.push(`${label}: expected ${expected} got ${got}`);
}
wbEq("cross ref", { Data: [[5, 7]], Calc: [["=Data!A1+Data!B1"]] }, "Calc", 0, 0, "12");
wbEq("case-insensitive sheet", { Data: [[5]], Calc: [["=data!A1*2"]] }, "Calc", 0, 0, "10");
wbEq("quoted name", { "My sheet": [[1, 2], [3, 4]], Calc: [["=SUM('My sheet'!A1:B2)"]] }, "Calc", 0, 0, "10");
wbEq("quote inside a name", { "Bob's": [[9]], Calc: [["='Bob''s'!A1"]] }, "Calc", 0, 0, "9");
wbEq("anchored cross ref", { D: [[4]], C: [["=D!$A$1+1"]] }, "C", 0, 0, "5");
wbEq("range in another sheet", { D: [[1], [2], [3]], C: [["=AVERAGE(D!A1:A3)"]] }, "C", 0, 0, "2");
wbEq("unknown sheet is #REF!", { C: [["=Nope!A1"]] }, "C", 0, 0, "#REF!");
wbEq("unknown sheet range is #REF!", { C: [["=SUM(Nope!A1:B2)"]] }, "C", 0, 0, "#REF!");
wbEq("ref outside the other sheet", { D: [[1]], C: [["=D!Z99"]] }, "C", 0, 0, "#REF!");
wbEq("formula in the other sheet", { D: [[2, "=A1*10"]], C: [["=D!B1"]] }, "C", 0, 0, "20");
wbEq("two-sheet cycle", { A: [["=B!A1"]], B: [["=A!A1"]] }, "A", 0, 0, "#CIRC!");
wbEq("self cycle through another sheet", { A: [["=B!A1+1"]], B: [["=A!A1+1"]] }, "B", 0, 0, "#CIRC!");
wbEq("three-sheet cycle", { A: [["=B!A1"]], B: [["=C!A1"]], C: [["=A!A1"]] }, "C", 0, 0, "#CIRC!");
wbEq("an error travels across sheets", { D: [["=1/0"]], C: [["=D!A1+1"]] }, "C", 0, 0, "#DIV/0!");
wbEq("a same-sheet ref still works", { D: [[1, "=A1+1"]], C: [[3, "=A1+D!B1"]] }, "C", 0, 1, "5");
for (const hn of ["__proto__", "constructor", "prototype", "toString", "hasOwnProperty", "valueOf"]) {
  wbEq("hostile sheet name " + hn, { D: [[1]], C: [["=" + hn + "!A1"]] }, "C", 0, 0, "#REF!");
  wbEq("hostile quoted sheet name " + hn, { D: [[1]], C: [["='" + hn + "'!A1"]] }, "C", 0, 0, "#REF!");
  wbEq("hostile sheet range " + hn, { D: [[1]], C: [["=SUM(" + hn + "!A1:B2)"]] }, "C", 0, 0, "#REF!");
}
for (const bad of ["Sheet1!", "!A1", "Sheet1!A", "Sheet1!1", "'x'!", "''!A1", "Sheet1!A1:", "Sheet1!A1:Sheet1", "'unterminated!A1", "Sheet 2!A1", "Sheet1!!A1", "a!b!c", "Sheet1![A1]", "'" + "x".repeat(70) + "'!A1"]) eq(bad, "#ERR!");
{ // names that look like cells or booleans are still just names
  wbEq("sheet named A1", { A1: [[6]], C: [["=A1!A1"]] }, "C", 0, 0, "6");
  wbEq("sheet named TRUE", { TRUE: [[8]], C: [["=TRUE!A1"]] }, "C", 0, 0, "8");
}
// rename / delete rewrite
const rt = [["=Data!A1+1", "Data", "Info", "=Info!A1+1"], ["=SUM(Data!A1:B2)", "data", "Q1 2026", "=SUM('Q1 2026'!A1:B2)"], ["='My sheet'!A1", "My sheet", "Plain", "=Plain!A1"],
  ["=Data!A1&\"Data!A1\"", "Data", "X", '=X!A1&"Data!A1"'], ["=Other!A1", "Data", "X", "=Other!A1"], ["=A1+1", "Data", "X", "=A1+1"], ["text Data!A1", "Data", "X", "text Data!A1"],
  ["=Data!A1+Data!$B$2+'Data'!C3", "Data", "Bob's", "='Bob''s'!A1+'Bob''s'!$B$2+'Bob''s'!C3"], ["=Data!A1+", "Data", "X", "=X!A1+"], ["=IF(Data!A1>0,Data!B1,0)", "Data", "D2", "=IF(D2!A1>0,D2!B1,0)"]];
for (const [src, o, n, want] of rt) { const got = F.retargetSheet(src, o, n); if (got !== want) fails.push(`retargetSheet(${src}, ${o} → ${n}) = ${got}, wanted ${want}`); }
const dl = [["=Data!A1+1", "Data", "=#REF!+1"], ["=SUM(Data!A1:B2)", "Data", "=SUM(#REF!)"], ["=Other!A1+Data!B2", "data", "=Other!A1+#REF!"], ["=A1", "Data", "=A1"]];
for (const [src, o, want] of dl) { const got = F.retargetSheet(src, o, null); if (got !== want) fails.push(`delete sheet ${o} in ${src} = ${got}, wanted ${want}`); }
{ const deleted = workbook({ C: [["=1+#REF!"]] }).valueAt("C", 0, 0); if (show(deleted) !== "#REF!") fails.push("a deleted-sheet ref should evaluate to #REF!, got " + show(deleted)); }
if (F.quoteSheet("Data") !== "Data" || F.quoteSheet("My sheet") !== "'My sheet'" || F.quoteSheet("Bob's") !== "'Bob''s'" || F.quoteSheet("2026") !== "'2026'" || F.quoteSheet("a.b") !== "a.b") fails.push("quoteSheet");
if (JSON.stringify(F.sheetsUsed("=Data!A1+'My sheet'!B2+Data!C3")) !== JSON.stringify(["Data", "My sheet"]) || F.sheetsUsed("=A1").length || F.sheetsUsed("x").length) fails.push("sheetsUsed");
// shift keeps the prefix and still anchors
for (const [src, dr, dc, want] of [["=Data!A1+1", 1, 0, "=Data!A2+1"], ["='My sheet'!A1:B2", 0, 1, "='My sheet'!B1:C2"], ["=Data!$A$1+Data!A$1", 2, 2, "=Data!$A$1+Data!C$1"], ["=Data!A1", -1, 0, "=#REF!"]]) {
  const got = F.shift(src, dr, dc); if (got !== want) fails.push(`shift(${src}, ${dr}, ${dc}) = ${got}, wanted ${want}`);
}
if (F.check("=Sheet2!A1") !== null || F.check("='My sheet'!A1:B2") !== null || F.check("=Sheet2!") !== "#ERR!") fails.push("check() with sheet refs");
{ // a long chain that hops between two sheets is an error value, never a crash
  const n = 3000, a = [], b = []; for (let i = 0; i < n; i++) { a.push([i === 0 ? 1 : "=B!A" + i + "+1"]); b.push(["=A!A" + (i + 1) + "+1"]); }
  const v = workbook({ A: a, B: b }).valueAt("A", n - 1, 0); if (!(v instanceof F.FErr)) fails.push("cross-sheet long chain: " + show(v));
}
// the old single-sheet evaluator API still works without any sheet resolver
{ const e = F.createEvaluator({ getRaw: (r, c) => (r === 0 && c === 0 ? "=Other!A1" : undefined), rows: () => 1, cols: () => 1 }); if (show(e.valueAt(0, 0)) !== "#REF!") fails.push("no resolver → #REF!"); }
// ---- helpers
if (F.colToLetters(0) !== "A" || F.colToLetters(25) !== "Z" || F.colToLetters(26) !== "AA" || F.colToLetters(701) !== "ZZ" || F.colToLetters(702) !== "AAA") fails.push("colToLetters");
for (const n of [0, 1, 25, 26, 27, 51, 52, 701, 702, 16383]) if (F.lettersToCol(F.colToLetters(n)) !== n) fails.push("letters round trip " + n);
const shifts = [["=A1+B2", 1, 1, "=B2+C3"], ["=$A$1+B2", 2, 0, "=$A$1+B4"], ["=A$1+$B2", 3, 3, "=D$1+$B5"], ["=SUM(A1:B2)", 1, 0, "=SUM(A2:B3)"], ["=A1", -1, 0, "=#REF!"],
  ['="A1"&A1', 0, 1, '="A1"&B1'], ["=1+2", 5, 5, "=1+2"], ["plain", 1, 1, "plain"], ["=SUM(A1:B2)", -1, 0, "=SUM(#REF!)"], ["=IF(A1>0, B1, 0)", 1, 0, "=IF(A2>0, B2, 0)"]];
for (const [src, dr, dc, want] of shifts) { const got = F.shift(src, dr, dc); if (got !== want) fails.push(`shift(${src}, ${dr}, ${dc}) = ${got}, wanted ${want}`); }
if (F.check("=1+") !== "#ERR!" || F.check("=1+1") !== null || F.check("text") !== null || F.check("=NOPE(1)") !== null) fails.push("check()");
if (F.fmtNum(0.1 + 0.2) !== "0.3" || F.fmtNum(5) !== "5" || F.fmtNum(1 / 3) !== "0.333333333333") fails.push("fmtNum " + F.fmtNum(0.1 + 0.2));
if (!F.isFormula("=1") || F.isFormula("=") || F.isFormula("x=1") || F.isFormula(5)) fails.push("isFormula");

console.log(fails.length ? fails.join("\n") : "ALL OK");
process.exit(fails.length ? 1 : 0);
