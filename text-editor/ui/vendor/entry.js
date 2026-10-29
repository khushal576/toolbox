export { EditorView, basicSetup } from "codemirror";
export { EditorState, EditorSelection, Compartment, StateEffect, StateField } from "@codemirror/state";
export { keymap, Decoration, ViewPlugin, lineNumbers } from "@codemirror/view";
export { addCursorAbove, addCursorBelow, indentWithTab } from "@codemirror/commands";
export { search, openSearchPanel, SearchQuery, setSearchQuery, getSearchQuery, selectNextOccurrence } from "@codemirror/search";
export { foldAll, unfoldAll, indentUnit, syntaxTree } from "@codemirror/language";
export { json } from "@codemirror/lang-json";
export { xml } from "@codemirror/lang-xml";
export { html } from "@codemirror/lang-html";
export { linter, lintGutter, setDiagnostics, forceLinting } from "@codemirror/lint";
export { MergeView, goToNextChunk, goToPreviousChunk, getChunks } from "@codemirror/merge";
import beautify from "js-beautify";
export const html_beautify = beautify.html;
export { python } from "@codemirror/lang-python";
export { sql, PostgreSQL } from "@codemirror/lang-sql";
export { format as sqlFormat } from "sql-formatter";
import ruffInit, { format as ruffFormat } from "@wasm-fmt/ruff_fmt/web";
// Python is formatted by ruff compiled to WebAssembly (Black-compatible); the .wasm is a separate file the page names.
let ruffReady;
export function pyLoad(wasmUrl) { return (ruffReady = ruffReady || ruffInit(wasmUrl)); }
export async function pyFormat(code, opts) { await ruffReady; return ruffFormat(code, "a.py", opts); }
