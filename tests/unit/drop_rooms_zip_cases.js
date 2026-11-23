// Drop Rooms (roadmap DR2): builds ZIPs with ui/zip.js and writes them to the directory given as argv[2]; tests/unit/test_drop_rooms_zip.py
// then verifies them with Python's own zipfile (the independent reader). Prints "OK" or the first failure.
const path = require("path");
const fs = require("fs");
const Z = require(path.join(__dirname, "..", "..", "drop-rooms", "ui", "zip.js"));
const out = process.argv[2];
let n = 0;
const check = (c, m) => { n++; if (!c) { console.error("FAIL: " + m); process.exit(1); } };

(async () => {
  check(Z.crc32(new TextEncoder().encode("123456789")) === 0xCBF43926, "crc32 of the standard test vector");
  check(Z.cleanPath("photos\\2024/../a.jpg") === "photos/2024/a.jpg", "backslashes and .. are cleaned");
  check(Z.cleanPath("/etc/passwd") === "etc/passwd" && Z.cleanPath("./a/./b") === "a/b" && Z.cleanPath("C:/x") === "C:/x", "absolute and dot segments");
  let threw = 0;
  for (const bad of ["", "..", "../..", "//", "\u0000"]) { try { Z.cleanPath(bad); } catch (e) { threw++; } }
  check(threw === 5, "nothing-usable paths throw");

  const file = (name, text) => ({ path: name, file: new Blob([text]), lastModified: Date.UTC(2026, 10, 22, 9, 30, 0) });
  const big = new Uint8Array(300000); for (let i = 0; i < big.length; i++) big[i] = (i * 7 + 3) & 255;
  const entries = [
    file("My Folder/readme.txt", "hello zip\n"),
    file("My Folder/sub/ünïcode — файл.txt", "unicode name ok"),
    file("My Folder/sub/empty.txt", ""),
    { path: "My Folder/data.bin", data: big },
    file("My Folder/dup.txt", "first"), file("My Folder/dup.txt", "second"),
    file("../../escape.txt", "must stay inside"), file("/abs/evil.txt", "no absolute"),
  ];
  const blob = await Z.build(entries);
  check(blob.type === "application/zip" && blob.size > 300000, "a zip blob comes out");
  fs.writeFileSync(path.join(out, "folder.zip"), Buffer.from(await blob.arrayBuffer()));
  fs.writeFileSync(path.join(out, "bin.expected"), Buffer.from(big));

  let emptyThrew = false;
  try { await Z.build([]); } catch (e) { emptyThrew = true; }
  check(emptyThrew, "an empty folder throws");
  console.log("OK " + n);
})().catch((e) => { console.error("FAIL: crashed " + (e && e.stack || e)); process.exit(1); });
