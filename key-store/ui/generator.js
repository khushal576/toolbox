/* Key Store: the generator page (options, rendering, copy). The logic is in keygen.js; nothing here talks to the server. */
"use strict";
(function () {
  const G = window.KeyGen;
  const $ = (id) => document.getElementById(id);
  const MODES = [
    ["password", "Password"], ["passphrase", "Passphrase"], ["pin", "PIN"], ["token", "Token / API key"], ["uuid", "UUID"],
  ];
  const NOTES = {
    password: "Best for logins and database passwords. Use a password manager habit: generate, then save it, never reuse it.",
    passphrase: "Several random words. Easier to type and remember than a password of the same strength.",
    pin: "A PIN is only safe where the system locks you out after a few wrong tries.",
    token: "For programs, not people: API keys, secrets, webhooks. Keep it in the Store rather than a text file.",
    uuid: "A random identifier. Good as an ID, not a password.",
  };
  const DEFAULTS = {
    mode: "password",
    password: Object.assign({}, G.PASSWORD_DEFAULTS),
    passphrase: { words: 5, separator: "-", capitalize: false, number: false },
    pin: { length: 6 },
    token: { kind: "hex", size: 32, prefix: "" },
  };

  // only the OPTIONS are remembered in this browser (never a generated value)
  let S;
  try { S = Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem("keystore.genopts") || "{}")); } catch (e) { S = Object.assign({}, DEFAULTS); }
  ["password", "passphrase", "pin", "token"].forEach((k) => { S[k] = Object.assign({}, DEFAULTS[k], S[k] || {}); });
  if (!MODES.some((m) => m[0] === S.mode)) S.mode = "password";
  const save = () => { try { localStorage.setItem("keystore.genopts", JSON.stringify(S)); } catch (e) { /* private mode: fine */ } };

  let current = "";

  function generate() {
    switch (S.mode) {
      case "password": return G.password(S.password);
      case "passphrase": return G.passphrase(S.passphrase, window.KEYSTORE_WORDS);
      case "pin": return G.pin(S.pin.length);
      case "token": return G.token(S.token);
      default: return G.uuid();
    }
  }

  function paint(el, text) {                       // colour letters, digits and symbols differently; text nodes only, so nothing is ever parsed as HTML
    el.textContent = "";
    for (const ch of text) {
      const cls = G.charClass(ch);
      if (cls === "d" || cls === "s") { const s = document.createElement("span"); s.className = "c-" + cls; s.textContent = ch; el.appendChild(s); }
      else el.appendChild(document.createTextNode(ch));
    }
  }

  function showStrength(bits) {
    const st = G.strength(bits);
    $("strengthLabel").textContent = st.label + " · " + Math.round(bits) + " bits";
    $("strengthLabel").className = "strength tone-" + st.tone;
    const fill = $("meterFill");
    fill.style.width = Math.min(100, (bits / 100) * 100) + "%";
    fill.style.background = st.tone === "bad" ? "var(--err-text)" : st.tone === "warn" ? "var(--warn-text)" : "var(--ok-text)";
    $("crack").textContent = "Estimated time to crack: " + G.humanTime(G.crackSeconds(bits)) + " (an attacker trying 10 billion guesses per second).";
  }

  function render() {
    $("error").classList.add("hidden");
    try {
      const r = generate();
      current = r.value;
      paint($("result"), r.value);
      showStrength(r.bits);
    } catch (e) {
      $("error").textContent = e.message; $("error").classList.remove("hidden");
    }
  }

  function toast(msg) {
    const t = $("toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 1600);
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (e) {
      try {                                          // older browsers / blocked in an iframe
        const ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta); ta.select(); const ok = document.execCommand("copy"); document.body.removeChild(ta); return ok;
      } catch (e2) { return false; }
    }
  }

  function setMode(mode) {
    S.mode = mode; save();
    document.querySelectorAll("#modes .mode").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
    document.querySelectorAll(".opts[data-mode]").forEach((p) => p.classList.toggle("hidden", p.dataset.mode !== mode));
    $("modeNote").textContent = NOTES[mode];
    $("moreList").textContent = "";
    render();
  }

  // ---- bind the option controls to the state -------------------------------------------------------------------
  function bind(id, group, key, kind) {
    const el = $(id);
    const read = () => kind === "bool" ? el.checked : kind === "num" ? Number(el.value) : el.value;
    const write = () => { if (kind === "bool") el.checked = !!S[group][key]; else el.value = S[group][key]; };
    write();
    el.addEventListener("input", () => { S[group][key] = read(); save(); sync(); render(); });
  }
  function sync() {
    $("lenShow").textContent = S.password.length;
    $("wordsShow").textContent = S.passphrase.words;
    $("pinShow").textContent = S.pin.length;
    $("t_sizeLab").textContent = S.token.kind === "alnum" ? "Length (characters)" : "Size (bytes of randomness)";
    $("p_urlSafe").disabled = !S.password.symbols;
  }
  bind("p_length", "password", "length", "num");
  ["lower", "upper", "digits", "symbols", "urlSafe", "noLookalikes", "requireEach"].forEach((k) => bind("p_" + k, "password", k, "bool"));
  bind("p_exclude", "password", "exclude", "str");
  bind("w_words", "passphrase", "words", "num"); bind("w_separator", "passphrase", "separator", "str");
  bind("w_capitalize", "passphrase", "capitalize", "bool"); bind("w_number", "passphrase", "number", "bool");
  bind("n_length", "pin", "length", "num");
  bind("t_kind", "token", "kind", "str"); bind("t_size", "token", "size", "num"); bind("t_prefix", "token", "prefix", "str");
  sync();

  MODES.forEach(([key, label]) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "mode"; b.dataset.mode = key; b.textContent = label;
    b.addEventListener("click", () => setMode(key));
    $("modes").appendChild(b);
  });

  $("copy").addEventListener("click", async () => { toast((await copyText(current)) ? "Copied" : "Copy failed: select the text and press Ctrl+C"); });
  $("regen").addEventListener("click", render);
  $("saveBtn").addEventListener("click", () => {
    const type = S.mode === "token" ? "token" : S.mode === "uuid" ? "token" : "password";
    document.dispatchEvent(new CustomEvent("keystore:save", { detail: { value: current, type: type } }));
  });
  $("moreBtn").addEventListener("click", () => {
    const list = $("moreList"); list.textContent = "";
    for (let i = 0; i < 5; i++) {
      let r; try { r = generate(); } catch (e) { return; }
      const row = document.createElement("div"); row.className = "more-item";
      const code = document.createElement("code"); paint(code, r.value);
      const btn = document.createElement("button"); btn.type = "button"; btn.className = "mini"; btn.textContent = "Copy";
      btn.addEventListener("click", async () => { toast((await copyText(r.value)) ? "Copied" : "Copy failed"); });
      row.appendChild(code); row.appendChild(btn); list.appendChild(row);
    }
  });

  setMode(S.mode);
})();
