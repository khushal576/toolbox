/* Key Store: generator logic. No DOM in here, so node can test it (tests/unit/key_store_keygen_cases.js).
   Randomness comes ONLY from the Web Crypto API (crypto.getRandomValues), never Math.random.
   Every pick uses rejection sampling, so every character is exactly equally likely (no modulo bias). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.KeyGen = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const LOWER = "abcdefghijklmnopqrstuvwxyz";
  const UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const DIGITS = "0123456789";
  const SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?/~";
  const URL_SAFE_SYMBOLS = "-_.~";          // safe inside URLs, connection strings, shell commands and .env files
  const LOOKALIKES = "0O1lI|";              // easy to confuse when read aloud or copied by eye

  function cryptoSource() {
    const c = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
    if (!c || typeof c.getRandomValues !== "function") throw new Error("No secure random generator (Web Crypto) is available in this browser.");
    return c;
  }

  /* A uniformly random integer 0..n-1. `rng` is only for tests (an object with getRandomValues). */
  function randInt(n, rng) {
    if (!Number.isInteger(n) || n < 1 || n > 4294967296) throw new RangeError("randInt needs a whole number from 1 to 2^32");
    if (n === 1) return 0;
    const src = rng || cryptoSource();
    const limit = Math.floor(4294967296 / n) * n;     // values at or above this would make low numbers more likely: throw them away
    const buf = new Uint32Array(1);
    for (;;) {
      src.getRandomValues(buf);
      if (buf[0] < limit) return buf[0] % n;
    }
  }

  function pick(list, rng) { return list[randInt(list.length, rng)]; }

  function shuffle(arr, rng) {                       // Fisher-Yates, in place
    for (let i = arr.length - 1; i > 0; i--) {
      const j = randInt(i + 1, rng);
      const t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr;
  }

  function randomBytes(n, rng) {
    const out = new Uint8Array(n);
    (rng || cryptoSource()).getRandomValues(out);
    return out;
  }

  function dedupe(s) { return Array.from(new Set(s.split(""))).join(""); }

  /* ---- password ---------------------------------------------------------------------------------------------------- */
  const PASSWORD_DEFAULTS = { length: 20, lower: true, upper: true, digits: true, symbols: true, noLookalikes: false, urlSafe: false, exclude: "", requireEach: true };

  function passwordClasses(o) {
    const drop = (o.noLookalikes ? LOOKALIKES : "") + (o.exclude || "");
    const keep = (s) => dedupe(s.split("").filter((ch) => drop.indexOf(ch) === -1).join(""));
    const classes = [];
    if (o.lower) classes.push(keep(LOWER));
    if (o.upper) classes.push(keep(UPPER));
    if (o.digits) classes.push(keep(DIGITS));
    if (o.symbols) classes.push(keep(o.urlSafe ? URL_SAFE_SYMBOLS : SYMBOLS));
    return classes.filter((c) => c.length > 0);
  }

  function password(opts, rng) {
    const o = Object.assign({}, PASSWORD_DEFAULTS, opts || {});
    const length = Math.floor(Number(o.length));
    if (!(length >= 1 && length <= 512)) throw new RangeError("Length must be between 1 and 512.");
    const classes = passwordClasses(o);
    if (classes.length === 0) throw new Error("Pick at least one kind of character.");
    if (o.requireEach && length < classes.length) throw new Error("Length is too short to include every selected kind of character.");
    const pool = dedupe(classes.join(""));
    const chars = [];
    if (o.requireEach) classes.forEach((c) => chars.push(pick(c, rng)));      // one of each kind first ...
    while (chars.length < length) chars.push(pick(pool, rng));                 // ... then the rest from everything
    if (o.requireEach) shuffle(chars, rng);                                    // so the guaranteed ones are not always at the front
    return { value: chars.join(""), bits: length * Math.log2(pool.length), poolSize: pool.length };
  }

  /* ---- passphrase -------------------------------------------------------------------------------------------------- */
  const PASSPHRASE_DEFAULTS = { words: 5, separator: "-", capitalize: false, number: false };

  function passphrase(opts, wordList, rng) {
    const o = Object.assign({}, PASSPHRASE_DEFAULTS, opts || {});
    const n = Math.floor(Number(o.words));
    if (!(n >= 2 && n <= 20)) throw new RangeError("Use between 2 and 20 words.");
    if (!wordList || wordList.length < 1000) throw new Error("The word list did not load.");
    const parts = [];
    for (let i = 0; i < n; i++) {
      let w = pick(wordList, rng);
      if (o.capitalize) w = w.charAt(0).toUpperCase() + w.slice(1);
      parts.push(w);
    }
    let bits = n * Math.log2(wordList.length);
    if (o.number) {                                   // a 1 to 2 digit number glued to the end of one random word
      const at = randInt(n, rng);
      parts[at] = parts[at] + String(randInt(100, rng));
      bits += Math.log2(n) + Math.log2(100);
    }
    return { value: parts.join(o.separator), bits: bits, poolSize: wordList.length };
  }

  /* ---- PIN --------------------------------------------------------------------------------------------------------- */
  function pin(length, rng) {
    const n = Math.floor(Number(length));
    if (!(n >= 3 && n <= 32)) throw new RangeError("A PIN needs 3 to 32 digits.");
    let s = "";
    for (let i = 0; i < n; i++) s += pick(DIGITS, rng);
    return { value: s, bits: n * Math.log2(10), poolSize: 10 };
  }

  /* ---- tokens / API keys ------------------------------------------------------------------------------------------- */
  const TOKEN_DEFAULTS = { kind: "hex", size: 32, prefix: "" };    // size = bytes (hex, base64url) or characters (alnum)

  function toBase64Url(bytes) {
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function token(opts, rng) {
    const o = Object.assign({}, TOKEN_DEFAULTS, opts || {});
    const size = Math.floor(Number(o.size));
    if (!(size >= 8 && size <= 256)) throw new RangeError("Size must be between 8 and 256.");
    const prefix = String(o.prefix || "");
    let body, bits;
    if (o.kind === "hex") {
      body = Array.from(randomBytes(size, rng)).map((b) => b.toString(16).padStart(2, "0")).join("");
      bits = size * 8;
    } else if (o.kind === "base64url") {
      body = toBase64Url(randomBytes(size, rng));
      bits = size * 8;
    } else if (o.kind === "alnum") {
      const pool = LOWER + UPPER + DIGITS;
      body = "";
      for (let i = 0; i < size; i++) body += pick(pool, rng);
      bits = size * Math.log2(pool.length);
    } else {
      throw new Error("Unknown token type: " + o.kind);
    }
    return { value: prefix + body, bits: bits, poolSize: 0 };
  }

  /* ---- UUID v4 ----------------------------------------------------------------------------------------------------- */
  function uuid(rng) {
    const b = randomBytes(16, rng);
    b[6] = (b[6] & 0x0f) | 0x40;                      // version 4
    b[8] = (b[8] & 0x3f) | 0x80;                      // variant 10xx
    const h = Array.from(b).map((x) => x.toString(16).padStart(2, "0"));
    return { value: h.slice(0, 4).join("") + "-" + h.slice(4, 6).join("") + "-" + h.slice(6, 8).join("") + "-" + h.slice(8, 10).join("") + "-" + h.slice(10).join(""), bits: 122, poolSize: 0 };
  }

  /* ---- strength, in plain words ------------------------------------------------------------------------------------ */
  function strength(bits) {
    if (bits < 28) return { label: "Very weak", tone: "bad" };
    if (bits < 36) return { label: "Weak", tone: "bad" };
    if (bits < 60) return { label: "Fair", tone: "warn" };
    if (bits < 80) return { label: "Strong", tone: "good" };
    if (bits < 100) return { label: "Very strong", tone: "good" };
    return { label: "Excellent", tone: "good" };
  }

  /* Average time for an attacker who can try 10 billion guesses per second and has the stored hash (a fast, unsalted hash is the worst case). */
  function crackSeconds(bits, guessesPerSecond) {
    return Math.pow(2, bits - 1) / (guessesPerSecond || 1e10);
  }

  function humanTime(sec) {
    if (!isFinite(sec) || sec > 1e30) return "longer than the age of the universe";
    if (sec < 1) return "instantly";
    const units = [["second", 60], ["minute", 60], ["hour", 24], ["day", 365], ["year", 1000]];
    let v = sec;
    for (const [name, div] of units) {
      if (v < div) { const r = Math.floor(v); return r + " " + name + (r === 1 ? "" : "s"); }
      v = v / div;
    }
    // v is now in thousands of years
    if (v < 1000) return Math.floor(v) + " thousand years";
    v = v / 1000;                                    // millions of years
    if (v < 1000) return Math.floor(v) + " million years";
    v = v / 1000;                                    // billions of years
    if (v < 14) return Math.floor(v) + " billion years";
    return "longer than the age of the universe";
  }

  function charClass(ch) {
    if (/[a-z]/.test(ch)) return "l";
    if (/[A-Z]/.test(ch)) return "u";
    if (/[0-9]/.test(ch)) return "d";
    return "s";
  }

  return {
    LOWER, UPPER, DIGITS, SYMBOLS, URL_SAFE_SYMBOLS, LOOKALIKES,
    PASSWORD_DEFAULTS, PASSPHRASE_DEFAULTS, TOKEN_DEFAULTS,
    randInt, pick, shuffle, randomBytes,
    password, passphrase, pin, token, uuid,
    strength, crackSeconds, humanTime, charClass,
  };
});
