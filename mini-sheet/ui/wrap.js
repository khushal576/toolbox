/* mini-sheet/ui/wrap.js — how many lines a piece of text takes inside a column of a given width (roadmap M2, "Wrap text").
 *
 * Pure functions, no DOM: the page hands in `measure(text) → pixel width` (a canvas 2D context with the cell's real font),
 * the tests hand in a fake monospace one. The rules mirror what the browser does to a wrapped cell
 * (`white-space: pre-wrap; overflow-wrap: anywhere`): line breaks in the text are kept, words wrap at spaces, and a single
 * word that is wider than the column is cut into pieces that each fill a line.
 *
 * Works in the browser (window.MSWrap) and in node (module.exports).
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.MSWrap = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const MAX_LINES = 40;                  // a row never grows beyond this many lines (the cell shows "…" and the whole text on hover)

  /** The longest prefix of `word` (at least 1 character) that fits in `avail` pixels, by binary search on measure(). */
  function fitPrefix(word, avail, measure) {
    let lo = 1, hi = word.length;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (measure(word.slice(0, mid)) <= avail) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  // lines taken by ONE paragraph (text without a line break); stops counting at `limit`
  function paragraphLines(para, avail, measure, limit) {
    if (para === "" || measure(para) <= avail) return 1;
    let n = 0, line = "";
    const words = para.split(" ");
    for (let i = 0; i < words.length; i++) {
      let word = words[i];
      if (line !== "") {
        const joined = line + " " + word;
        if (measure(joined) <= avail) { line = joined; continue; }
        n++; line = "";                                                // the current line is full: start a new one with this word
        if (n >= limit) return n;
      }
      while (word.length > 1 && measure(word) > avail) {              // a word wider than the column is cut into full lines
        word = word.slice(fitPrefix(word, avail, measure));
        n++;
        if (n >= limit) return n;
      }
      line = word;
    }
    return n + 1;                                                      // the last, partly filled line
  }

  /**
   * countLines(text, availWidth, measure, maxLines?) → { lines, truncated }
   *   lines     1 … maxLines (an empty text is 1 line)
   *   truncated true when the text needs more than maxLines (counting stops there)
   */
  function countLines(text, availWidth, measure, maxLines) {
    const cap = maxLines || MAX_LINES;
    const s = text === null || text === undefined ? "" : String(text);
    if (s === "") return { lines: 1, truncated: false };
    const avail = Math.max(1, availWidth);
    let lines = 0;
    const paras = s.replace(/\r\n?/g, "\n").split("\n");
    for (let p = 0; p < paras.length; p++) {
      lines += paragraphLines(paras[p], avail, measure, cap - lines + 1);
      if (lines > cap) return { lines: cap, truncated: true };
    }
    return { lines, truncated: false };
  }

  /** A fast guess (no measuring): `charW` = the average character width in pixels. Used for rows that are not on screen yet. */
  function estimateLines(text, availWidth, charW, maxLines) {
    const cap = maxLines || MAX_LINES;
    if (text === null || text === undefined) return 1;
    const s = String(text);
    if (s === "") return 1;
    const perLine = Math.max(1, Math.floor(Math.max(1, availWidth) / Math.max(1, charW)));
    let lines = 0;
    let at = 0;
    for (;;) {
      const nl = s.indexOf("\n", at);
      const len = (nl < 0 ? s.length : nl) - at;
      lines += Math.max(1, Math.ceil(len / perLine));
      if (lines >= cap || nl < 0) break;
      at = nl + 1;
    }
    return Math.min(cap, lines);
  }

  /** The pixel height of a row whose tallest wrapped cell has `lines` lines (single line = the normal 26 px row). */
  function rowHeight(lines, lineHeight, minHeight) {
    const min = minHeight || 26;
    return lines <= 1 ? min : Math.max(min, lines * lineHeight + 9);
  }

  return { MAX_LINES, countLines, estimateLines, rowHeight, fitPrefix };
});
