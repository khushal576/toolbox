/* Drop Rooms: the page. Rooms on the left, the room's stream on the right, like a chat. Talks only to this tool's own API
   (relative paths) through api() and, for file uploads (which need progress events), through upload(). Messages and keys are shown with textContent / text nodes, never as HTML. The room key is never
   stored in the browser: it is held in memory only while a dialog shows it. localStorage keeps just your nickname and the last room. */
"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  const HEADERS = { "Content-Type": "application/json", "X-Drop-Rooms": "1" };     // the custom header is the request-forgery guard

  let META = { presets: [3600, 10800, 21600, 43200, 86400, 259200, 604800, 2592000], default_retention: 21600, undo_seconds: 10 };
  let rooms = [], cur = null, items = [], rev = null, skew = 0;
  let editing = null;                              // {id, text, version, restart, seconds, current}
  let pollTimer = null, sending = false, detail = null;
  let uploads = [];                                // {id, name, pct, error, abort}
  let usage = { room_bytes: 0, room_quota: 1073741824 };

  // ---- helpers ------------------------------------------------------------------------------------------------------
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  const lsGet = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private mode: fine */ } };
  const nowSrv = () => Date.now() / 1000 + skew;                                   // the server's clock, not this device's

  async function api(path, method, body) {         // the ONLY network call in this file: relative paths, JSON in and out
    const opts = { method: method || "GET", headers: HEADERS, credentials: "same-origin" };
    if (body !== undefined) opts.body = JSON.stringify(body);
    let r;
    try { r = await fetch(path, opts); } catch (e) { const err = new Error("Cannot reach Drop Rooms. Is Toolbox running?"); err.network = true; throw err; }
    let d = {};
    try { d = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok || d.ok === false) { const err = new Error(d.detail || ("Request failed (" + r.status + ")")); err.status = r.status; err.data = d; throw err; }
    return d;
  }

  function upload(path, body, onProgress) {       // the ONLY other network call: a streamed PUT whose body is the file, with progress
    const xhr = new XMLHttpRequest();
    const promise = new Promise((resolve, reject) => {
      xhr.open("PUT", path);
      xhr.setRequestHeader("X-Drop-Rooms", "1");
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
      xhr.onload = () => {
        let d = {};
        try { d = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
        if (xhr.status >= 200 && xhr.status < 300 && d.ok !== false) resolve(d);
        else { const err = new Error(d.detail || ("Upload failed (" + xhr.status + ")")); err.status = xhr.status; reject(err); }
      };
      xhr.onerror = () => reject(Object.assign(new Error("Upload failed: cannot reach Drop Rooms."), { network: true }));
      xhr.onabort = () => reject(Object.assign(new Error("Cancelled"), { cancelled: true }));
      xhr.send(body);
    });
    return { promise: promise, abort: () => xhr.abort() };
  }

  const fmtSize = (n) => n < 1024 ? n + " bytes" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : n < 1073741824 ? (n / 1048576).toFixed(1) + " MB" : (n / 1073741824).toFixed(2) + " GB";

  function say(msg, action) {
    const t = $("toast");
    t.textContent = msg;
    if (action) { const b = el("button", "", action.label); b.type = "button"; b.addEventListener("click", () => { t.classList.remove("show"); action.run(); }); t.appendChild(b); }
    t.classList.add("show");
    clearTimeout(say._t); say._t = setTimeout(() => t.classList.remove("show"), action ? (META.undo_seconds + 1) * 1000 : 2200);
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

  function hue(s) { let h = 0; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
  function avatar(cls, name) {
    const a = el("div", cls, (String(name).trim()[0] || "?").toUpperCase());
    a.style.background = "hsl(" + hue(name) + " 55% 46%)";
    return a;
  }

  const DUR = { 3600: "1 hour", 10800: "3 hours", 21600: "6 hours", 43200: "12 hours", 86400: "1 day", 259200: "3 days", 604800: "7 days", 2592000: "30 days" };
  function fmtDur(s) { return DUR[s] || (s % 3600 === 0 ? (s / 3600) + " hours" : Math.round(s / 60) + " minutes"); }
  function fmtLeft(sec) {
    sec = Math.max(0, Math.floor(sec));
    if (sec < 60) return sec + " s";
    if (sec < 3600) return Math.floor(sec / 60) + " min";
    if (sec < 86400) return Math.floor(sec / 3600) + " h " + Math.floor((sec % 3600) / 60) + " min";
    return Math.floor(sec / 86400) + " d " + Math.floor((sec % 86400) / 3600) + " h";
  }
  function fmtTime(ts) {
    const d = new Date(ts * 1000), today = new Date();
    const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return d.toDateString() === today.toDateString() ? hm : d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + hm;
  }
  function fmtAgo(ts) {
    const s = nowSrv() - ts;
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    return Math.floor(s / 86400) + " d ago";
  }

  function fillRetention(sel, value) {
    sel.textContent = "";
    META.presets.forEach((p) => sel.appendChild(new Option(fmtDur(p), String(p))));
    sel.value = String(META.presets.includes(value) ? value : META.default_retention);
  }

  function linkify(parent, text) {                // http(s) links become anchors, everything else stays plain text
    const re = /https?:\/\/[^\s<>"']+/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      const raw = m[0], url = raw.replace(/[.,;:!?)\]}]+$/, "");
      parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      let ok = false;
      try { const u = new URL(url); if (u.protocol === "http:" || u.protocol === "https:") { const a = el("a", "", url); a.href = u.href; a.target = "_blank"; a.rel = "noopener noreferrer"; parent.appendChild(a); ok = true; } } catch (e) { /* not a URL */ }
      if (!ok) parent.appendChild(document.createTextNode(url));
      last = m.index + url.length; re.lastIndex = last;
    }
    parent.appendChild(document.createTextNode(text.slice(last)));
  }

  // ---- rooms ----------------------------------------------------------------------------------------------------------
  const room = () => rooms.find((r) => r.id === cur) || null;

  function renderRooms() {
    const list = $("roomList"); list.textContent = "";
    rooms.forEach((r) => {
      const b = el("button", "room" + (r.id === cur ? " on" : "")); b.type = "button";
      b.appendChild(avatar("av", r.name));
      b.appendChild(el("div", "nm", r.name));
      b.appendChild(el("small", "", r.members + " 👤"));
      b.addEventListener("click", () => selectRoom(r.id));
      list.appendChild(b);
    });
  }

  function renderHead() {
    const r = room();
    $("roomName").textContent = r ? r.name : "Welcome";
    $("roomMeta").textContent = r ? r.members + (r.members === 1 ? " device" : " devices") + " · things delete after " + fmtDur(r.default_retention) + " unless you choose another time" +
      (usage.room_bytes ? " · " + fmtSize(usage.room_bytes) + " of " + fmtSize(usage.room_quota) + " used" : "") : "Create a room or join one with a key";
    $("inviteBtn").classList.toggle("hidden", !r);
    $("settingsBtn").classList.toggle("hidden", !r);
    $("composer").classList.toggle("hidden", !r);
    $("composerHint").classList.toggle("hidden", !r);
  }

  async function loadRooms() {
    let d;
    try { d = await api("rooms"); } catch (e) { return; }
    rooms = d.rooms;
    if (cur && !room()) { cur = null; items = []; rev = null; editing = null; say("You are no longer in that room (it was deleted, or you were removed)."); }
    if (!cur && rooms.length) { const last = lsGet("droprooms.last"); await selectRoom((rooms.find((r) => r.id === last) || rooms[0]).id); return; }
    renderRooms(); renderHead();
    if (!rooms.length) renderItems();
  }

  async function selectRoom(id) {
    cur = id; rev = null; items = []; editing = null; usage = { room_bytes: 0, room_quota: usage.room_quota }; uploads = []; renderUploads(); lsSet("droprooms.last", id);
    $("side").classList.remove("open");
    renderRooms(); renderHead(); fillRetention($("ret"), room().default_retention);
    renderItems();
    await pollItems();
    $("msg").focus();
  }

  // ---- the stream -----------------------------------------------------------------------------------------------------
  async function pollItems() {
    const id = cur;
    if (!id) return;
    try {
      const d = await api("rooms/" + encodeURIComponent(id) + "/items" + (rev !== null ? "?rev=" + rev : ""));
      if (id !== cur) return;
      skew = d.now - Date.now() / 1000;
      if (d.changed) {
        items = d.items; rev = d.rev; if (d.usage) usage = d.usage;
        const r = room(); if (r && d.room) { Object.assign(r, { name: d.room.name, default_retention: d.room.default_retention, nickname: d.room.nickname, role: d.room.role }); renderRooms(); renderHead(); }
        renderItems();
      }
    } catch (e) {
      if (e.status === 404) await loadRooms();
    }
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => { await pollItems(); schedulePoll(); }, document.hidden ? 10000 : 2000);
  }

  function renderItems() {
    const box = $("stream");
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    box.textContent = "";
    if (!rooms.length) {
      const e = el("div", "empty");
      e.appendChild(el("b", "", "Welcome to Drop Rooms"));
      e.appendChild(el("div", "", "A room is a private place to drop text between your devices (or with other people). Everyone who joins with the room's key sees everything in it. Nothing stays longer than 30 days."));
      const row = el("div", "row");
      const a = el("button", "", "+ Create a room"); a.type = "button"; a.addEventListener("click", openCreate);
      const b = el("button", "alt", "Join with a key"); b.type = "button"; b.addEventListener("click", () => openJoin(""));
      row.appendChild(a); row.appendChild(b); e.appendChild(row); box.appendChild(e);
      return;
    }
    if (!items.length) {
      const e = el("div", "empty");
      e.appendChild(el("b", "", "Nothing here yet"));
      e.appendChild(el("div", "", "Type below and press Enter. It shows up on every device in this room, and deletes itself after " + fmtDur(room().default_retention) + " unless you choose another time."));
      box.appendChild(e);
      return;
    }
    items.forEach((it) => box.appendChild(itemRow(it)));
    if (nearBottom) box.scrollTop = box.scrollHeight;
  }

  function itemRow(it) {
    const row = el("div", "item"); row.dataset.id = it.id;
    row.appendChild(avatar("av", it.nickname));
    const body = el("div", "body");
    const who = el("div", "who");
    who.appendChild(el("b", "", it.nickname + (it.mine ? " (you)" : "")));
    who.appendChild(el("span", "when", fmtTime(it.created_at)));
    if (it.edited_at) who.appendChild(el("span", "edited", "edited by " + it.edited_by + " · " + fmtAgo(it.edited_at)));
    const left = el("span", "left"); left.dataset.exp = String(it.expires_at); left.title = "This is deleted for everyone when the time runs out";
    who.appendChild(left);
    body.appendChild(who);
    const isFile = it.kind === "file" || it.kind === "folder";
    if (isFile) body.appendChild(fileCard(it));
    else if (editing && editing.id === it.id) body.appendChild(editorFor(it));
    else { const t = el("div", "txt"); linkify(t, it.text); body.appendChild(t); }
    row.appendChild(body);
    if (!(editing && editing.id === it.id)) {
      const acts = el("div", "acts");
      if (!isFile) {
        acts.appendChild(actBtn("📋", "Copy", async () => say((await copyText(it.text)) ? "Copied" : "Copy failed: select the text and press Ctrl+C")));
        acts.appendChild(actBtn("✏️", "Edit (everyone in the room sees the change)", () => { editing = { id: it.id, text: it.text, version: it.version, restart: false, seconds: room().default_retention, current: null }; renderItems(); const ta = document.querySelector(".editor textarea"); if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); } }));
      }
      const rb = actBtn("⏱", "Change when it is deleted", () => openRetentionMenu(rb, it)); acts.appendChild(rb);
      acts.appendChild(actBtn("🗑", "Delete for everyone", () => deleteItem(it)));
      row.appendChild(acts);
    }
    updateLeft(left);
    return row;
  }

  const fileUrl = (it, suffix) => "rooms/" + encodeURIComponent(cur) + "/files/" + encodeURIComponent(it.id) + (suffix || "");

  function fileCard(it) {
    const box = el("div");
    const card = el("div", "file");
    card.appendChild(el("div", "ico", it.kind === "folder" ? "🗂️" : it.image ? "🖼️" : "📄"));
    const info = el("div", "info");
    info.appendChild(el("div", "fname", it.file_name));
    info.appendChild(el("div", "fmeta", fmtSize(it.size) + (it.kind === "folder" && it.text ? " · " + it.text + " (ZIP)" : "")));
    card.appendChild(info);
    if (it.text_preview) { const pv = el("button", "pv", "Preview"); pv.type = "button"; pv.addEventListener("click", () => openViewer(it)); card.appendChild(pv); }
    const dl = el("a", "dl", "Download"); dl.href = fileUrl(it); dl.setAttribute("download", it.file_name); dl.rel = "noopener"; card.appendChild(dl);
    box.appendChild(card);
    if (it.image) {
      const img = document.createElement("img"); img.className = "thumb"; img.loading = "lazy"; img.alt = it.file_name; img.src = fileUrl(it, "/preview");
      img.addEventListener("click", () => openViewer(it)); box.appendChild(img);
    }
    return box;
  }

  async function openViewer(it) {
    $("vTitle").textContent = it.file_name;
    const body = $("vBody"); body.textContent = "";
    $("vDownload").href = fileUrl(it); $("vDownload").setAttribute("download", it.file_name);
    if (it.image) { const img = document.createElement("img"); img.alt = it.file_name; img.src = fileUrl(it, "/preview"); body.appendChild(img); }
    else {
      try {
        const d = await api(fileUrl(it, "/text"));
        const pre = el("pre", "", d.text); body.appendChild(pre);
        if (d.truncated) body.appendChild(el("div", "fmeta", "Only the first part is shown. Download the file to see all of it."));
      } catch (e) { body.appendChild(el("div", "", e.message)); }
    }
    $("viewDlg").showModal();
  }

  function actBtn(label, title, fn) {
    const b = el("button", "", label); b.type = "button"; b.title = title; b.setAttribute("aria-label", title); b.addEventListener("click", fn); return b;
  }

  function updateLeft(span) {
    const s = Number(span.dataset.exp) - nowSrv();
    span.textContent = "⏳ " + fmtLeft(s);
    span.classList.toggle("soon", s < 600);
  }

  function tick() {                                 // every second: countdowns, and items vanish the moment they expire
    let gone = false;
    document.querySelectorAll(".left[data-exp]").forEach((span) => {
      if (Number(span.dataset.exp) <= nowSrv()) { gone = true; return; }
      updateLeft(span);
    });
    if (gone) { items = items.filter((i) => i.expires_at > nowSrv()); renderItems(); renderRooms(); }
  }

  // ---- editing --------------------------------------------------------------------------------------------------------
  function editorFor(it) {
    const box = el("div", "editor");
    const ta = el("textarea"); ta.value = editing.text; ta.maxLength = 20000;
    ta.addEventListener("input", () => { editing.text = ta.value; });
    ta.addEventListener("keydown", (e) => { if (e.key === "Escape") { editing = null; renderItems(); } if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); saveEdit(it); } });
    box.appendChild(ta);
    if (editing.current) {
      const w = el("div", "warn", "Changed on another device while you were editing. ");
      const use = el("button", "", "Use their version"); use.type = "button"; use.addEventListener("click", () => { editing.text = editing.current.text; editing.version = editing.current.version; editing.current = null; renderItems(); });
      const over = el("button", "", "Keep mine and overwrite"); over.type = "button"; over.style.marginLeft = "8px"; over.addEventListener("click", () => { editing.version = editing.current.version; editing.current = null; saveEdit(it); });
      w.appendChild(use); w.appendChild(over); box.appendChild(w);
    }
    const row = el("div", "erow");
    const save = el("button", "", "Save"); save.type = "button"; save.style.cssText = "background:var(--accent);color:#fff;border:none;border-radius:8px;padding:6px 14px;font-weight:600"; save.addEventListener("click", () => saveEdit(it));
    const cancel = el("button", "", "Cancel"); cancel.type = "button"; cancel.style.cssText = "background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:6px 12px"; cancel.addEventListener("click", () => { editing = null; renderItems(); });
    const lab = el("label"); const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = editing.restart; cb.addEventListener("change", () => { editing.restart = cb.checked; sel.disabled = !cb.checked; });
    lab.appendChild(cb); lab.appendChild(document.createTextNode(" restart the timer: "));
    const sel = el("select"); fillRetention(sel, editing.seconds); sel.disabled = !editing.restart; sel.addEventListener("change", () => { editing.seconds = Number(sel.value); });
    row.appendChild(save); row.appendChild(cancel); row.appendChild(lab); row.appendChild(sel); box.appendChild(row);
    return box;
  }

  async function saveEdit(it) {
    if (!editing) return;
    try {
      await api("rooms/" + encodeURIComponent(cur) + "/items/" + encodeURIComponent(it.id), "PUT",
        { text: editing.text, version: editing.version, restart_retention: editing.restart ? editing.seconds : null });
      editing = null; rev = null; await pollItems(); say("Saved");
    } catch (e) {
      if (e.status === 409 && e.data && e.data.current) { editing.current = e.data.current; renderItems(); }
      else say(e.message);
    }
  }

  // ---- item actions -----------------------------------------------------------------------------------------------------
  function openRetentionMenu(anchor, it) {
    document.querySelectorAll(".menu").forEach((m) => m.remove());
    const m = el("div", "menu");
    META.presets.forEach((p) => {
      const b = el("button", "", "Delete after " + fmtDur(p) + " from now"); b.type = "button";
      b.addEventListener("click", async () => {
        m.remove();
        try { await api("rooms/" + encodeURIComponent(cur) + "/items/" + encodeURIComponent(it.id) + "/retention", "POST", { seconds: p }); rev = null; await pollItems(); say("It will be deleted in " + fmtDur(p)); }
        catch (e) { say(e.message); }
      });
      m.appendChild(b);
    });
    const r = anchor.getBoundingClientRect();
    m.style.top = Math.min(window.innerHeight - 320, r.bottom + 4) + "px"; m.style.left = Math.max(8, r.right - 220) + "px";
    document.body.appendChild(m);
    setTimeout(() => document.addEventListener("click", function off(ev) { if (!m.contains(ev.target)) { m.remove(); document.removeEventListener("click", off); } }), 0);
  }

  async function deleteItem(it) {
    try {
      await api("rooms/" + encodeURIComponent(cur) + "/items/" + encodeURIComponent(it.id), "DELETE");
      items = items.filter((x) => x.id !== it.id); renderItems(); renderRooms();
      say("Deleted for everyone", { label: "Undo", run: async () => {
        try { await api("rooms/" + encodeURIComponent(cur) + "/items/" + encodeURIComponent(it.id) + "/undo", "POST"); rev = null; await pollItems(); say("Restored"); }
        catch (e) { say(e.message); }
      } });
      rev = null; pollItems();
    } catch (e) { say(e.message); if (e.status === 404) { rev = null; pollItems(); } }
  }

  // ---- sharing files and folders ------------------------------------------------------------------------------------------
  function renderUploads() {
    const box = $("uploads"); box.textContent = "";
    box.classList.toggle("hidden", !uploads.length);
    uploads.forEach((u) => {
      const row = el("div", "up" + (u.error ? " bad" : ""));
      row.appendChild(el("div", "nm", u.error ? u.name + " — " + u.error : "⬆ " + u.name));
      if (!u.error) { const bar = el("div", "bar"); const i = el("i"); i.style.width = Math.round(u.pct * 100) + "%"; bar.appendChild(i); row.appendChild(bar); row.appendChild(el("div", "", Math.round(u.pct * 100) + "%")); }
      const x = el("button", "", u.error ? "✕" : "Cancel"); x.type = "button"; x.title = u.error ? "Dismiss" : "Cancel this upload";
      x.addEventListener("click", () => { if (u.abort && !u.error) u.abort(); uploads = uploads.filter((q) => q !== u); renderUploads(); });
      row.appendChild(x); box.appendChild(row);
    });
  }

  async function shareBlob(blob, name, kind) {
    const limit = (META.limits && META.limits.file) || 104857600;
    if (blob.size === 0) { say("“" + name + "” is empty, so it was not shared."); return; }
    if (blob.size > limit) { say("“" + name + "” is " + fmtSize(blob.size) + ". The limit is " + fmtSize(limit) + " per upload."); return; }
    const room_ = cur, u = { name: name, pct: 0, error: null, abort: null };
    uploads.push(u); renderUploads();
    const path = "rooms/" + encodeURIComponent(room_) + "/files?name=" + encodeURIComponent(name) + "&kind=" + kind + "&retention=" + encodeURIComponent($("ret").value);
    const job = upload(path, blob, (f) => { u.pct = f; renderUploads(); });
    u.abort = job.abort;
    try {
      await job.promise;
      uploads = uploads.filter((q) => q !== u); renderUploads();
      if (room_ === cur) { rev = null; await pollItems(); const box = $("stream"); box.scrollTop = box.scrollHeight; }
    } catch (e) {
      if (e.cancelled) { uploads = uploads.filter((q) => q !== u); renderUploads(); return; }
      u.error = e.message; renderUploads();
    }
  }

  async function shareFiles(list) {
    for (const f of Array.from(list)) await shareBlob(f, f.name || "file", "file");
  }

  async function shareFolder(name, entries) {
    const limit = (META.limits && META.limits.file) || 104857600, max = (META.limits && META.limits.zip_entries) || 5000;
    if (!entries.length) { say("The folder “" + name + "” is empty."); return; }
    if (entries.length > max) { say("The folder “" + name + "” has " + entries.length + " files. The limit is " + max + "."); return; }
    const total = entries.reduce((n, e) => n + e.file.size, 0);
    if (total > limit) { say("The folder “" + name + "” is " + fmtSize(total) + ". The limit is " + fmtSize(limit) + " per upload."); return; }
    try { await shareBlob(await window.DropZip.build(entries), name + ".zip", "folder"); } catch (e) { say(e.message); }
  }

  async function shareFromPicker(files) {         // <input webkitdirectory>: each file knows its path inside the folder
    const groups = new Map();
    Array.from(files).forEach((f) => {
      const rel = f.webkitRelativePath || f.name, top = rel.split("/")[0] || "folder";
      if (!groups.has(top)) groups.set(top, []);
      groups.get(top).push({ path: rel, file: f });
    });
    for (const [name, entries] of groups) await shareFolder(name, entries);
  }

  async function walkEntry(entry, prefix, out) {
    if (entry.isFile) { const file = await new Promise((res, rej) => entry.file(res, rej)); out.push({ path: prefix + entry.name, file: file }); }
    else if (entry.isDirectory) {
      const reader = entry.createReader(); let batch;
      do { batch = await new Promise((res, rej) => reader.readEntries(res, rej)); for (const c of batch) await walkEntry(c, prefix + entry.name + "/", out); } while (batch.length);
    }
  }

  async function shareDropped(dt) {
    const roots = [];                              // must be collected synchronously: the list is invalid after the first await
    Array.from(dt.items || []).forEach((it) => { const e = it.webkitGetAsEntry && it.webkitGetAsEntry(); if (e) roots.push(e); });
    if (!roots.length) { await shareFiles(dt.files); return; }
    for (const root of roots) {
      if (root.isFile) { const f = await new Promise((res, rej) => root.file(res, rej)); await shareBlob(f, f.name, "file"); }
      else { const entries = []; await walkEntry(root, "", entries); await shareFolder(root.name, entries); }
    }
  }

  // ---- composer ---------------------------------------------------------------------------------------------------------
  async function send(ev) {
    if (ev) ev.preventDefault();
    const text = $("msg").value;
    if (!text.trim() || sending || !cur) return;
    sending = true; $("sendBtn").disabled = true;
    try {
      await api("rooms/" + encodeURIComponent(cur) + "/items", "POST", { text: text, retention: Number($("ret").value) });
      $("msg").value = ""; autoGrow(); rev = null; await pollItems();
      const box = $("stream"); box.scrollTop = box.scrollHeight;
    } catch (e) { say(e.message); }
    sending = false; $("sendBtn").disabled = false; $("msg").focus();
  }
  function autoGrow() { const t = $("msg"); t.style.height = "auto"; t.style.height = Math.min(160, t.scrollHeight) + "px"; }

  // ---- dialogs ----------------------------------------------------------------------------------------------------------
  function showErr(id, msg) { const e = $(id); e.textContent = msg || ""; e.classList.toggle("hidden", !msg); }

  function openCreate() {
    $("cName").value = ""; $("cNick").value = lsGet("droprooms.nick") || ""; fillRetention($("cRet"), META.default_retention); showErr("cErr", "");
    $("createDlg").showModal(); $("cName").focus();
  }
  function openJoin(key) {
    $("jKey").value = key || ""; $("jNick").value = lsGet("droprooms.nick") || ""; showErr("jErr", "");
    $("joinDlg").showModal(); (key ? $("jNick") : $("jKey")).focus();
  }

  function showKey(key, title, sub) {
    $("kTitle").textContent = title; $("kSub").textContent = sub; $("kBox").textContent = key;
    const link = location.origin + location.pathname + "#join=" + key;
    $("kCopyKey").onclick = async () => say((await copyText(key)) ? "Key copied" : "Copy failed");
    $("kCopyLink").onclick = async () => say((await copyText(link)) ? "Join link copied" : "Copy failed");
    $("keyDlg").showModal();
  }

  async function submitCreate(ev) {
    ev.preventDefault();
    try {
      const d = await api("rooms", "POST", { name: $("cName").value, nickname: $("cNick").value, default_retention: Number($("cRet").value) });
      lsSet("droprooms.nick", $("cNick").value.trim());
      $("createDlg").close(); cur = null; await loadRooms(); await selectRoom(d.room.id);
      showKey(d.room.key, "Room created", "Share this key. Anyone who has it can read everything in the room. You can see it again any time with the Invite button.");
    } catch (e) { showErr("cErr", e.message); }
  }
  async function submitJoin(ev) {
    ev.preventDefault();
    try {
      const d = await api("join", "POST", { key: $("jKey").value, nickname: $("jNick").value });
      lsSet("droprooms.nick", $("jNick").value.trim());
      $("jKey").value = ""; $("joinDlg").close(); cur = null; await loadRooms(); await selectRoom(d.room.id); say("Joined “" + d.room.name + "”");
    } catch (e) { showErr("jErr", e.message); }
  }

  async function openRoomDialog() {
    const r = room(); if (!r) return;
    showErr("rErr", "");
    try { detail = (await api("rooms/" + encodeURIComponent(r.id))).room; } catch (e) { say(e.message); return; }
    const owner = detail.role === "owner";
    $("rTitle").textContent = detail.name; $("rSub").textContent = owner ? "You are the owner of this room." : "You are a member of this room.";
    $("ownerBox").classList.toggle("hidden", !owner);
    $("rName").value = detail.name; fillRetention($("rRet"), detail.default_retention); $("rNick").value = detail.nickname;
    $("rReset").classList.toggle("hidden", !owner); $("rDelete").classList.toggle("hidden", !owner); $("rLeave").classList.toggle("hidden", owner);
    const box = $("rMembers"); box.textContent = "";
    detail.members.forEach((m) => {
      const row = el("div", "m"); row.appendChild(el("span", "dot" + (m.online ? " on" : "")));
      row.appendChild(el("span", "", m.nickname + (m.you ? " (you)" : "") + (m.role === "owner" ? " · owner" : "")));
      if (owner && !m.you) {
        const rm = el("button", "", "Remove"); rm.type = "button";
        rm.addEventListener("click", async () => {
          if (!confirm("Remove " + m.nickname + " from the room?")) return;
          try { await api("rooms/" + encodeURIComponent(r.id) + "/members/" + encodeURIComponent(m.id), "DELETE"); openRoomDialog(); loadRooms(); } catch (e) { showErr("rErr", e.message); }
        });
        row.appendChild(rm);
      }
      box.appendChild(row);
    });
    if (!$("roomDlg").open) $("roomDlg").showModal();
  }

  async function roomAction(fn) { try { await fn(); } catch (e) { showErr("rErr", e.message); } }

  // ---- wiring -----------------------------------------------------------------------------------------------------------
  $("createBtn").addEventListener("click", openCreate);
  $("joinBtn").addEventListener("click", () => openJoin(""));
  $("createForm").addEventListener("submit", submitCreate);
  $("joinForm").addEventListener("submit", submitJoin);
  $("composer").addEventListener("submit", send);
  $("fileBtn").addEventListener("click", () => $("filePick").click());
  $("folderBtn").addEventListener("click", () => $("folderPick").click());
  $("filePick").addEventListener("change", () => { const f = Array.from($("filePick").files); $("filePick").value = ""; if (f.length && cur) shareFiles(f); });
  $("folderPick").addEventListener("change", () => { const f = Array.from($("folderPick").files); $("folderPick").value = ""; if (f.length && cur) shareFromPicker(f); });
  let dragDepth = 0;
  const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
  document.addEventListener("dragenter", (e) => { if (cur && hasFiles(e)) { dragDepth++; $("dropzone").classList.remove("hidden"); } });
  document.addEventListener("dragover", (e) => { if (cur && hasFiles(e)) e.preventDefault(); });
  document.addEventListener("dragleave", (e) => { if (cur && hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; $("dropzone").classList.add("hidden"); } });
  document.addEventListener("drop", (e) => { if (!hasFiles(e)) return; e.preventDefault(); dragDepth = 0; $("dropzone").classList.add("hidden"); if (cur) shareDropped(e.dataTransfer); });
  document.addEventListener("paste", (e) => {      // a pasted screenshot or file is shared; pasted text just goes into the box as usual
    const files = Array.from((e.clipboardData && e.clipboardData.files) || []);
    if (!files.length || !cur) return;
    e.preventDefault();
    const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
    shareFiles(files.map((f, i) => (f.name && f.name !== "image.png") ? f : new File([f], "pasted-image-" + stamp + (files.length > 1 ? "-" + (i + 1) : "") + "." + ((f.type.split("/")[1] || "png").replace("jpeg", "jpg")), { type: f.type })));
  });
  $("msg").addEventListener("input", autoGrow);
  $("msg").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
  $("burger").addEventListener("click", () => $("side").classList.toggle("open"));
  $("settingsBtn").addEventListener("click", openRoomDialog);
  $("inviteBtn").addEventListener("click", async () => {
    try { const d = await api("rooms/" + encodeURIComponent(cur) + "/key"); showKey(d.key, "Invite to “" + room().name + "”", "Anyone who has this key can join and read everything in the room."); } catch (e) { say(e.message); }
  });
  document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));
  $("joinDlg").addEventListener("close", () => { $("jKey").value = ""; });
  $("keyDlg").addEventListener("close", () => { $("kBox").textContent = ""; $("kCopyKey").onclick = null; $("kCopyLink").onclick = null; });   // the key is not left on the page

  $("rSave").addEventListener("click", () => roomAction(async () => {
    await api("rooms/" + encodeURIComponent(cur), "PUT", { name: $("rName").value, default_retention: Number($("rRet").value) });
    await loadRooms(); fillRetention($("ret"), room().default_retention); await openRoomDialog(); say("Saved");
  }));
  $("rNickSave").addEventListener("click", () => roomAction(async () => {
    await api("rooms/" + encodeURIComponent(cur) + "/nickname", "PUT", { nickname: $("rNick").value });
    lsSet("droprooms.nick", $("rNick").value.trim()); await loadRooms(); await openRoomDialog(); say("Nickname changed");
  }));
  $("rReset").addEventListener("click", () => roomAction(async () => {
    if (!confirm("Make a new key? Everyone else is removed and must join again with the new key.")) return;
    const d = await api("rooms/" + encodeURIComponent(cur) + "/reset-key", "POST");
    $("roomDlg").close(); await loadRooms();
    showKey(d.key, "New key", "The old key no longer works and everyone else was removed. Share this new key with the people who should be in the room.");
  }));
  $("rDelete").addEventListener("click", () => roomAction(async () => {
    if (!confirm("Delete “" + room().name + "” and everything in it, for everyone? This cannot be undone.")) return;
    await api("rooms/" + encodeURIComponent(cur), "DELETE");
    $("roomDlg").close(); cur = null; await loadRooms(); say("Room deleted");
  }));
  $("rLeave").addEventListener("click", () => roomAction(async () => {
    if (!confirm("Leave this room? You need the key to join again.")) return;
    await api("rooms/" + encodeURIComponent(cur) + "/leave", "POST");
    $("roomDlg").close(); cur = null; await loadRooms(); say("You left the room");
  }));

  document.addEventListener("visibilitychange", () => { if (!document.hidden) { pollItems(); loadRooms(); } });
  setInterval(tick, 1000);
  setInterval(() => { if (!document.hidden) loadRooms(); }, 10000);

  // ---- start ------------------------------------------------------------------------------------------------------------
  (async function start() {
    try { META = Object.assign(META, await api("meta")); } catch (e) { /* defaults */ }
    await loadRooms();
    if (!rooms.length) renderItems();
    schedulePoll();
    const m = location.hash.match(/join=([A-Za-z0-9\-\s]+)/);                  // a join link: #join=KEY (the fragment never goes to the server)
    if (m) { history.replaceState(null, "", location.pathname + location.search); openJoin(m[1].trim()); }
  })();
})();
