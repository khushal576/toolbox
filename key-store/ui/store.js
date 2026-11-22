/* Key Store: the Store tab (search, one-click copy, add / edit, trash). It talks only to this tool's own API (relative paths).
   A value is in this page only while it is being edited or revealed (it is masked again after 10 s or when you leave the tab),
   and it is shown with textContent / input values, never as HTML. Nothing secret is written to localStorage. */
"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  const REVEAL_MS = 10000;

  let META = { types: [], trash_days: 30 };
  let COUNTS = { total: 0, trash: 0, types: {}, environments: {}, tags: [] };
  let ENTRIES = [];
  let TRASH = false, TAG = "", SEQ = 0, loadedOnce = false;
  const revealed = new Map();                       // entry id -> timer; the revealed value itself lives only in the row's element
  let editing = null;                               // {id|null, tags:[...], original value}

  // ---- tiny helpers ----------------------------------------------------------------------------------------------
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  const typeInfo = (key) => META.types.find((t) => t.key === key) || { label: key, icon: "📦" };

  async function api(path, method, body) {           // the ONLY network call in this file: relative paths, JSON in and out
    const opts = { method: method || "GET", headers: { "Content-Type": "application/json" } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    let r;
    try { r = await fetch(path, opts); } catch (e) { throw new Error("Cannot reach Key Store. Is Toolbox running?"); }
    let d = {};
    try { d = await r.json(); } catch (e) { /* non-JSON error page */ }
    if (!r.ok || d.ok === false) throw new Error(d.detail || ("Request failed (" + r.status + ")"));
    return d;
  }

  function say(msg, action) {
    const t = $("toast2");
    t.textContent = msg;
    if (action) { const b = el("button", "", action.label); b.type = "button"; b.addEventListener("click", () => { t.classList.remove("show"); action.run(); }); t.appendChild(b); }
    t.classList.add("show");
    clearTimeout(say._t); say._t = setTimeout(() => t.classList.remove("show"), action ? 7000 : 1800);
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (e) {
      try {
        const ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta); ta.select(); const ok = document.execCommand("copy"); document.body.removeChild(ta); return ok;
      } catch (e2) { return false; }
    }
  }

  function ago(iso) {
    if (!iso) return "";
    const s = (Date.now() - Date.parse(iso)) / 1000;
    if (!isFinite(s)) return "";
    if (s < 60) return "just now";
    const units = [["minute", 60], ["hour", 24], ["day", 30], ["month", 12], ["year", 1e9]];
    let v = s / 60;
    for (const [name, div] of units) {
      if (v < div) { const n = Math.floor(v); return n + " " + name + (n === 1 ? "" : "s") + " ago"; }
      v /= div;
    }
    return "";
  }

  function showStoreError(msg) { const e = $("storeError"); e.textContent = msg || ""; e.classList.toggle("hidden", !msg); }

  // ---- loading and rendering ----------------------------------------------------------------------------------------
  async function loadMeta() {
    META = await api("meta");
    const fType = $("fType"), eType = $("eType");
    fType.textContent = ""; eType.textContent = "";
    fType.appendChild(new Option("All types", ""));
    META.types.forEach((t) => { fType.appendChild(new Option(t.icon + " " + t.label, t.key)); eType.appendChild(new Option(t.icon + " " + t.label, t.key)); });
  }

  function query() {
    const p = new URLSearchParams();
    if ($("q").value.trim()) p.set("q", $("q").value.trim());
    if ($("fType").value) p.set("type", $("fType").value);
    if ($("fEnv").value) p.set("env", $("fEnv").value);
    if (TAG) p.set("tag", TAG);
    if ($("fValues").checked) p.set("in_values", "true");
    if (TRASH) p.set("trash", "true");
    p.set("sort", $("fSort").value);
    return p.toString();
  }

  async function refresh() {
    const my = ++SEQ;
    try {
      const d = await api("entries?" + query());
      if (my !== SEQ) return;                         // a newer search already started
      ENTRIES = d.entries; COUNTS = d.counts; showStoreError("");
      render();
    } catch (e) { if (my === SEQ) showStoreError(e.message); }
  }

  function hasFilters() { return !!($("q").value.trim() || $("fType").value || $("fEnv").value || TAG); }

  function render() {
    const badge = $("storeCount");
    badge.textContent = String(COUNTS.total); badge.classList.toggle("hidden", COUNTS.total === 0);

    // type options show how many entries each type has
    Array.from($("fType").options).forEach((o) => {
      const t = o.value ? typeInfo(o.value) : null;
      o.textContent = o.value ? t.icon + " " + t.label + (COUNTS.types[o.value] ? " (" + COUNTS.types[o.value] + ")" : "") : "All types";
    });
    const dl = $("tagList"); dl.textContent = "";
    COUNTS.tags.forEach(([t]) => dl.appendChild(new Option(t)));
    const bar = $("tagbar"); bar.textContent = "";
    COUNTS.tags.slice(0, 14).forEach(([t, n]) => {
      const b = el("button", "chip" + (TAG.toLowerCase() === t.toLowerCase() ? " on" : ""), t); b.type = "button";
      b.appendChild(el("small", "", String(n)));
      b.addEventListener("click", () => { TAG = TAG.toLowerCase() === t.toLowerCase() ? "" : t; refresh(); });
      bar.appendChild(b);
    });

    $("trashToggle").textContent = TRASH ? "← Back to entries" : "🗑 Trash" + (COUNTS.trash ? " (" + COUNTS.trash + ")" : "");
    $("emptyTrash").classList.toggle("hidden", !(TRASH && ENTRIES.length));
    $("listInfo").textContent = TRASH ? "Trash: kept " + META.trash_days + " days, then deleted for good"
      : hasFilters() ? ENTRIES.length + " of " + COUNTS.total + " match" : COUNTS.total + (COUNTS.total === 1 ? " entry" : " entries");
    $("enterHint").classList.toggle("hidden", TRASH || ENTRIES.length === 0);

    const list = $("list"); list.textContent = "";
    if (ENTRIES.length === 0) { list.appendChild(emptyState()); return; }
    ENTRIES.forEach((e) => list.appendChild(row(e)));
  }

  function emptyState() {
    const d = el("div", "empty");
    if (TRASH) { d.appendChild(el("b", "", "The trash is empty")); return d; }
    if (COUNTS.total === 0) {
      d.appendChild(el("b", "", "Nothing saved yet"));
      d.appendChild(el("div", "", "Add your first key, URL or connection string, or generate a password and press “Save to Store…”."));
      const row2 = el("div", "row"); row2.style.justifyContent = "center";
      const a = el("button", "act", "+ New entry"); a.type = "button"; a.addEventListener("click", () => openForm({}));
      const g = el("button", "act alt", "Open the generator"); g.type = "button"; g.addEventListener("click", () => $("tabGen").click());
      row2.appendChild(a); row2.appendChild(g); d.appendChild(row2);
    } else {
      d.appendChild(el("b", "", "No match"));
      d.appendChild(el("div", "", "Try fewer words, clear a filter, or tick “Also search inside values”."));
    }
    return d;
  }

  function iconButton(text, title, fn) {
    const b = el("button", "icon", text); b.type = "button"; b.title = title; b.setAttribute("aria-label", title);
    b.addEventListener("click", fn); return b;
  }

  function row(e) {
    const t = typeInfo(e.type);
    const r = el("div", "entry"); r.dataset.id = e.id;
    r.appendChild(el("div", "eicon", t.icon));
    const main = el("div", "emain");
    const title = el("div", "etitle");
    title.appendChild(el("span", "", e.name));
    if (e.pinned) title.appendChild(el("span", "", "📌"));
    title.appendChild(el("span", "b2", t.label));
    if (e.environment === "prod") title.appendChild(el("span", "b2 prod", "PROD"));
    else if (e.environment === "non-prod") title.appendChild(el("span", "b2", "dev / test"));
    main.appendChild(title);

    const meta = el("div", "emeta");
    e.tags.forEach((g) => meta.appendChild(el("span", "tagpill", g)));
    if (e.note) meta.appendChild(document.createTextNode(e.note.length > 90 ? e.note.slice(0, 90) + "…" : e.note));
    const when = TRASH ? ("In the trash · " + (e.days_left === 0 ? "deleted soon" : e.days_left + " days left"))
      : e.last_used ? "used " + ago(e.last_used) : "added " + ago(e.created_at);
    meta.appendChild(el("span", "", (meta.childNodes.length ? "  ·  " : "") + when));
    main.appendChild(meta);

    const val = el("div", "evalue" + (e.preview ? "" : " masked"), e.preview || "•".repeat(10) + "  (" + e.value_length + " characters)");
    if (!TRASH) main.appendChild(val);
    r.appendChild(main);

    const act = el("div", "eactions");
    if (TRASH) {
      const rs = el("button", "act alt", "Restore"); rs.type = "button"; rs.addEventListener("click", () => restore(e));
      const del = el("button", "act alt", "Delete forever"); del.type = "button"; del.style.color = "var(--err-text)";
      del.addEventListener("click", () => deleteForever(e));
      act.appendChild(rs); act.appendChild(del);
    } else {
      const cp = el("button", "act", "Copy"); cp.type = "button"; cp.addEventListener("click", () => copyEntry(e));
      act.appendChild(cp);
      if (!e.preview) act.appendChild(iconButton("👁", "Show the value for 10 seconds", () => toggleReveal(e, val, act.firstChild.nextSibling)));
      else { const gap = el("span"); gap.style.width = "32px"; act.appendChild(gap); }      // keeps the Copy/Edit buttons lined up with the other rows
      act.appendChild(iconButton("✏️", "Edit", () => editEntry(e.id)));
      act.appendChild(iconButton(e.pinned ? "📍" : "📌", e.pinned ? "Unpin" : "Pin to the top", () => pin(e)));
      act.appendChild(iconButton("⧉", "Duplicate", () => duplicate(e)));
      act.appendChild(iconButton("🗑", "Move to trash", () => trashEntry(e)));
    }
    r.appendChild(act);
    return r;
  }

  // ---- actions on one entry ------------------------------------------------------------------------------------------
  async function copyEntry(e) {
    try {
      const d = await api("entries/" + encodeURIComponent(e.id) + "/copy", "POST");
      const ok = await copyText(d.value);
      say(ok ? "Copied “" + e.name + "”" + (e.environment === "prod" ? " (PROD)" : "") : "Copy failed: use the 👁 button and copy it by hand");
    } catch (err) { say(err.message); }
  }

  function mask(e, valEl, btn) {
    clearTimeout(revealed.get(e.id)); revealed.delete(e.id);
    valEl.textContent = "•".repeat(10) + "  (" + e.value_length + " characters)"; valEl.classList.add("masked");
    if (btn) btn.textContent = "👁";
  }

  async function toggleReveal(e, valEl, btn) {
    if (revealed.has(e.id)) { mask(e, valEl, btn); return; }
    try {
      const d = await api("entries/" + encodeURIComponent(e.id));
      valEl.textContent = d.entry.value; valEl.classList.remove("masked"); btn.textContent = "🙈";
      revealed.set(e.id, setTimeout(() => mask(e, valEl, btn), REVEAL_MS));
    } catch (err) { say(err.message); }
  }

  function maskAll() {                               // leaving the tab or the window: nothing stays on screen
    revealed.forEach((t) => clearTimeout(t)); revealed.clear();
    if (!TRASH && $("paneStore") && !$("paneStore").classList.contains("hidden")) render();
  }

  async function pin(e) { try { await api("entries/" + encodeURIComponent(e.id), "PUT", { pinned: !e.pinned }); refresh(); } catch (err) { say(err.message); } }
  async function duplicate(e) { try { await api("entries/" + encodeURIComponent(e.id) + "/duplicate", "POST"); say("Duplicated"); refresh(); } catch (err) { say(err.message); } }

  async function trashEntry(e) {
    try {
      await api("entries/" + encodeURIComponent(e.id), "DELETE");
      say("Moved “" + e.name + "” to the trash", { label: "Undo", run: () => restore(e, true) });
      refresh();
    } catch (err) { say(err.message); }
  }
  async function restore(e, quiet) {
    try { const d = await api("entries/" + encodeURIComponent(e.id) + "/restore", "POST"); if (!quiet || d.name !== e.name) say("Restored “" + d.name + "”"); refresh(); }
    catch (err) { say(err.message); }
  }
  async function deleteForever(e) {
    if (!confirm("Delete “" + e.name + "” for good? This cannot be undone.")) return;
    try { await api("entries/" + encodeURIComponent(e.id) + "/forever", "DELETE"); say("Deleted"); refresh(); } catch (err) { say(err.message); }
  }

  // ---- the add / edit form --------------------------------------------------------------------------------------------
  function setTags(tags) {
    editing.tags = tags;
    const box = $("eTagBox");
    Array.from(box.querySelectorAll(".tagpill")).forEach((n) => n.remove());
    tags.forEach((t, i) => {
      const p = el("span", "tagpill", t);
      const x = el("button", "", "×"); x.type = "button"; x.title = "Remove tag"; x.addEventListener("click", () => setTags(editing.tags.filter((_, j) => j !== i)));
      p.appendChild(x); box.insertBefore(p, $("eTagIn"));
    });
  }
  function addTagFromInput() {
    const raw = $("eTagIn").value.split(",").map((s) => s.trim()).filter(Boolean);
    if (!raw.length) return;
    const have = editing.tags.map((t) => t.toLowerCase());
    const next = editing.tags.slice();
    raw.forEach((t) => { if (!have.includes(t.toLowerCase())) { have.push(t.toLowerCase()); next.push(t); } });
    $("eTagIn").value = ""; setTags(next);
  }
  function hideValue(on) { $("eValue").classList.toggle("hiddenval", on); $("eReveal").textContent = on ? "👁" : "🙈"; }
  function dlgError(msg) { const e = $("dlgError"); e.textContent = msg || ""; e.classList.toggle("hidden", !msg); }

  function openForm(init) {                          // init: {id, name, value, type, tags, note, environment}
    editing = { id: init.id || null, tags: [], original: init.value || "" };
    $("dlgTitle").textContent = init.id ? "Edit entry" : "New entry";
    $("eName").value = init.name || ""; $("eType").value = init.type || "password";
    $("eValue").value = init.value || ""; $("eNote").value = init.note || "";
    document.querySelectorAll('input[name="eEnv"]').forEach((r) => { r.checked = r.value === (init.environment || ""); });
    $("eTagIn").value = ""; setTags((init.tags || []).slice());
    hideValue(!!init.id || !init.value);              // a freshly generated value is shown so you can see what you are saving
    if (init.value && !init.id) hideValue(false);
    dlgError("");
    $("dlgSave").disabled = false;
    $("dlg").showModal();
    $("eName").focus();
  }

  async function editEntry(id) {
    try { const d = await api("entries/" + encodeURIComponent(id)); openForm(d.entry); }
    catch (err) { say(err.message); }
  }

  async function submitForm(ev) {
    ev.preventDefault();
    addTagFromInput();
    const body = {
      name: $("eName").value, type: $("eType").value, tags: editing.tags, note: $("eNote").value,
      environment: (document.querySelector('input[name="eEnv"]:checked') || {}).value || "",
    };
    const value = $("eValue").value;
    if (!editing.id || value !== editing.original) body.value = value;     // an edit that leaves the value alone does not send it again
    if (!editing.id && !value) { dlgError("The value is empty."); return; }
    $("dlgSave").disabled = true;
    try {
      if (editing.id) await api("entries/" + encodeURIComponent(editing.id), "PUT", body);
      else await api("entries", "POST", Object.assign({ value: value }, body));
      $("eValue").value = ""; editing = null;
      $("dlg").close(); say("Saved"); refresh();
    } catch (err) { dlgError(err.message); $("dlgSave").disabled = false; }
  }

  function generateInto() {
    const G = window.KeyGen; if (!G) return;
    const type = $("eType").value;
    try {
      let v;
      if (type === "api_key" || type === "token") v = G.token({ kind: "hex", size: 32 }).value;
      else {
        let o = {};
        try { o = (JSON.parse(localStorage.getItem("keystore.genopts") || "{}").password) || {}; } catch (e) { /* defaults */ }
        if (type === "connection_string") o = Object.assign({}, o, { urlSafe: true });         // @ : / ? # would break a connection string
        v = G.password(o).value;
      }
      $("eValue").value = v; hideValue(false);
    } catch (err) { dlgError(err.message); }
  }

  // ---- wiring ---------------------------------------------------------------------------------------------------------
  let debounce;
  $("q").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(refresh, 150); });
  $("q").addEventListener("keydown", async (ev) => {
    if (ev.key === "Enter" && ENTRIES.length && !TRASH) { ev.preventDefault(); await copyEntry(ENTRIES[0]); }
    if (ev.key === "Escape") { $("q").value = ""; refresh(); }
  });
  ["fType", "fEnv", "fSort", "fValues"].forEach((id) => $(id).addEventListener("change", refresh));
  $("newBtn").addEventListener("click", () => openForm({}));
  $("trashToggle").addEventListener("click", () => { TRASH = !TRASH; refresh(); });
  $("emptyTrash").addEventListener("click", async () => {
    if (!confirm("Delete everything in the trash for good? This cannot be undone.")) return;
    try { const d = await api("trash/empty", "POST"); say("Deleted " + d.deleted + (d.deleted === 1 ? " entry" : " entries")); refresh(); } catch (err) { say(err.message); }
  });
  $("dlgForm").addEventListener("submit", submitForm);
  $("dlgCancel").addEventListener("click", () => { $("eValue").value = ""; editing = null; $("dlg").close(); });
  $("dlg").addEventListener("close", () => { $("eValue").value = ""; });        // never leave a value sitting in a closed form
  $("eReveal").addEventListener("click", () => hideValue(!$("eValue").classList.contains("hiddenval")));
  $("eGen").addEventListener("click", generateInto);
  $("eTagIn").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === ",") { ev.preventDefault(); addTagFromInput(); }
    if (ev.key === "Backspace" && !$("eTagIn").value && editing.tags.length) setTags(editing.tags.slice(0, -1));
  });
  $("eTagIn").addEventListener("blur", addTagFromInput);

  document.addEventListener("keydown", (ev) => {      // "/" jumps to the search box, like most sites
    if (ev.key !== "/" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if ($("paneStore").classList.contains("hidden") || $("dlg").open) return;
    const tag = (document.activeElement || {}).tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    ev.preventDefault(); $("q").focus(); $("q").select();
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) maskAll(); });
  window.addEventListener("blur", maskAll);

  // "Save to Store…" in the generator: open the form with the value filled in (it travels only inside this page)
  document.addEventListener("keystore:save", async (ev) => {
    await ensureLoaded();
    openForm({ value: ev.detail.value, type: ev.detail.type });
  });

  async function ensureLoaded() {
    if (loadedOnce) return;
    try { await loadMeta(); loadedOnce = true; } catch (e) { showStoreError(e.message); }
  }

  window.KeyStoreUI = {
    async activated() { await ensureLoaded(); refresh(); if (!$("dlg").open) $("q").focus(); },
  };
})();
