registerModule({
  id: 2,
  title: "Present simple",
  sub: "habits, routines and facts",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 2 · Start here", title:"One little letter",
     html:`<p>In Module 1 you learned <i>she <b>is</b> tired</i>. Now we need actions: working, eating, going.</p>
           <p>One tiny letter causes more mistakes than almost anything else in English. Let's see if your ear already knows it.</p>`},
    {k:"mcq", q:"Which one is right?", o:["She work in a bank.","She is work in a bank.","She working in a bank.","She works in a bank."], a:3,
     w:["Almost. One letter is missing at the end.","\"is\" is for feelings and places. \"Work\" is already an action, so it doesn't need <b>is</b>.","\"Working\" means <i>right now</i>. That's Module 3.","Yes! The magic letter: <b>S</b>."]},
    {k:"card", ref:"What it is for", tag:"The idea · 1 of 6", title:"What present simple is for",
     html:`<p>Use it for things that are <b>true in general</b>, not just this second:</p>
           <div class="right">I drink tea every morning. <span class="sub">(habit)</span></div>
           <div class="right">My brother works at night. <span class="sub">(routine)</span></div>
           <div class="right">The sun rises in the east. <span class="sub">(fact)</span></div>
           <p>Module 1 was a <i>state</i>: <i>I am tired</i>. Module 2 is an <i>action</i>: <i>I work</i>.</p>
           <p><b>Big idea:</b> an action needs <b>no am / is / are</b>. Never say "I am work".</p>`},
    {k:"card", ref:"One S, one place", tag:"The idea · 2 of 6", title:"One S, one place",
     html:`<p>The skeleton is still the same, except the glue is now the action itself:</p>
           <div class="frame"><span class="who">I</span><span class="glue">work</span><span class="rest">in a bank.</span></div>
           <div class="frame"><span class="who">She</span><span class="glue">works</span><span class="rest">in a bank.</span></div>
           <p><b>The rule:</b> after <b>he / she / it</b> (exactly one other person or thing), the verb gets an <b>S</b>. After I / you / we / they, no S.</p>
           <p><b>Why?</b> English has only one place to show "this is one other person": the verb. It was once much more complicated. This S is what survived.</p>
           <p><b>Trick:</b> only one S per pair, on the noun <i>or</i> the verb:</p>
           <div class="right">The <b>boy</b> play<b>s</b>. (one boy → S on the verb)</div>
           <div class="right">The <b>boys</b> play. (many boys → S on the noun, none on the verb)</div>`},
    {k:"order", q:"Build it.", words:["She","works","in","a","bank"], a:"She works in a bank.",
     w:"She = one person → verb + <b>s</b>."},
    {k:"order", q:"Now with I.", words:["I","usually","wake","up","at","six"], a:"I usually wake up at six.",
     w:"After <b>I</b> there is no S: wake. (And <i>usually</i> goes before the verb. More on that soon.)"},
    {k:"card", ref:"Spelling the S", tag:"The idea · 3 of 6", title:"Spelling the S (it's easier than it looks)",
     html:`<table>
             <tr><th>Verb ends in…</th><th>Do this</th><th>Example</th></tr>
             <tr><td>most verbs</td><td>+ s</td><td>work → works<br>play → plays</td></tr>
             <tr><td>s, sh, ch, x, o</td><td>+ es</td><td>watch → watches<br>go → goes<br>do → does</td></tr>
             <tr><td>consonant + y</td><td>y → ies</td><td>study → studies<br>cry → cries</td></tr>
             <tr><td>vowel + y</td><td>just + s</td><td>play → plays<br>enjoy → enjoys</td></tr>
             <tr><td>have</td><td>special</td><td>have → <b>has</b></td></tr>
           </table>
           <p class="sub">The sounds help: if you'd need an extra "iz" sound to say it (watch-iz), you add <b>es</b>.</p>`},
    {k:"card", ref:"don't / doesn't", tag:"The idea · 4 of 6", title:"Saying NO: don't and doesn't",
     html:`<div class="right">I <b>don't</b> work on Sundays.</div>
           <div class="right">She <b>doesn't</b> work on Sundays.</div>
           <p>Look closely at the second one. <b>The S jumped.</b> It left <i>work</i> and moved into <i>does</i>.</p>
           <div class="wrong">She doesn't works.</div>
           <div class="right">She doesn't work.</div>
           <p>One S per sentence. <i>Doesn't</i> already shows "one person", so the verb goes back to its plain form.</p>`},
    {k:"card", ref:"Do / Does questions", tag:"The idea · 5 of 6", title:"Asking questions: Do / Does",
     html:`<p>Same trick as Module 1: put the helper first. This time the helper is <b>do</b> or <b>does</b>.</p>
           <div class="frame"><span class="glue">Do</span><span class="who">you</span><span class="rest">work here?</span></div>
           <div class="frame"><span class="glue">Does</span><span class="who">she</span><span class="rest">work here?</span></div>
           <p>The S lives in <b>Does</b>, so <i>work</i> stays plain. With a question word: <b>Where does he live? What do you do?</b></p>
           <p>Short answers: <b>Yes, I do. &nbsp; No, she doesn't.</b></p>
           <div class="fb note"><b>Don't mix the two toolkits.</b> Feelings/places/descriptions use <i>am/is/are</i> (<i>Are you tired?</i>). Actions use <i>do/does</i> (<i>Do you work?</i>). Never "Do you tired?" or "I am work".</div>`},
    {k:"card", ref:"Frequency words", tag:"The idea · 6 of 6", title:"How often? always, usually, never…",
     html:`<p>From most to least often: <b>always → usually → often → sometimes → rarely → never</b></p>
           <p>With an action, put the word <b>before the verb</b>:</p>
           <div class="right">I <b>always</b> drink tea. &nbsp; She <b>never</b> eats meat.</div>
           <p>With <b>am / is / are</b> (Module 1!), put it <b>after</b> the glue:</p>
           <div class="right">She is <b>always</b> late. &nbsp; I am <b>never</b> bored.</div>
           <div class="wrong">She always is late.</div>`},
    {k:"mcq", q:"My brother ___ in a hospital.", o:["work","works","working"], a:1,
     w:["\"My brother\" is one person, so the verb needs an <b>S</b>.","Yes. One person → work<b>s</b>.","\"Working\" is for right now (Module 3)."]},
    {k:"mcq", q:"They ___ coffee in the morning.", o:["drinks","drink","are drink"], a:1,
     w:["\"They\" is plural. No S on the verb.","Yes. They → plain verb: <b>drink</b>.","\"are\" is for feelings and places. \"Drink\" is an action, so no glue."]},
    {k:"type", q:"My mother ___ (cook) every evening.", a:["cooks"], w:"One person → <b>cooks</b>."},
    {k:"type", q:"He ___ (study) at night.", a:["studies"], w:"Consonant + y → <b>ies</b>: studies."},
    {k:"type", q:"She ___ (go) to the gym on Mondays.", a:["goes"], w:"Ends in o → <b>es</b>: goes."},
    {k:"mcq", q:"She ___ like spicy food.", o:["don't","doesn't","isn't"], a:1,
     w:["\"don't\" goes with I/you/we/they.","Yes. One person → <b>doesn't</b>.","\"isn't\" is for the Module 1 glue, not actions."]},
    {k:"mcq", q:"Which is correct?", o:["She doesn't likes tea.","She doesn't like tea.","She not like tea."], a:1,
     w:["Two S's. The S is already in <i>doesn't</i>.","Yes. The S jumped into <b>doesn't</b>; the verb stays plain.","English needs <i>doesn't</i> here, not just <i>not</i>."]},
    {k:"type", q:"I ___ like coffee. <span class='sub'>(say no: don't / doesn't)</span>", a:["don't","do not"], w:"\"I\" → <b>don't</b>."},
    {k:"mcq", q:"___ he play cricket?", o:["Do","Does","Is"], a:1,
     w:["\"he\" needs <b>does</b>.","Yes. \"he\" → <b>Does</b>.","\"Is\" is for feelings and places. \"Play\" is an action."]},
    {k:"order", q:"Build the question.", words:["Does","he","work","here"], a:"Does he work here?",
     w:"<b>Does</b> carries the S, so <i>work</i> stays plain."},
    {k:"order", q:"Build the negative.", words:["She","doesn't","eat","meat"], a:"She doesn't eat meat.", w:"The S jumped into <b>doesn't</b>."},
    {k:"order", q:"A little revision from Module 1!", words:["My","dad","is","never","late"], a:"My dad is never late.",
     w:"With <b>is</b>, the frequency word comes <i>after</i> the glue."},
    {k:"mcq", q:"Which is correct?", o:["She always is late.","She is always late.","She always late."], a:1,
     w:["With am/is/are the frequency word goes <i>after</i> the glue.","Yes. <b>is always</b>.","The glue (Module 1!) is missing."]},
    {k:"type", q:"What time ___ you start work? <span class='sub'>(do / does)</span>", a:["do"], w:"\"you\" → <b>do</b>."},
    {k:"build", intro:"Your turn. Real sentences about <b>your life</b>. Type each one and say it out loud.",
     items:[
      {p:"Tell me one thing you do every morning.", frame:"I ______ every morning.", ex:"I drink tea every morning.", must:/^\s*i\s+(?!am\b|'m)\w+/i, ok:"Habit + plain verb after I. Right.", tip:"Start with <b>I</b> + an action word. No <i>am</i>: not \"I am drink\"."},
      {p:"What does someone in your family do?", frame:"My ______ works / plays / likes ______.", ex:"My father works in a shop.", must:/\b(my|he|she)\b.*\b\w+(s|es|ies)\b/i, ok:"Remember the S after one person.", tip:"One person → verb with <b>S</b>: My father <b>works</b>..."},
      {p:"Say something you never do.", frame:"I never ______.", ex:"I never eat breakfast.", must:/never/i, ok:"<i>Never</i> before the verb.", tip:"Put <b>never</b> before the action: I never ..."},
      {p:"Say something a friend does NOT like.", frame:"My friend doesn't ______.", ex:"My friend doesn't like tea.", must:/(doesn't|does not)/i, ok:"<i>Doesn't</i> + plain verb. No S.", tip:"Use <b>doesn't</b> + plain verb: My friend doesn't like ..."},
      {p:"Ask me about my routine, starting with Do or Does.", frame:"Do you ______?", ex:"Do you work on weekends?", must:/^\s*(do|does)\b/i, ok:"A real question.", tip:"Start with <b>Do</b> (you/I/we/they) or <b>Does</b> (he/she/it)."}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"She work in a bank.", good:"She works in a bank.", fix:"One other person → add the S."},
      {bad:"She doesn't works.", good:"She doesn't work.", fix:"The S moved into <i>doesn't</i>. One S only."},
      {bad:"Do she like tea?", good:"Does she like tea?", fix:"he/she/it → <b>Does</b>."},
      {bad:"I am work every day. / I am go home.", good:"I work every day. / I go home.", fix:"Actions need no am/is/are. Pick one toolkit, not both."},
      {bad:"He have a car.", good:"He has a car.", fix:"<i>have</i> becomes <b>has</b> after he/she/it."}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: A Day at the Office", pass:0.8,
     intro:"You are starting at a new office and everyone is asking you questions. This challenge also revisits Module 1. You need 8 of 10.",
     qs:[
      {k:"mcq", ref:"What it is for", q:"Which sentence is correct?", o:["He is work at night.","He works at night.","He work at night."], a:1, w:["Actions don't need <i>is</i>.","Yes: he + work<b>s</b>.","One other person → needs the S."]},
      {k:"type", ref:"One S, one place", q:"My parents ___ (live) in a small town.", a:["live"], w:"\"My parents\" = they → plain verb: <b>live</b>."},
      {k:"order", ref:"Do / Does questions", q:"Build the question.", words:["Does","she","like","tea"], a:"Does she like tea?", w:"<b>Does</b> carries the S."},
      {k:"mcq", ref:"Module 1: am / is / are", q:"Is your brother at home? — Yes, ___", o:["he is.","he does.","he's."], a:0, w:["Yes: the question used <i>is</i>, so the answer uses <b>is</b>, in full.","The question used <i>is</i>, so answer with <i>is</i>.","Don't shrink at the end of an answer."]},
      {k:"type", ref:"Spelling the S", q:"She ___ (watch) TV at night.", a:["watches"], w:"Ends in ch → <b>es</b>: watches."},
      {k:"mcq", ref:"don't / doesn't", q:"He doesn't ___ spicy food.", o:["like","likes","liking"], a:0, w:["Yes: after doesn't, the verb stays plain.","The S is already in <i>doesn't</i>.","\"Liking\" is not used here."]},
      {k:"order", ref:"don't / doesn't", q:"Build it.", words:["We","don't","work","on","Sundays"], a:"We don't work on Sundays.", w:"We → <b>don't</b> + plain verb."},
      {k:"mcq", ref:"Do / Does questions", q:"Which is correct?", o:["Where he lives?","Where does he live?","Where does he lives?"], a:1, w:["The helper <i>does</i> is missing.","Yes: <b>Where does he live?</b>","Two S's: <i>does</i> already has it."]},
      {k:"mcq", ref:"Frequency words", q:"Which is correct?", o:["He never is late.","He is never late.","He never late."], a:1, w:["With <i>is</i>, the frequency word goes after.","Yes: <b>is never</b>.","The glue is missing."]},
      {k:"type", ref:"Do / Does questions", q:"___ they speak English at work? <span class='sub'>(Do / Does)</span>", a:["do"], w:"\"they\" → <b>Do</b>."}
     ]},
    {k:"done", title:"You can now say…",
     can:["Talk about habits and routines: <i>I wake up at six. She works at night. We never eat late.</i>",
          "Say no: <i>He doesn't like tea. I don't work on Sundays.</i>",
          "Ask about other people's lives: <i>Do you work here? Where does he live?</i>"],
     teaser:"Next: <b>Present continuous.</b> What is happening <i>right now</i>: <i>I'm working. She's cooking.</i> The Module 1 glue comes back, with a new job."}
  ]
});
