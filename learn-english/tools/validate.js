#!/usr/bin/env node
/* Validate every ready module + its Hindi practice + cheat sheet. Run from the repo root:  node tools/validate.js
   Exits 1 on any problem. */
const fs = require("fs"), path = require("path");
const root = path.join(__dirname, "..");
global.window = global;
require(path.join(root, "modules/manifest.js"));
const MODS = {}, HIN = {}, CHE = {};
global.registerModule = m => { MODS[m.id] = m; };
global.registerHindi = (id, a) => { HIN[id] = a; };
global.registerCheat = (id, h) => { CHE[id] = h; };
const TAGS = new Set(["Food","Travel","Work","Family","Market","Weather","Health","School","Phone","Home","Feelings"]);
const norm = s => s.toLowerCase().replace(/[’]/g,"'").replace(/[.?!,]/g,"").replace(/\s+/g," ").trim();
const bag = s => norm(s).split(" ").sort().join(" ");
let problems = 0; const bad = (m, msg) => { problems++; console.log("  ✗ M"+m+": "+msg); };
const rows = [];
for(const e of MANIFEST.filter(x => x.ready)){
  const id = e.id, f = n => path.join(root, n, n[0] + String(id).padStart(3,"0") + ".js");
  const mf = path.join(root, "modules", "m"+String(id).padStart(3,"0")+".js");
  const hf = path.join(root, "practice", "h"+String(id).padStart(3,"0")+".js");
  const cf = path.join(root, "cheat", "c"+String(id).padStart(3,"0")+".js");
  [mf,hf,cf].forEach(p => { if(!fs.existsSync(p)) bad(id, "missing file "+path.relative(root,p)); else require(p); });
  const m = MODS[id]; if(!m) continue;
  if(m.id !== id) bad(id, "id mismatch");
  if(m.title !== e.title) bad(id, "title differs from manifest: "+m.title);
  const steps = m.steps, boss = steps.find(s => s.k==="boss");
  if(!boss) { bad(id,"no boss"); continue; }
  if(steps[steps.length-1].k !== "done") bad(id,"last step is not done");
  const chk = (q, where) => {
    if(q.k==="order"){
      if(norm(q.words.join(" ")) !== norm(q.a)) bad(id, where+" order words don't rebuild: "+q.a);
      (q.alt||[]).forEach(a => { if(bag(a) !== bag(q.words.join(" "))) bad(id, where+" alt uses different words: "+a); });
      if(q.hi && !q.q) bad(id, where+" hi without q");
    } else if(q.k==="mcq"){
      if(!Array.isArray(q.w) || q.w.length !== q.o.length) bad(id, where+" mcq w/o count mismatch: "+q.q);
      if(!(q.a>=0 && q.a<q.o.length)) bad(id, where+" mcq a out of range: "+q.q);
      if(new Set(q.o).size !== q.o.length) bad(id, where+" duplicate options: "+q.q);
    } else if(q.k==="type"){
      if(!Array.isArray(q.a) || !q.a.length) bad(id, where+" type needs a:[...]: "+q.q);
      if(typeof q.w !== "string") bad(id, where+" type w must be string: "+q.q);
    }
  };
  steps.forEach(s => { if(["order","mcq","type"].includes(s.k)) chk(s,"practice"); });
  boss.qs.forEach(q => chk(q,"boss"));
  const refs = new Set(steps.filter(s => s.k==="card").map(s => s.ref));
  boss.qs.forEach(q => { if(!q.ref) bad(id,"boss q without ref: "+q.q); });
  const own = boss.qs.filter(q => refs.has(q.ref)).length;
  if(!boss.review && own < Math.ceil(boss.qs.length*0.5)) bad(id, "fewer than half of boss questions link to this module's cards");
  const hiP = steps.filter(s => s.hi).length, hiB = boss.qs.filter(q => q.hi).length;
  if(id>=6 && hiP < 4) bad(id, "needs ≥4 Hindi questions in practice (has "+hiP+")");
  if(id>=6 && hiB < 2) bad(id, "needs ≥2 Hindi questions in boss (has "+hiB+")");
  const trap = steps.find(s => s.k==="trap"); if(!trap || trap.items.length<3) bad(id,"trap needs ≥3 items");
  const build = steps.find(s => s.k==="build"); if(!build || build.items.length<4 || build.items.some(i => !(i.must instanceof RegExp))) bad(id,"build needs ≥4 items with a RegExp must");
  const done = steps[steps.length-1]; if(!done.can || done.can.length!==3 || !done.teaser) bad(id,"done needs 3 can + teaser");
  if(boss.pass !== 0.8) bad(id,"boss pass must be 0.8");
  const h = HIN[id] || []; const seen = new Set();
  if(h.length < 20) bad(id, "Hindi practice has "+h.length+" sentences (needs ≥20)");
  h.forEach((x,i) => {
    if(!TAGS.has(x.tag)) bad(id, "unknown tag "+x.tag+" #"+i);
    if(!x.hi || !x.en || !Array.isArray(x.w) || !x.w.length) bad(id, "incomplete Hindi sentence #"+i);
    if(seen.has(x.hi)) bad(id, "duplicate Hindi sentence #"+i); seen.add(x.hi);
    if(!/[ऀ-ॿ]/.test(x.hi||"")) bad(id, "Hindi text has no Devanagari #"+i);
  });
  if(!CHE[id] || CHE[id].length < 600) bad(id, "cheat sheet missing or too short");
  if(!phase(id)) bad(id, "not inside any phase");
  rows.push([id, e.title, steps.length+" steps", "hindi "+hiP+"+"+hiB, h.length+" sentences", (CHE[id]||"").length+" chars cheat"]);
}
function phase(id){ return (PHASES||[]).find(p => id>=p.from && id<=p.to); }
rows.forEach(r => console.log(r.join(" | ")));
console.log(problems ? "\n"+problems+" problem(s)" : "\nAll good: "+rows.length+" modules valid");
process.exit(problems ? 1 : 0);
