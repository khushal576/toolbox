/* Course map. One line per module. Add ready:true once modules/mNNN.js exists.
   Only the engine (index.html) and this map load at start; each module file loads on demand. */
window.MANIFEST = [
  {id:1, ready:true, title:"The sentence skeleton", sub:"am / is / are"},
  {id:2, ready:true, title:"Present simple", sub:"habits, routines and facts"},
  {id:3, ready:true, title:"Present continuous", sub:"what is happening now"},
  {id:4, ready:true, title:"Past simple", sub:"what already happened"},
  {id:5, ready:true, title:"Present perfect (vs past)", sub:"linking the past to now"},
  {id:6, ready:true, title:"Future", sub:"will, going to and plans"},
  {id:7, ready:true, title:"Questions (do/does/did, what vs which)", sub:"ask anything, in any tense"},
  {id:8, ready:true, title:"Modals (can, should, must, would)", sub:"ability, advice, rules and politeness"},
  {id:9, ready:true, title:"Nouns and articles", sub:"a, an, the, or nothing"},
  {id:10, ready:true, title:"in / on / at and prepositions", sub:"time, place, movement and fixed pairs"},
  {id:11, ready:true, title:"Connectors (because, but, so, if, although)", sub:"join ideas into long, smooth sentences"},
  {id:12, ready:true, title:"Comparing and opinions", sub:"bigger, the best, I think…"},
  {id:13, ready:true, title:"Conditionals", sub:"real and imaginary if"},
  {id:14, ready:true, title:"Reporting what people said", sub:"he said that…, she asked if…"},
  {id:15, ready:true, title:"Real situations", sub:"introduce, ask for help, disagree, complain, tell a story, phone"},
  {id:16, ready:true, title:"Think in English", sub:"keep improving alone, for life"},
];

/* Phases group modules into chapters with a meaning; finishing the last module of a phase earns a trophy.
   Add a phase here when its modules are planned (from/to are module ids). */
window.PHASES = [
  {id:1, from:1,  to:6,  icon:"⏱️", name:"The Six Tenses",      tagline:"Talk about any time",                          win:"You can talk about any time: right now, your habits, the past, your life so far and the future."},
  {id:2, from:7,  to:10, icon:"❓", name:"Ask and Shape",       tagline:"Ask anything, request, advise, name things",   win:"You can ask any question, make requests and give advice, and name people and things correctly."},
  {id:3, from:11, to:14, icon:"🔗", name:"Connect Your Ideas",  tagline:"Reasons, opinions, long smooth sentences",     win:"You can give reasons, compare, share opinions and report what others said, in long, smooth sentences."},
  {id:4, from:15, to:16, icon:"🌍", name:"Real Life",           tagline:"Use English for real, keep growing alone",     win:"You can handle real situations and you know how to keep improving on your own, for life."}
];
