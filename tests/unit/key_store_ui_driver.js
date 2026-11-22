// Key Store (roadmap KS2): the page driver, injected by tests/unit/test_key_store_ui.py into a page served from a TEMPORARY vault.
// It clicks through the real UI and posts {check name: true/false} to /__result.
(async () => {
  const results = {};
  const ok = (name, cond, detail) => { results[name] = !!cond; if (!cond) results[name + " [detail]"] = String(detail === undefined ? "" : detail); };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const $ = (id) => document.getElementById(id);
  const until = async (fn, ms) => { const t = Date.now(); while (Date.now() - t < (ms || 5000)) { try { if (fn()) return true; } catch (e) { /* keep waiting */ } await sleep(40); } return false; };
  let clip = null;
  Object.defineProperty(navigator, "clipboard", { value: { writeText: async (t) => { clip = t; } }, configurable: true });
  window.confirm = () => true;
  const names = () => Array.from(document.querySelectorAll("#list .entry .etitle span:first-child")).map((n) => n.textContent);
  const rowOf = (name) => Array.from(document.querySelectorAll("#list .entry")).find((r) => r.querySelector(".etitle span").textContent === name);
  const btn = (row, title) => row.querySelector('button[title="' + title + '"]');
  const copyBtn = (row) => Array.from(row.querySelectorAll("button")).find((b) => b.textContent === "Copy");
  const search = async (q, inValues) => { $("fValues").checked = !!inValues; $("q").value = q; $("q").dispatchEvent(new Event("input")); await sleep(450); };
  async function fillAndSave(o) {
    await until(() => $("dlg").open);
    $("eName").value = o.name; $("eType").value = o.type;
    if (o.value !== undefined) $("eValue").value = o.value;
    document.querySelector('input[name="eEnv"][value="' + (o.env || "") + '"]').checked = true;
    for (const t of o.tags || []) { $("eTagIn").value = t; $("eTagIn").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); }
    $("eNote").value = o.note || "";
    $("dlgForm").requestSubmit();
    return until(() => !$("dlg").open, 4000);
  }
  try {
    localStorage.clear();
    ok("starts on the generator tab", !$("paneGen").classList.contains("hidden") && $("paneStore").classList.contains("hidden"));
    $("tabStore").click();
    ok("empty state on a fresh vault", await until(() => $("list").textContent.includes("Nothing saved yet")));
    ok("type filter lists the types", $("fType").options.length >= 9);

    // ---- generator -> Save to Store -----------------------------------------------------------------------------------
    $("tabGen").click();
    const pw = $("result").textContent;
    ok("generated a password", pw.length === 20);
    $("saveBtn").click();
    ok("save switches to the store and opens the form prefilled", await until(() => $("dlg").open && !$("paneStore").classList.contains("hidden")) && $("eValue").value === pw && $("eType").value === "password");
    ok("saved the generated password", await fillAndSave({ name: "Billing DB", type: "password", env: "prod", tags: ["billing", "db"], note: "main cluster" }) && await until(() => names().includes("Billing DB")));

    $("newBtn").click(); await fillAndSave({ name: "Docs", type: "url", value: "https://example.com/docs", tags: ["docs"] });
    $("newBtn").click(); await fillAndSave({ name: "Slack hook", type: "url", value: "https://hooks.slack.com/services/T0/B0/AAAAAAAAAAAAAAAAAAAAAAAA", tags: ["chat"] });
    $("newBtn").click(); await fillAndSave({ name: "Wifi", type: "password", value: "wifi-pass-123", env: "non-prod", tags: ["home"], note: "router" });
    await until(() => names().length === 4);
    ok("four entries listed", names().length === 4 && $("storeCount").textContent === "4", names());
    ok("prod badge shown", rowOf("Billing DB").querySelector(".b2.prod") !== null);
    ok("a plain URL shows its preview", rowOf("Docs").textContent.includes("https://example.com/docs"));
    ok("a webhook URL stays masked", !rowOf("Slack hook").textContent.includes("hooks.slack.com"));
    ok("no secret value on screen", !document.body.innerText.includes(pw) && !document.body.innerText.includes("wifi-pass-123"));
    ok("nothing secret in localStorage", !JSON.stringify(localStorage).includes(pw) && !JSON.stringify(localStorage).includes("wifi-pass"), JSON.stringify(localStorage));

    // ---- search, filters ---------------------------------------------------------------------------------------------
    await search("billing"); ok("search by tag", names().join() === "Billing DB", names());
    await search("router"); ok("search by note", names().join() === "Wifi", names());
    await search("zzz nothing"); ok("no-match message", $("list").textContent.includes("No match"));
    await search("wifi-pass"); ok("values are not searched by default", names().length === 0);
    await search("wifi-pass", true); ok("values are searched when asked", names().join() === "Wifi", names());
    ok("a value search does not reveal the value", !document.body.innerText.includes("wifi-pass-123"));
    await search("");
    $("fEnv").value = "prod"; $("fEnv").dispatchEvent(new Event("change")); await sleep(400);
    ok("environment filter", names().join() === "Billing DB", names());
    $("fEnv").value = ""; $("fEnv").dispatchEvent(new Event("change")); await sleep(300);
    $("fType").value = "url"; $("fType").dispatchEvent(new Event("change")); await sleep(300);
    ok("type filter", names().join() === "Docs,Slack hook", names());
    $("fType").value = ""; $("fType").dispatchEvent(new Event("change")); await sleep(300);
    const chip = Array.from(document.querySelectorAll("#tagbar .chip")).find((c) => c.textContent.startsWith("home"));
    chip.click(); await sleep(400); ok("tag chip filter", names().join() === "Wifi", names());
    Array.from(document.querySelectorAll("#tagbar .chip")).find((c) => c.classList.contains("on")).click(); await sleep(400);
    ok("tag chip clears", names().length === 4);

    // ---- copy, Enter, reveal -----------------------------------------------------------------------------------------
    copyBtn(rowOf("Billing DB")).click(); ok("Copy puts the real value on the clipboard", await until(() => clip === pw), clip);
    ok("copy toast mentions PROD", $("toast2").textContent.includes("PROD"));
    clip = null; await search("wifi"); $("q").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    ok("Enter copies the first result", await until(() => clip === "wifi-pass-123"), clip);
    await search("");
    btn(rowOf("Billing DB"), "Show the value for 10 seconds").click();
    ok("eye reveals the value", await until(() => rowOf("Billing DB").querySelector(".evalue").textContent === pw));
    ok("revealed value masks itself again", await until(() => rowOf("Billing DB").querySelector(".evalue").classList.contains("masked"), 13000));

    // ---- edit ---------------------------------------------------------------------------------------------------------
    btn(rowOf("Wifi"), "Edit").click();
    ok("edit form loads the value", await until(() => $("dlg").open && $("eValue").value === "wifi-pass-123"));
    ok("the value is masked in the form", $("eValue").classList.contains("hiddenval"));
    $("eNote").value = "router, 5 GHz"; $("dlgForm").requestSubmit(); await until(() => !$("dlg").open);
    clip = null; copyBtn(rowOf("Wifi")).click(); await until(() => clip !== null);
    ok("an edit that leaves the value alone keeps it", clip === "wifi-pass-123", clip);
    ok("note updated", await until(() => rowOf("Wifi").textContent.includes("5 GHz")));
    btn(rowOf("Wifi"), "Edit").click(); await until(() => $("dlg").open);
    $("eName").value = "docs"; $("dlgForm").requestSubmit(); await sleep(500);
    ok("duplicate names are refused, form stays open", $("dlg").open && $("dlgError").textContent.includes("already exists"), $("dlgError").textContent);
    $("dlgCancel").click(); await sleep(200);
    ok("the closed form is empty", $("eValue").value === "");

    // ---- pin, duplicate, trash, undo, delete forever -----------------------------------------------------------------
    btn(rowOf("Wifi"), "Pin to the top").click(); await until(() => names()[0] === "Wifi" && rowOf("Wifi").textContent.includes("📌"));
    ok("pinned entry comes first", names()[0] === "Wifi", names());
    btn(rowOf("Billing DB"), "Duplicate").click(); await until(() => names().includes("Billing DB (copy)"));
    ok("duplicate created", names().includes("Billing DB (copy)"), names());
    btn(rowOf("Docs"), "Move to trash").click(); await until(() => !names().includes("Docs"));
    ok("trashed entry leaves the list", !names().includes("Docs"));
    ok("undo offered", $("toast2").textContent.includes("Undo"));
    $("toast2").querySelector("button").click(); await until(() => names().includes("Docs"));
    ok("undo restores it", names().includes("Docs"), names());
    btn(rowOf("Slack hook"), "Move to trash").click(); await until(() => !names().includes("Slack hook"));
    $("trashToggle").click(); await until(() => $("list").textContent.includes("Slack hook"));
    ok("trash view lists it", $("list").textContent.includes("Slack hook") && $("listInfo").textContent.includes("30 days"));
    Array.from(document.querySelectorAll("#list button")).find((b) => b.textContent === "Delete forever").click(); await until(() => $("list").textContent.includes("trash is empty"));
    ok("delete forever removes it", !$("list").textContent.includes("Slack hook") && $("list").textContent.includes("trash is empty"));
    $("trashToggle").click(); await sleep(400);

    ok("end: still no secret on screen or in storage",
       !document.body.innerText.includes(pw) && !document.body.innerText.includes("wifi-pass-123") && !JSON.stringify(localStorage).includes(pw));
  } catch (e) {
    ok("driver crashed", false, e && e.stack || e);
  }
  await fetch("/__result", { method: "POST", body: JSON.stringify(results) });
})();
