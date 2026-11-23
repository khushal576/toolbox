/* Drop Rooms: builds a ZIP (no compression, "store" method) from a folder's files, in the browser. No DOM here, so node can test it
   (tests/unit/drop_rooms_zip_cases.js, verified with Python's own zipfile). The server never trusts it: store.check_zip re-validates the
   upload. Paths are cleaned here too, so a folder can never produce entries like "../x" or "/etc/x". */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.DropZip = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const TABLE = (function () {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
    return t;
  })();

  function crc32(bytes) {
    let c = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) c = TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  /* "photos\\2024/../a.jpg" -> "photos/2024/a.jpg"; throws when nothing usable is left. */
  function cleanPath(p) {
    const parts = String(p || "").replace(/\\/g, "/").split("/").map((s) => s.replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0, 200)).filter((s) => s && s !== "." && s !== "..");
    if (!parts.length) throw new Error("A file in the folder has no usable name.");
    return parts.join("/");
  }

  function dosDateTime(ms) {
    const d = new Date(Math.max(ms || Date.now(), Date.UTC(1980, 0, 2)));
    const year = Math.min(Math.max(d.getFullYear(), 1980), 2107);
    return {
      time: ((d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1)) & 0xFFFF,
      date: (((year - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate()) & 0xFFFF,
    };
  }

  function uniqueName(name, used) {
    if (!used.has(name)) { used.add(name); return name; }
    const dot = name.lastIndexOf("."), base = dot > name.lastIndexOf("/") + 1 ? name.slice(0, dot) : name, ext = dot > name.lastIndexOf("/") + 1 ? name.slice(dot) : "";
    for (let i = 2; ; i++) { const n = base + " (" + i + ")" + ext; if (!used.has(n)) { used.add(n); return n; } }
  }

  /* entries: [{path, file}] where `file` has arrayBuffer() (a File/Blob) and optionally lastModified; or [{path, data: Uint8Array}].
     Returns a Blob of type application/zip. */
  async function build(entries) {
    if (!entries.length) throw new Error("The folder is empty.");
    if (entries.length > 65000) throw new Error("The folder has too many files.");
    const enc = new TextEncoder(), used = new Set(), parts = [], central = [];
    let offset = 0;
    for (const e of entries) {
      const name = uniqueName(cleanPath(e.path), used), nameBytes = enc.encode(name);
      const data = e.data ? e.data : new Uint8Array(await e.file.arrayBuffer());
      const crc = crc32(data), dt = dosDateTime(e.lastModified || (e.file && e.file.lastModified));
      const lh = new DataView(new ArrayBuffer(30));
      lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint16(6, 0x0800, true); lh.setUint16(8, 0, true);
      lh.setUint16(10, dt.time, true); lh.setUint16(12, dt.date, true); lh.setUint32(14, crc, true);
      lh.setUint32(18, data.length, true); lh.setUint32(22, data.length, true); lh.setUint16(26, nameBytes.length, true); lh.setUint16(28, 0, true);
      parts.push(lh.buffer, nameBytes, data);
      const ch = new DataView(new ArrayBuffer(46));
      ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true); ch.setUint16(8, 0x0800, true); ch.setUint16(10, 0, true);
      ch.setUint16(12, dt.time, true); ch.setUint16(14, dt.date, true); ch.setUint32(16, crc, true);
      ch.setUint32(20, data.length, true); ch.setUint32(24, data.length, true); ch.setUint16(28, nameBytes.length, true);
      ch.setUint16(30, 0, true); ch.setUint16(32, 0, true); ch.setUint16(34, 0, true); ch.setUint16(36, 0, true); ch.setUint32(38, 0, true); ch.setUint32(42, offset, true);
      central.push(ch.buffer, nameBytes);
      offset += 30 + nameBytes.length + data.length;
      if (offset > 0xFFFFFFF0) throw new Error("The folder is too big to zip.");
    }
    let cdSize = 0;
    for (const c of central) cdSize += c.byteLength;
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(4, 0, true); end.setUint16(6, 0, true);
    end.setUint16(8, entries.length, true); end.setUint16(10, entries.length, true); end.setUint32(12, cdSize, true); end.setUint32(16, offset, true); end.setUint16(20, 0, true);
    return new Blob(parts.concat(central, [end.buffer]), { type: "application/zip" });
  }

  return { build, cleanPath, crc32 };
});
