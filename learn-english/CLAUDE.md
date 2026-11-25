# Speak English (`learn-english/`, package `learn_english`) — the owner's English fluency course

> Repo rules: `../CLAUDE.md` · where things live: `./KNOWLEDGE_MAP.md` · the original teacher prompt: `./PROMPT.md`.
> Moved here from the `learn-english-fluency` repo on 2026-11-24 ("centralize; content is good, only improve the UI/UX").
> That repo still exists and is NOT to be deleted until the owner decides after testing.

## START OF EVERY SESSION (do this first)
1. Read this whole file. The owner writes short, broken English; read for intent, answer plainly and briefly. They use this course a lot.
2. **Current state: Batch 1 (Modules 1–16) is fully built** (Phases 1–4). **Do not build Batch 2 until the progress check shows ALL of 1–16 passed.**
   Then build Batch 2 = Modules 17–26 in one go (see "Batch rule").
3. Run the progress check (below) before touching any module, even if the owner says "I passed". If it disagrees with them, ask.

## How to check progress (one request; no more reading Chrome's files)
```
curl -s -H 'X-Speak-English: 1' http://localhost:8000/tools/learn-english/progress/summary
```
→ `{"passed":[1,2,…], "built":[1…16], "next":N, "all_built_passed":bool, "scores":{…}, "tough":n, "updated_at":…}`.
`all_built_passed: true` = the whole built batch is passed → build the next batch. Read only; never PUT to the live store yourself.
(If `updated_at` is null or `passed` is empty right after the move, the owner has not restored their old progress code yet — ask, don't build.)

## Batch rule: build 10 modules at a time, only after the owner finishes the batch
1. Build the next 10 modules in one go (Batch 2 = 17–26, Batch 3 = 27–36 …), each complete (module + Hindi set + cheat sheet + manifest + phase),
   validated, tested. They stay **locked** in the app until the previous module is passed.
2. Start the next batch only when the progress check shows every module of the current batch passed. Don't wait to be asked.
3. Work in rounds of 2 modules: write → `node learn-english/tools/validate.js` → click-through on a private copy (below) → `python3 -m pytest tests/unit/test_learn_english.py -q`
   → `docker compose up -d --build`. Commit/push only when the owner says so (Toolbox rule).
4. Plan a batch by first adding all 10 entries to `modules/manifest.js` (`{id, title}`; set `ready:true, sub` as each is built) and extending `window.PHASES`
   (each phase = a meaningful theme of 4–8 modules with a `win` sentence). Ideas for Batch 2+: vocabulary by topic, phrasal verbs, collocations and idioms,
   listening and fast speech, pronunciation, storytelling and presenting, writing emails and messages, interviews and meetings. Grammar now mostly review-in-context.
5. Phase review bosses (12–20 questions, `review:true` allowed) close each phase. Pass mark stays 80%.

## Where things live
- `ui/index.html` — the engine: top bar, course sidebar, home (hero = next module, stats, phase cards; the full path list on phones), lessons, boss,
  Hindi practice (Plain/Tough), cheat sheets, welcome-back warm-up, progress code. **Never put module content in it.**
- `modules/mNNN.js` (`registerModule({id,title,sub,steps})`) + `modules/manifest.js` (`MANIFEST`, `PHASES`) · `practice/hNNN.js` (`registerHindi`) · `cheat/cNNN.js` (`registerCheat`).
  The page loads them with `<script>` tags on demand; `server.py` serves only names matching `mNNN.js|manifest.js`, `hNNN.js`, `cNNN.js`.
- `server.py` — page, content files, progress API (`GET/PUT progress`, `GET progress/summary`), `/health`. Progress = one row in SqlStore `learn_english.progress`.
- `tools/validate.js` (content checker, unchanged from the repo) · `tools/run_private.py` (a private copy with throwaway progress for click-through tests).

## Progress (owner decision 2026-11-24: saved in Toolbox)
- Stored in Postgres via SqlStore, one learner (`id = 'me'`). The browser keeps a cache (`localStorage speakEnglish.v1`) only to retry a failed save;
  a failed save shows "⚠ Not saved" in the top bar.
- **Server merge rule:** passed = union, scores = max, last = max; `pos` and the Tough list come from the newest save. An old tab can never remove a pass.
- Every progress call needs the header `X-Speak-English: 1` (blocks other websites; tested).
- Moving progress in: the old app's "Copy my progress code" → here "Restore from a code" (merge-only, `SE2.`/`SE1.` codes).
- Reading preferences (text size, light/dark) are per browser: `localStorage speakEnglish.ui`.
- The offline download copy (`dist/`, `build.py`) was dropped: progress lives in Toolbox now.

## Hindi practice: Plain / Tough
`S.tough = {sentenceId:{s:streak,n:timesMarked}}`. A sentence id is `module:hash(hindi text)` (`sid()`), so reordering a practice file is safe;
**never edit the `hi` text of an existing sentence** (it orphans its tough mark; add a new one). Plain gives ✅ Knew it / 😬 Add to Tough; Tough gives ✅ Got it
(3 in a row → offer removal) / 😬 Still tough. Every card has an always-visible Add to / Remove from Tough toggle.

## Module content rules (from the teacher prompt, unchanged)
- **One module = one sitting**, one topic, a clear finish line. Flow: hook → the idea (frame = fixed part + swappable slots, why it sounds right, wrong vs right) →
  guided practice (easy → harder, a one-line explanation for **every** wrong option) → build your own (about the owner's life, said out loud) → mistake trap
  (3–5 common mistakes + quick fix) → boss (pass 80%, mixes earlier modules, on fail shows what to revisit) → "You can now say…" (3 real-life things + teaser).
- **Hindi → English questions (Module 6+):** ≥4 in guided practice and ≥2 in the boss: `hi:"<Devanagari>"` on `order`/`type`/`mcq` (`q` = the instruction).
  Mostly `order`; `alt:[…]` = other correct orders from the **same words**; `a:[…]` list for `type`. Natural everyday Hindi that pushes the exact mistake.
- **Hindi practice set per module:** `practice/hNNN.js`, 20–100 sentences sized to the topic, varied tags (Food, Travel, Work, Family, Market, Weather,
  Health, School, Phone, Home, Feelings; a new tag needs an emoji in `TOPIC_ICON`), only grammar taught so far, 1–2 words in `w`, a `note` on the trap.
  Currently: M1 20, M2 24, M3 20, M4 26, M5 22, M6 24, M7–14 24 each, M15 30, M16 24 (382 total).
- **Cheat sheet per module:** `cheat/cNNN.js`, one phone-screen page: frame, forms tables, no + question forms, short answers, Remember, Top mistakes, Say it.
  Classes: `frame/who/glue/rest`, `table`, `right`, `wrong`, `h3`.
- **Phases:** `window.PHASES` (id, from, to, icon, name, tagline, win). 1 The Six Tenses 1–6, 2 Ask and Shape 7–10, 3 Connect Your Ideas 11–14, 4 Real Life 15–16.
  Last module of a phase → 🏆 trophy. Beyond 16 add new phases; never leave modules unphased.
- **Layout rules (owner, 2026-11-24):** Learn AWS look (white cards, blue-grey desk, blue accent, light/night). One place to go anywhere: the sidebar
  (Continue · Practice: Quick mix 20 / Hard ones / Everything — each starts at once, no setup screen · phases as fold-out sections, only the current one open).
  Per-module actions are small line icons shown on hover (cheat sheet, practise, replay). The lesson progress row (← Home · bar · step) lives in the top bar.
  Lessons have ‹ Previous / Next › in the top bar: `pos` = furthest step (saved), `at` = step on screen; looking back never moves `pos`, nobody can go past it, and the buttons hide during a boss attempt.
  Home = next module + three numbers only (no phase list; the sidebar has it). Lesson screens must fit a ~1355×790 screen without scrolling where the content allows; the last button of a screen is pinned to the bottom when a card is long.
- **Voice:** a smart, warm, slightly funny friend. Simple words, never childish. **Win early. No guilt** (welcome back + 5-question warm-up, no streak shaming).
  Hide earlier modules inside new examples (spaced repetition). Every few modules a bigger review.
- Step kinds: `card`, `mcq`, `order`, `type`, `build`, `trap`, `boss`, `done`. Boss questions carry `ref` matching a card's `ref`. Strict order is enforced in `runModule`.

## Tests
- `node learn-english/tools/validate.js` must print "All good" (order words rebuild `a`/`alt`, one `w` per mcq option, boss refs, Hindi counts, cheat sheet, phase, pass 0.8).
- `tests/unit/test_learn_english.py` — content routes, progress guard, round trip, merge rules, junk dropping, summary, page rules, validate.js, Dockerfile lines.
- Click-through: `python3 learn-english/tools/run_private.py`, preset progress with curl (see the script), open `http://127.0.0.1:8765/`. Expect no page errors.
  A boss answered with the first option should FAIL (it proves the fail path).
- `tests/smoke/test_learn_english.py` is read-only against the live stack.

## Lessons learned (do not repeat)
- **Never test against the live tool** — it is the owner's real progress. Use `tools/run_private.py`.
- Never edit an existing practice sentence's `hi` text. Keep module files small (~13–20 KB), vanilla JS, no libraries.
- The content route `/{folder}/{name}` is declared LAST in `server.py`, or it would capture `/progress/summary`.
- Owner rule from Learn AWS: when asked to *add* something to an approved screen, extend it — never swap in a different design.
