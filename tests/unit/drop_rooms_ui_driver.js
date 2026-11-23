// Drop Rooms (roadmap DR1): driver injected by tests/unit/test_drop_rooms_ui.py. TWO browsers run it, as role A and role B (?role=A|B), against one
// real server; they coordinate through /__kv/<name> and report {check: true/false} to /__result?role=...
(async () => {
  const role = new URLSearchParams(location.search).get("role");
  const results = {};
  const ok = (name, cond, detail) => { results[name] = !!cond; if (!cond) results[name + " [detail]"] = String(detail === undefined ? "" : detail); };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const $ = (id) => document.getElementById(id);
  const until = async (fn, ms) => { const t = Date.now(); while (Date.now() - t < (ms || 12000)) { try { if (fn()) return true; } catch (e) { /* keep waiting */ } await sleep(60); } return false; };
  const kvSet = (k, v) => fetch("/__kv/" + k, { method: "POST", body: v === undefined ? "1" : v });
  const kvGet = async (k) => (await (await fetch("/__kv/" + k)).text());
  const kvWait = async (k, ms) => { const t = Date.now(); while (Date.now() - t < (ms || 60000)) { const v = await kvGet(k); if (v) return v; await sleep(150); } return ""; };
  let clip = null;
  Object.defineProperty(navigator, "clipboard", { value: { writeText: async (t) => { clip = t; } }, configurable: true });
  window.confirm = () => true;
  const texts = () => Array.from(document.querySelectorAll("#stream .item .txt")).map((n) => n.textContent);
  const itemWith = (t) => Array.from(document.querySelectorAll("#stream .item")).find((r) => { const x = r.querySelector(".txt"); return x && x.textContent === t; });
  const act = (row, titleStart) => Array.from(row.querySelectorAll(".acts button")).find((b) => b.title.startsWith(titleStart));
  const typeAndSend = async (t) => { $("msg").value = t; $("msg").dispatchEvent(new Event("input")); $("msg").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); };
  const PNGB = Uint8Array.from(atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="), (c) => c.charCodeAt(0));
  const mk = (name, bytes, type) => new File([bytes], name, { type });
  const share = (input, files) => { Object.defineProperty(input, "files", { configurable: true, get: () => files }); input.dispatchEvent(new Event("change")); };
  const cardWith = (name) => Array.from(document.querySelectorAll("#stream .file")).find((c) => c.querySelector(".fname").textContent === name);
  const thumbOf = (name) => { const c = cardWith(name); return c && c.parentElement.querySelector("img.thumb"); };
  const membersText = async () => { $("settingsBtn").click(); await until(() => $("roomDlg").open && $("rMembers").children.length > 0); const t = Array.from($("rMembers").children).map((r) => r.textContent).join(" | "); return t; };

  try {
    if (role === "A") {
      ok("A: starts on the welcome screen", await until(() => document.querySelector("#stream .empty b") && document.querySelector("#stream .empty b").textContent === "Welcome to Drop Rooms"));
      ok("A: composer hidden before any room", $("composer").classList.contains("hidden"));
      $("createBtn").click();
      await until(() => $("createDlg").open);
      $("cName").value = "Team room"; $("cNick").value = "Laptop";
      ok("A: default retention is 6 hours", $("cRet").value === "21600" && $("cRet").selectedOptions[0].textContent === "6 hours");
      $("createForm").requestSubmit();
      ok("A: key dialog shows a formatted key", await until(() => $("keyDlg").open && /^[0-9A-Z]{5}(-[0-9A-Z]{5}){4}$/.test($("kBox").textContent)));
      const key = $("kBox").textContent;
      $("kCopyKey").click(); await until(() => clip === key);
      ok("A: Copy key copies the key", clip === key, clip);
      $("kCopyLink").click(); await until(() => clip && clip.includes("#join="));
      ok("A: join link carries the key in the fragment", clip === location.origin + location.pathname + "#join=" + key, clip);
      $("keyDlg").close();
      ok("A: the key is gone from the page after closing", await until(() => $("kBox").textContent === "" && !document.body.innerText.includes(key), 3000));
      ok("A: room selected and composer shown", $("roomName").textContent === "Team room" && !$("composer").classList.contains("hidden"));
      await kvSet("key", key);

      await typeAndSend("hello from laptop");
      ok("A: own message appears", await until(() => itemWith("hello from laptop")));
      const left = itemWith("hello from laptop").querySelector(".left").textContent;
      ok("A: shows a countdown of about 6 hours", /5 h 5\d min|6 h 0 min/.test(left), left);
      ok("A: message input cleared", $("msg").value === "");

      await kvWait("bjoined");
      ok("A: sees B's device in the room", (await membersText()).includes("Phone"), "members");
      $("roomDlg").close();
      await kvWait("b_sent");
      ok("A: sees B's message without reloading", await until(() => itemWith("reply from phone"), 15000));
      await kvWait("b_edited");
      ok("A: sees B's edit of A's message", await until(() => itemWith("hello from the laptop (edited)"), 15000));
      ok("A: shows who edited", itemWith("hello from the laptop (edited)").querySelector(".edited").textContent.includes("edited by Phone"));
      await kvSet("a_saw_edit");

      act(itemWith("reply from phone"), "Delete").click();
      ok("A: deleting removes it at once", await until(() => !itemWith("reply from phone")));
      ok("A: Undo is offered", $("toast").classList.contains("show") && $("toast").textContent.includes("Undo"));
      await kvSet("a_deleted");
      await kvWait("b_saw_delete");
      $("toast").querySelector("button").click();
      ok("A: undo within 10 s brings it back", await until(() => itemWith("reply from phone")));
      await kvSet("a_undone");
      await kvWait("b_saw_undo");

      // ---- files and folders ----
      share($("filePick"), [mk("notes.txt", "file contents from A", "text/plain"), mk("pic.png", PNGB, "image/png")]);
      ok("A: shared files appear as file cards", await until(() => cardWith("notes.txt") && cardWith("pic.png"), 15000));
      ok("A: a card shows the size", cardWith("notes.txt") && cardWith("notes.txt").querySelector(".fmeta").textContent === "20 bytes", cardWith("notes.txt") && cardWith("notes.txt").textContent);
      ok("A: an image gets a thumbnail", await until(() => { const i = thumbOf("pic.png"); return i && i.complete && i.naturalWidth === 1; }));
      ok("A: the upload row is gone when the upload is done", !document.querySelector("#uploads .up"));
      const huge = mk("huge.bin", "x", "application/octet-stream"); Object.defineProperty(huge, "size", { value: 200 * 1024 * 1024 });
      share($("filePick"), [huge]);
      ok("A: a file over the limit is refused with a clear message and nothing is uploaded", await until(() => $("toast").textContent.includes("limit is 100.0 MB")) && !document.querySelector("#uploads .up") && !cardWith("huge.bin"), $("toast").textContent);
      const f1 = mk("a.txt", "folder file A", "text/plain"); Object.defineProperty(f1, "webkitRelativePath", { value: "Docs/a.txt" });
      const f2 = mk("b.txt", "folder file B", "text/plain"); Object.defineProperty(f2, "webkitRelativePath", { value: "Docs/sub/b.txt" });
      share($("folderPick"), [f1, f2]);
      ok("A: a folder is shared as one ZIP item with its file count", await until(() => cardWith("Docs.zip") && cardWith("Docs.zip").querySelector(".fmeta").textContent.includes("2 files (ZIP)"), 15000), cardWith("Docs.zip") && cardWith("Docs.zip").textContent);
      await kvSet("a_files");
      await kvWait("b_pasted");
      ok("A: sees the image B pasted", await until(() => Array.from(document.querySelectorAll(".file .fname")).some((n) => /^pasted-image-\d+\.png$/.test(n.textContent)), 15000));
      const noteRow = cardWith("notes.txt").closest(".item");
      Array.from(noteRow.querySelectorAll(".acts button")).find((b) => b.title.startsWith("Delete")).click();
      ok("A: deleting a file removes its card", await until(() => !cardWith("notes.txt")));
      await kvSet("a_deleted_file");
      await kvWait("b_saw_file_gone");

      act(itemWith("hello from the laptop (edited)"), "Change when").click();
      await until(() => document.querySelector(".menu"));
      Array.from(document.querySelectorAll(".menu button")).find((b) => b.textContent.includes("1 hour")).click();
      ok("A: shortening one item's life updates its countdown", await until(() => /^⏳ (5\d min|1 h 0 min)/.test(itemWith("hello from the laptop (edited)").querySelector(".left").textContent), 8000),
         itemWith("hello from the laptop (edited)").querySelector(".left").textContent);

      $("settingsBtn").click(); await until(() => $("roomDlg").open && !$("ownerBox").classList.contains("hidden"));
      ok("A: owner sees the owner controls", !$("rReset").classList.contains("hidden") && $("rLeave").classList.contains("hidden"));
      $("rReset").click();
      ok("A: reset shows a different key", await until(() => $("keyDlg").open && $("kBox").textContent && $("kBox").textContent !== key));
      const newKey = $("kBox").textContent;
      await kvSet("newkey", newKey);
      $("keyDlg").close();
      ok("A: owner keeps the room and its content after a reset", $("roomName").textContent === "Team room" && !!itemWith("hello from the laptop (edited)"));
      await kvWait("b_rejoined");
      ok("A: sees B back in the room", (await membersText()).includes("Phone"));
      $("roomDlg").close();
      $("settingsBtn").click(); await until(() => $("roomDlg").open); $("rDelete").click();
      ok("A: deleting the room returns to the welcome screen", await until(() => document.querySelector("#stream .empty b") && document.querySelector("#stream .empty b").textContent === "Welcome to Drop Rooms"));
      await kvSet("a_deleted_room");
    }

    if (role === "B") {
      ok("B: starts on the welcome screen", await until(() => document.querySelector("#stream .empty b")));
      const key = await kvWait("key");
      $("joinBtn").click(); await until(() => $("joinDlg").open);
      $("jKey").value = "zzzzz-zzzzz-zzzzz-zzzzz-zzzzz"; $("jNick").value = "Phone"; $("joinForm").requestSubmit();
      ok("B: a wrong key is refused with a plain message", await until(() => !$("jErr").classList.contains("hidden") && $("jErr").textContent.includes("does not match")), $("jErr").textContent);
      $("jKey").value = key.toLowerCase(); $("joinForm").requestSubmit();
      ok("B: joins with the key (typed in lower case)", await until(() => $("roomName").textContent === "Team room" && !$("joinDlg").open));
      ok("B: sees A's earlier message", await until(() => itemWith("hello from laptop")));
      ok("B: A's message is marked as A's", itemWith("hello from laptop").querySelector(".who b").textContent === "Laptop");
      await kvSet("bjoined");
      await typeAndSend("reply from phone");
      ok("B: own message appears", await until(() => itemWith("reply from phone")));
      await kvSet("b_sent");

      const row = itemWith("hello from laptop");
      act(row, "Edit").click();
      await until(() => document.querySelector(".editor textarea"));
      const ta = document.querySelector(".editor textarea");
      ta.value = "hello from the laptop (edited)"; ta.dispatchEvent(new Event("input"));
      Array.from(document.querySelectorAll(".editor button")).find((b) => b.textContent === "Save").click();
      ok("B: edits A's message", await until(() => itemWith("hello from the laptop (edited)") && !document.querySelector(".editor")));
      await kvSet("b_edited");
      await kvWait("a_saw_edit");

      await kvWait("a_deleted");
      ok("B: sees A delete B's message, without reloading", await until(() => !itemWith("reply from phone"), 15000));
      await kvSet("b_saw_delete");
      await kvWait("a_undone");
      ok("B: sees the undo bring it back", await until(() => itemWith("reply from phone"), 15000));
      await kvSet("b_saw_undo");

      // ---- files and folders ----
      await kvWait("a_files");
      ok("B: sees A's files and folder without reloading", await until(() => cardWith("notes.txt") && cardWith("pic.png") && cardWith("Docs.zip"), 15000));
      const link = cardWith("notes.txt").querySelector("a.dl");
      const resp = await fetch(link.href);
      ok("B: downloads exactly the bytes A shared", resp.status === 200 && (await resp.text()) === "file contents from A");
      ok("B: a download is an attachment of opaque bytes", resp.headers.get("content-type") === "application/octet-stream" && resp.headers.get("content-disposition").startsWith("attachment") && resp.headers.get("x-content-type-options") === "nosniff", resp.headers.get("content-disposition"));
      ok("B: the download link keeps the file name", link.getAttribute("download") === "notes.txt");
      ok("B: the image thumbnail loads", await until(() => { const i = thumbOf("pic.png"); return i && i.complete && i.naturalWidth === 1; }));
      thumbOf("pic.png").click();
      ok("B: clicking a thumbnail opens a viewer with the image", await until(() => $("viewDlg").open && $("vBody").querySelector("img") && $("vBody").querySelector("img").complete));
      $("viewDlg").close();
      cardWith("notes.txt").querySelector("button.pv").click();
      ok("B: Preview shows a text file as plain text", await until(() => $("viewDlg").open && $("vBody").querySelector("pre") && $("vBody").querySelector("pre").textContent === "file contents from A"));
      $("viewDlg").close();
      ok("B: an image-less file has no thumbnail and a ZIP has no preview button", !thumbOf("notes.txt") && !cardWith("Docs.zip").querySelector("button.pv"));
      const zbytes = new Uint8Array(await (await fetch(cardWith("Docs.zip").querySelector("a.dl").href)).arrayBuffer());
      await kvSet("zipdata", btoa(Array.from(zbytes, (b) => String.fromCharCode(b)).join("")));
      ok("B: the folder downloads as a real ZIP", zbytes[0] === 0x50 && zbytes[1] === 0x4b);
      const dt = new DataTransfer(); dt.items.add(mk("image.png", PNGB, "image/png"));
      document.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
      ok("B: pasting an image shares it as pasted-image-….png", await until(() => Array.from(document.querySelectorAll(".file .fname")).some((n) => /^pasted-image-\d+\.png$/.test(n.textContent)), 15000));
      await kvSet("b_pasted");
      await kvWait("a_deleted_file");
      ok("B: a deleted file disappears for B too", await until(() => !cardWith("notes.txt"), 15000));
      ok("B: and its download link stops working", (await fetch(link.href)).status === 404);
      await kvSet("b_saw_file_gone");

      const newKey = await kvWait("newkey");
      ok("B: is removed from the room when the owner resets the key", await until(() => $("roomName").textContent !== "Team room" && !rooms_visible(), 20000));
      function rooms_visible() { return Array.from(document.querySelectorAll("#roomList .room")).some((r) => r.textContent.includes("Team room")); }
      $("joinBtn").click(); await until(() => $("joinDlg").open);
      $("jKey").value = key; $("jNick").value = "Phone"; $("joinForm").requestSubmit();
      ok("B: the OLD key no longer works", await until(() => $("jErr").textContent.includes("does not match")), $("jErr").textContent);
      $("jKey").value = newKey; $("joinForm").requestSubmit();
      ok("B: the new key works", await until(() => $("roomName").textContent === "Team room" && !$("joinDlg").open));
      ok("B: content survived the reset", await until(() => itemWith("hello from the laptop (edited)")));
      await kvSet("b_rejoined");
      await kvWait("a_deleted_room");
      ok("B: the deleted room disappears for B too", await until(() => !rooms_visible() && document.querySelector("#stream .empty b"), 20000));
    }
  } catch (e) {
    ok(role + ": driver crashed", false, e && e.stack || e);
  }
  await fetch("/__result?role=" + role, { method: "POST", body: JSON.stringify(results) });
})();
