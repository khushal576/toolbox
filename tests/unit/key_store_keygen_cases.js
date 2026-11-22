// Key Store (roadmap KS1): the generator logic, run by node from tests/unit/test_key_store.py.
// Prints "OK <n> checks" and exits 0, or the failing check and exits 1.
const path = require("path");
const fs = require("fs");
const G = require(path.join(__dirname, "..", "..", "key-store", "ui", "keygen.js"));

let n = 0;
function check(cond, msg) { n++; if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function throws(fn, re, msg) { n++; try { fn(); } catch (e) { if (re.test(e.message)) return; console.error("FAIL: " + msg + " (wrong message: " + e.message + ")"); process.exit(1); } console.error("FAIL: " + msg + " (did not throw)"); process.exit(1); }

// ---- randInt: uniform, in range, and it really rejects the biased values ----------------------------------------------
{
  const counts = new Array(7).fill(0), N = 70000;
  for (let i = 0; i < N; i++) { const v = G.randInt(7); check(v >= 0 && v < 7, "randInt out of range"); counts[v]++; }
  const expected = N / 7, sd = Math.sqrt(N * (1 / 7) * (6 / 7));
  counts.forEach((c, i) => check(Math.abs(c - expected) < 6 * sd, "randInt looks biased at " + i + ": " + counts));
  check(G.randInt(1) === 0, "randInt(1) must be 0");
  throws(() => G.randInt(0), /whole number/, "randInt(0) must refuse");
  throws(() => G.randInt(1.5), /whole number/, "randInt(1.5) must refuse");
  // n = 3: limit = floor(2^32/3)*3 = 4294967295. The value 4294967295 must be thrown away, then 7 is used (7 % 3 = 1).
  const feed = [4294967295, 7];
  const rng = { getRandomValues(buf) { buf[0] = feed.shift(); return buf; } };
  check(G.randInt(3, rng) === 1 && feed.length === 0, "randInt must reject values in the biased tail");
}

// ---- password ---------------------------------------------------------------------------------------------------------
{
  const r = G.password({ length: 24 });
  check(r.value.length === 24, "default length");
  check(Math.abs(r.bits - 24 * Math.log2(r.poolSize)) < 1e-9, "password entropy formula");
  for (let i = 0; i < 400; i++) {                                   // "include at least one of each kind", at the tightest length
    const p = G.password({ length: 4, requireEach: true }).value;
    check(/[a-z]/.test(p) && /[A-Z]/.test(p) && /[0-9]/.test(p) && /[^a-zA-Z0-9]/.test(p), "requireEach violated: " + p);
  }
  for (let i = 0; i < 200; i++) {
    const p = G.password({ length: 60, noLookalikes: true }).value;
    check(!/[0O1lI|]/.test(p), "look-alike character present: " + p);
  }
  for (let i = 0; i < 200; i++) {
    const p = G.password({ length: 60, urlSafe: true }).value;
    check(/^[A-Za-z0-9\-_.~]+$/.test(p), "urlSafe produced an unsafe symbol: " + p);
  }
  for (let i = 0; i < 200; i++) {
    const p = G.password({ length: 60, exclude: "aeiou!@#" }).value;
    check(!/[aeiou!@#]/.test(p), "excluded character present: " + p);
  }
  check(/^[0-9]+$/.test(G.password({ length: 30, lower: false, upper: false, symbols: false }).value), "digits only");
  throws(() => G.password({ lower: false, upper: false, digits: false, symbols: false }), /at least one kind/, "no classes");
  throws(() => G.password({ length: 3, requireEach: true }), /too short/, "length below class count");
  throws(() => G.password({ length: 0 }), /Length/, "length 0");
  throws(() => G.password({ length: 9999 }), /Length/, "length too big");
  // symbols selected but every symbol excluded: the class disappears instead of crashing
  check(/^[a-zA-Z0-9]+$/.test(G.password({ length: 30, urlSafe: true, exclude: "-_.~" }).value), "class emptied by exclusions is dropped");
  const set = new Set(); for (let i = 0; i < 100; i++) set.add(G.password({ length: 20 }).value);
  check(set.size === 100, "passwords repeated");
}

// ---- passphrase -------------------------------------------------------------------------------------------------------
{
  const list = Array.from({ length: 7776 }, (_, i) => "word" + String.fromCharCode(97 + (i % 26)) + i);
  const r = G.passphrase({ words: 5, separator: "-" }, list);
  check(r.value.split("-").length === 5, "word count");
  check(Math.abs(r.bits - 5 * Math.log2(7776)) < 1e-9, "passphrase entropy");
  check(G.passphrase({ words: 4, separator: " ", capitalize: true }, list).value.split(" ").every((w) => /^[A-Z]/.test(w)), "capitalize");
  const n = G.passphrase({ words: 4, separator: "-", number: true }, list);
  check(/[0-9]{1,2}(?=-|$)/.test(n.value) && n.bits > 4 * Math.log2(7776), "number option adds entropy");
  throws(() => G.passphrase({ words: 5 }, ["a", "b"]), /word list/i, "short word list");
  throws(() => G.passphrase({ words: 1 }, list), /between 2 and 20/, "too few words");
}

// ---- the real EFF word list shipped with the tool -----------------------------------------------------------------------
{
  global.window = {};
  eval(fs.readFileSync(path.join(__dirname, "..", "..", "key-store", "ui", "words.js"), "utf8"));
  const w = window.KEYSTORE_WORDS;
  check(Array.isArray(w) && w.length === 7776, "words.js must hold the 7776 EFF words, has " + (w && w.length));
  check(new Set(w).size === 7776, "word list has duplicates");
  check(w.every((x) => /^[a-z-]+$/.test(x)), "unexpected character in a word");
  check(w[0] === "abacus" && w[7775] === "zoom", "word list order changed");
  const p = G.passphrase({ words: 6, separator: "-" }, w);
  check(p.value.split("-").length >= 6 && p.bits > 77, "passphrase from the real list");
}

// ---- PIN --------------------------------------------------------------------------------------------------------------
{
  let sawZero = false;
  for (let i = 0; i < 2000; i++) { const p = G.pin(6).value; check(/^[0-9]{6}$/.test(p), "pin format"); if (p[0] === "0") sawZero = true; }
  check(sawZero, "PIN never starts with 0 (a digit is being dropped)");
  check(Math.abs(G.pin(8).bits - 8 * Math.log2(10)) < 1e-9, "pin entropy");
  throws(() => G.pin(2), /3 to 32/, "tiny pin");
}

// ---- tokens -----------------------------------------------------------------------------------------------------------
{
  const hex = G.token({ kind: "hex", size: 32 });
  check(/^[0-9a-f]{64}$/.test(hex.value) && hex.bits === 256, "hex token");
  const b64 = G.token({ kind: "base64url", size: 32 });
  check(/^[A-Za-z0-9_-]{43}$/.test(b64.value) && b64.bits === 256, "base64url token (43 chars, no padding)");
  const al = G.token({ kind: "alnum", size: 40 });
  check(/^[A-Za-z0-9]{40}$/.test(al.value) && Math.abs(al.bits - 40 * Math.log2(62)) < 1e-9, "alnum token");
  check(G.token({ kind: "hex", size: 16, prefix: "sk_live_" }).value.startsWith("sk_live_"), "prefix");
  throws(() => G.token({ kind: "nope", size: 16 }), /Unknown token type/, "unknown kind");
  throws(() => G.token({ kind: "hex", size: 4 }), /between 8 and 256/, "tiny token");
}

// ---- uuid -------------------------------------------------------------------------------------------------------------
for (let i = 0; i < 200; i++) check(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(G.uuid().value), "uuid v4 format");

// ---- strength and time words ------------------------------------------------------------------------------------------
{
  check(G.strength(10).label === "Very weak" && G.strength(30).label === "Weak" && G.strength(50).label === "Fair", "strength labels low");
  check(G.strength(70).label === "Strong" && G.strength(90).label === "Very strong" && G.strength(128).label === "Excellent", "strength labels high");
  check(G.strength(20).tone === "bad" && G.strength(50).tone === "warn" && G.strength(70).tone === "good", "strength tones");
  check(G.humanTime(0.1) === "instantly" && G.humanTime(30) === "30 seconds" && G.humanTime(1) === "1 second", "humanTime seconds");
  check(G.humanTime(90) === "1 minute" && G.humanTime(3 * 3600) === "3 hours", "humanTime minutes/hours");
  check(G.humanTime(5 * 86400 * 365) === "5 years", "humanTime years");
  check(/thousand years/.test(G.humanTime(2000 * 365 * 86400)) && /million years/.test(G.humanTime(3e6 * 365 * 86400)), "humanTime big");
  check(G.humanTime(1e40) === "longer than the age of the universe" && G.humanTime(Infinity) === "longer than the age of the universe", "humanTime huge");
  check(G.crackSeconds(1) === 0.5 / 1e10 * 1 || Math.abs(G.crackSeconds(1) - 1e-10) < 1e-20, "crackSeconds");
  // a 6 digit PIN falls instantly, an 80+ bit password does not
  check(G.humanTime(G.crackSeconds(G.pin(6).bits)) === "instantly", "6-digit PIN is instant to crack offline");
  check(!/instantly|second/.test(G.humanTime(G.crackSeconds(G.password({ length: 20 }).bits))), "20-char password takes long");
  check(G.charClass("a") === "l" && G.charClass("Z") === "u" && G.charClass("5") === "d" && G.charClass("#") === "s", "charClass");
}

console.log("OK " + n + " checks");
