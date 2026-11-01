// Run by tests/unit/test_mini_sheet.py (node): the wrap line counter in mini-sheet/ui/wrap.js. Fake monospace font: 1 character = 7 px.
const path = require("path");
const W = require(path.join(__dirname, "..", "..", "mini-sheet", "ui", "wrap.js"));
const fails = [];
const m = (s) => s.length * 7;
const lines = (text, avail, cap) => W.countLines(text, avail, m, cap).lines;
function eq(label, got, want) { if (got !== want) fails.push(`${label}: expected ${want}, got ${got}`); }

// width 70 px = 10 characters per line
eq("empty is one line", lines("", 70), 1);
eq("null is one line", W.countLines(null, 70, m).lines, 1);
eq("fits", lines("abcdefghij", 70), 1);
eq("one over", lines("abcdefghijk", 70), 2);                      // a single 11-character word is cut: 10 + 1
eq("words wrap at spaces", lines("aaaa bbbb cccc", 70), 2);         // "aaaa bbbb" (9) + "cccc"
eq("words wrap again", lines("aaaa bbbb cccc dddd eeee", 70), 3);
eq("exactly full line then next word", lines("aaaaaaaaaa bbb", 70), 2);
eq("a very long word fills several lines", lines("x".repeat(95), 70), 10);
eq("a word of exactly three lines", lines("y".repeat(30), 70), 3);
eq("long word after short words", lines("ab " + "z".repeat(25), 70), 4);   // "ab" / zzzzzzzzzz / zzzzzzzzzz / zzzzz
eq("newlines are kept", lines("a\nb\nc", 70), 3);
eq("blank lines count", lines("a\n\nb", 70), 3);
eq("trailing newline", lines("a\n", 70), 2);
eq("newline plus wrapping", lines("aaaa bbbb cccc\nxx", 70), 3);
eq("windows line breaks", lines("a\r\nb", 70), 2);
eq("old mac line breaks", lines("a\rb", 70), 2);
eq("a single wide character in a tiny column", lines("W", 3), 1);   // can't be split further: still one line
eq("narrow column: one character per line", lines("abcd", 7), 4);
eq("zero width is treated as 1 px, never loops", lines("abc", 0), 3);
eq("negative width too", lines("abc", -50), 3);
eq("numbers are text too", W.countLines(12345678901, 70, m).lines, 2);
eq("double spaces do not break counting", lines("aa  bb  cc", 70), 1);
eq("many spaces in a row", lines("a" + " ".repeat(30) + "b", 70) >= 1, true);
// the cap
{ const r = W.countLines("x".repeat(100000), 70, m); eq("capped at 40", r.lines, 40); eq("capped is flagged", r.truncated, true); }
{ const r = W.countLines("a\n".repeat(100), 70, m); eq("many lines capped", r.lines, 40); eq("flagged", r.truncated, true); }
{ const r = W.countLines("a\n".repeat(10), 70, m, 5); eq("custom cap", r.lines, 5); eq("custom cap flagged", r.truncated, true); }
{ const r = W.countLines("x".repeat(30), 70, m); eq("just under the cap", r.truncated, false); }
{ const t0 = Date.now(); W.countLines("word ".repeat(200000), 70, m); eq("a huge text stops quickly", Date.now() - t0 < 1500, true); }
{ const t0 = Date.now(); W.countLines("x".repeat(2000000), 70, m); eq("a huge single word stops quickly", Date.now() - t0 < 1500, true); }
// the estimate (no measuring): average character width 7 px
eq("estimate empty", W.estimateLines("", 70, 7), 1);
eq("estimate short", W.estimateLines("abc", 70, 7), 1);
eq("estimate long", W.estimateLines("a".repeat(35), 70, 7), 4);
eq("estimate newlines", W.estimateLines("a\nb\nc", 70, 7), 3);
eq("estimate cap", W.estimateLines("a".repeat(100000), 70, 7), 40);
eq("estimate tiny width", W.estimateLines("abc", 0, 7), 3);
eq("estimate null", W.estimateLines(null, 70, 7), 1);
// row height: 1 line = the normal row, more lines grow it
eq("height 1 line", W.rowHeight(1, 17), 26);
eq("height 2 lines", W.rowHeight(2, 17), 43);
eq("height 5 lines", W.rowHeight(5, 17), 94);
eq("height 40 lines", W.rowHeight(40, 17), 689);
eq("height 0 lines", W.rowHeight(0, 17), 26);
// fitPrefix
eq("fitPrefix", W.fitPrefix("abcdefghijklmnop", 70, m), 10);
eq("fitPrefix at least one", W.fitPrefix("abc", 1, m), 1);

console.log(fails.length ? fails.join("\n") : "ALL OK");
process.exit(fails.length ? 1 : 0);
