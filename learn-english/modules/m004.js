registerModule({
  id: 4,
  title: "Past simple",
  sub: "what already happened",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 4 · Start here", title:"The word that feels wrong",
     html:`<p>A friend asks: <b>"What did you do yesterday?"</b> You went to the market.</p>
           <p>Your brain says: <i>go → goed</i>, like <i>work → worked</i>. That feels logical! Let's see what English thinks.</p>`},
    {k:"mcq", q:"Yesterday I ___ to the market.",
     o:["go","goed","did go","went"], a:3,
     w:["<i>Go</i> is the plain form. \"Yesterday\" needs the past.",
        "A great guess, and every learner makes it. But <i>go</i> is a special verb that does not follow the -ed rule.",
        "That's close, but <i>did go</i> is only used in special cases. The normal past is one word.",
        "Yes! <b>went</b>. About 20 common verbs change shape like this. You'll learn to handle them."]},
    {k:"card", ref:"What it is for", tag:"The idea · 1 of 6", title:"What it is for: finished, and over",
     html:`<p>Past simple is for actions that <b>started and finished</b> in the past, usually with a clear time:</p>
           <div class="right">I watched a movie <b>last night</b>.</div>
           <div class="right">She moved to Pune <b>in 2019</b>.</div>
           <div class="right">We met <b>two days ago</b>.</div>
           <p>Time words that call for it: <b>yesterday, last week / month / year, ago, in 2020, when I was a child</b>.</p>
           <p><b>Three tenses, one picture:</b> <i>I cook</i> (habit, Module 2), <i>I'm cooking</i> (now, Module 3), <i>I cooked</i> (finished, today's module).</p>`},
    {k:"card", ref:"Regular verbs", tag:"The idea · 2 of 6", title:"Good news: one form for everybody",
     html:`<p>Most verbs add <b>-ed</b>. And here is the best part: <b>the same form for every WHO</b>.</p>
           <div class="frame"><span class="who">I</span><span class="glue">worked</span><span class="rest">yesterday.</span></div>
           <div class="frame"><span class="who">She</span><span class="glue">worked</span><span class="rest">yesterday.</span></div>
           <div class="frame"><span class="who">They</span><span class="glue">worked</span><span class="rest">yesterday.</span></div>
           <p>No S like in Module 2 (<i>she work<b>s</b></i>). No am/is/are like Module 3. The -ed already says "past", so nothing else is needed.</p>
           <div class="wrong">She worked<b>s</b>. &nbsp; She is worked. &nbsp; She was work.</div>
           <p class="sub">Pronunciation: -ed has three sounds. <i>worked</i> = "t", <i>played</i> = "d", <i>wanted</i> = "id". You don't say "work-ED" in two clear syllables, except after t and d.</p>`},
    {k:"order", q:"Build it.", words:["I","watched","a","movie","last","night"], a:"I watched a movie last night.",
     w:"WHO + verb-ed + REST. <i>Last night</i> tells us it's finished."},
    {k:"order", q:"A different WHO, the same form.", words:["She","moved","here","two","years","ago"], a:"She moved here two years ago.",
     w:"<b>She moved</b>. No S in the past. <i>Ago</i> is a past clue."},
    {k:"card", ref:"Spelling -ed", tag:"The idea · 3 of 6", title:"Spelling -ed",
     html:`<table>
             <tr><th>Verb</th><th>Do this</th><th>Example</th></tr>
             <tr><td>most verbs</td><td>+ ed</td><td>work → worked<br>watch → watched</td></tr>
             <tr><td>ends in <b>e</b></td><td>+ d only</td><td>like → liked<br>live → lived</td></tr>
             <tr><td>consonant + <b>y</b></td><td>y → ied</td><td>study → studied<br>carry → carried</td></tr>
             <tr><td>vowel + <b>y</b></td><td>just + ed</td><td>play → played<br>enjoy → enjoyed</td></tr>
             <tr><td>short word: consonant + vowel + consonant</td><td>double the last letter</td><td>stop → stopped<br>plan → planned</td></tr>
           </table>
           <p class="sub">Same logic as Module 3 (-ing) and Module 2 (-s): the end of the word decides.</p>`},
    {k:"card", ref:"Irregular verbs", tag:"The idea · 4 of 6", title:"The 20 verbs that break the rule",
     html:`<p>Many of the most common verbs have their own past form. Don't try to learn all of them at once. These cover a huge part of everyday talk:</p>
           <table>
             <tr><th>Now</th><th>Past</th><th>Now</th><th>Past</th></tr>
             <tr><td>go</td><td><b>went</b></td><td>buy</td><td><b>bought</b></td></tr>
             <tr><td>see</td><td><b>saw</b></td><td>think</td><td><b>thought</b></td></tr>
             <tr><td>have</td><td><b>had</b></td><td>know</td><td><b>knew</b></td></tr>
             <tr><td>do</td><td><b>did</b></td><td>give</td><td><b>gave</b></td></tr>
             <tr><td>make</td><td><b>made</b></td><td>tell</td><td><b>told</b></td></tr>
             <tr><td>take</td><td><b>took</b></td><td>write</td><td><b>wrote</b></td></tr>
             <tr><td>come</td><td><b>came</b></td><td>speak</td><td><b>spoke</b></td></tr>
             <tr><td>get</td><td><b>got</b></td><td>eat</td><td><b>ate</b></td></tr>
             <tr><td>say</td><td><b>said</b></td><td>drink</td><td><b>drank</b></td></tr>
           </table>
           <p><b>How to learn them:</b> say each one inside a sentence you will really use: <i>I went home. I saw my friend. I had lunch.</i> A list of words is easy to forget; your own sentence is not.</p>`},
    {k:"card", ref:"was and were", tag:"The idea · 5 of 6", title:"The past of am / is / are",
     html:`<p>Module 1's glue has its own past, and it is the only verb with two forms:</p>
           <table>
             <tr><th>WHO</th><th>Past glue</th><th>Example</th></tr>
             <tr><td>I, he, she, it (one)</td><td><b>was</b></td><td>I was tired. She was late.</td></tr>
             <tr><td>you, we, they (many)</td><td><b>were</b></td><td>We were at home. You were right.</td></tr>
           </table>
           <p>Negative: <b>wasn't / weren't</b>. Question: swap, just like Module 1: <b>Was she at home? Were you tired?</b></p>
           <p>Same rule as before: <i>was/were</i> is for feelings, places and descriptions. Actions use the past form (<i>worked, went</i>), never <i>was</i> + action:</p>
           <div class="wrong">I was watched a movie.</div><div class="right">I watched a movie.</div>`},
    {k:"card", ref:"No and questions", tag:"The idea · 6 of 6", title:"No and questions: did / didn't",
     html:`<p>Same trick as Module 2, with <b>did</b> instead of do/does:</p>
           <div class="right">I <b>didn't</b> go. &nbsp; She <b>didn't</b> call. &nbsp; They <b>didn't</b> know.</div>
           <div class="frame"><span class="glue">Did</span><span class="who">you</span><span class="rest">go to work?</span></div>
           <div class="right">Where <b>did</b> you go? &nbsp; What <b>did</b> she say?</div>
           <p>Look closely. <b>The past moved into <i>did</i>.</b> The verb goes back to its plain form, exactly like the S in Module 2:</p>
           <div class="wrong">I didn't went. &nbsp; Did you went?</div>
           <div class="right">I didn't go. &nbsp; Did you go?</div>
           <p>Short answers: <b>Yes, I did. &nbsp; No, she didn't.</b></p>
           <p class="sub">With <i>was / were</i> there's no <i>did</i>: <i>Was she there?</i> The glue is its own helper.</p>`},
    {k:"mcq", q:"I ___ my friend yesterday.", o:["see","seed","saw"], a:2,
     w:["Plain form, but \"yesterday\" needs the past.","Not a word. <i>See</i> is irregular.","Yes. see → <b>saw</b>."]},
    {k:"mcq", q:"She ___ a letter last week.", o:["writed","wrote","write"], a:1,
     w:["<i>Write</i> is irregular, so no -ed.","Yes. write → <b>wrote</b>.","Plain form; \"last week\" needs the past."]},
    {k:"mcq", q:"They ___ here two years ago.", o:["live","lived","living"], a:1,
     w:["\"Ago\" is a past clue.","Yes. Ends in e → just add <b>d</b>.","\"Living\" is the -ing form (Module 3)."]},
    {k:"type", q:"She ___ (study) hard last night.", a:["studied"], w:"Consonant + y → <b>ied</b>: studied."},
    {k:"type", q:"We ___ (stop) at the shop.", a:["stopped"], w:"Short word → double the p: <b>stopped</b>."},
    {k:"type", q:"I ___ (buy) a new phone yesterday.", a:["bought"], w:"Irregular: buy → <b>bought</b>."},
    {k:"type", q:"He ___ (take) a taxi.", a:["took"], w:"Irregular: take → <b>took</b>."},
    {k:"mcq", q:"I ___ tired last night.", o:["am","was","were"], a:1,
     w:["\"Last night\" is the past.","Yes. I → <b>was</b>.","\"were\" goes with you/we/they."]},
    {k:"mcq", q:"We ___ at home yesterday.", o:["was","were","are"], a:1,
     w:["\"We\" is more than one: <b>were</b>.","Yes. We → <b>were</b>.","\"Yesterday\" needs the past."]},
    {k:"mcq", q:"Which is correct?", o:["I didn't went.","I didn't go.","I not went."], a:1,
     w:["<i>Didn't</i> already carries the past. The verb stays plain.","Yes. The past moved into <b>didn't</b>; the verb is plain.","English needs <i>didn't</i> here."]},
    {k:"order", q:"Build the negative.", words:["She","didn't","call","me","yesterday"], a:"She didn't call me yesterday.", w:"<b>didn't</b> + plain verb. No -ed."},
    {k:"order", q:"Build the question.", words:["Where","did","you","go"], a:"Where did you go?", w:"Question word + <b>did</b> + WHO + plain verb."},
    {k:"order", q:"Build the question.", words:["Did","he","finish","his","work"], a:"Did he finish his work?", w:"<b>Did</b> carries the past, so <i>finish</i> stays plain."},
    {k:"order", q:"Revision from Module 1!", words:["We","were","very","tired"], a:"We were very tired.", w:"The glue in the past: we → <b>were</b>."},
    {k:"mcq", q:"Revision from Module 3: which one is happening RIGHT NOW?", o:["I cooked dinner.","I'm cooking dinner.","I cook dinner every day."], a:1,
     w:["Finished and in the past.","Yes. <b>am + -ing</b> = now.","A habit (Module 2)."]},
    {k:"build", intro:"Your turn. Tell me about <b>your own past</b>. Type each one and say it out loud.",
     items:[
      {p:"What did you do yesterday?", frame:"I ______ (verb-ed or irregular) yesterday.", ex:"I went to the market and bought vegetables.", must:/\bi\s+(\w+ed|went|saw|had|did|ate|took|made|got|came|bought|drank|slept|met|read|wrote|woke|gave|said|spoke|knew|thought|left|found|told|sat|ran)\b/i, ok:"Past form after I. Right.", tip:"Start with <b>I</b> + a past verb: I watched, I went, I had..."},
      {p:"Where were you at 8 pm last night?", frame:"I was ______.", ex:"I was at home with my family.", must:/\bi was\b/i, ok:"<i>I was</i>: the past glue.", tip:"Start with <b>I was</b> + a place."},
      {p:"Say something you did NOT do yesterday.", frame:"I didn't ______.", ex:"I didn't cook dinner.", must:/(didn't|did not)\s+\w+/i, ok:"<i>didn't</i> + plain verb. No -ed.", tip:"<b>I didn't</b> + plain verb (go, eat, call...)."},
      {p:"Tell me about a family member's last weekend.", frame:"My ______ ______ last weekend.", ex:"My brother visited us last weekend.", must:/\b(was|went|saw|had|did|ate|took|made|got|came|bought|drank|slept|met|wrote|woke|gave|said|spoke|knew|\w+ed)\b/i, ok:"Past verb, same form for every WHO.", tip:"A past verb after the person: My father <b>visited</b> / <b>went</b> / <b>had</b>..."},
      {p:"Ask me a question about my past.", frame:"Did you ______? / Where did you ______?", ex:"Where did you grow up?", must:/^\s*(did|was|were|what|where|when|who|why|how)\b/i, ok:"A real past question.", tip:"Start with <b>Did you ...?</b> or <b>Where did you ...?</b>"}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"Yesterday I go to work.", good:"Yesterday I went to work.", fix:"A past time word (yesterday, last week, ago) needs the past form."},
      {bad:"I goed. / I buyed.", good:"I went. / I bought.", fix:"Irregular verbs have their own past. Learn them inside your own sentences."},
      {bad:"I didn't went.", good:"I didn't go.", fix:"<i>Didn't</i> already carries the past. The verb goes back to plain."},
      {bad:"Did you went there?", good:"Did you go there?", fix:"Same rule: <b>Did</b> carries the past."},
      {bad:"I was watched a movie.", good:"I watched a movie.", fix:"Don't mix <i>was</i> with an action word. <i>Was/were</i> is for feelings, places and descriptions."}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: The Detective", pass:0.8,
     intro:"Something happened last night and you are the detective asking the questions. This also revisits Modules 1 to 3. You need 8 of 10.",
     qs:[
      {k:"mcq", ref:"What it is for", q:"Which is correct?", o:["I see her yesterday.","I saw her yesterday.","I seen her yesterday."], a:1, w:["\"Yesterday\" needs the past.","Yes: see → <b>saw</b>.","<i>Seen</i> is for a later module; the simple past is <i>saw</i>."]},
      {k:"type", ref:"Spelling -ed", q:"They ___ (stop) the car.", a:["stopped"], w:"Double the p: <b>stopped</b>."},
      {k:"type", ref:"Spelling -ed", q:"She ___ (carry) the bag.", a:["carried"], w:"Consonant + y → <b>ied</b>: carried."},
      {k:"mcq", ref:"No and questions", q:"I didn't ___ him.", o:["see","saw","seen"], a:0, w:["Yes: after <i>didn't</i>, the verb is plain.","<i>Didn't</i> already carries the past.","Not after <i>didn't</i>."]},
      {k:"order", ref:"No and questions", q:"Build the question.", words:["Did","you","finish","your","homework"], a:"Did you finish your homework?", w:"<b>Did</b> + WHO + plain verb."},
      {k:"type", ref:"Irregular verbs", q:"We ___ (eat) dinner at eight.", a:["ate"], w:"Irregular: eat → <b>ate</b>."},
      {k:"mcq", ref:"was and were", q:"They ___ at the party.", o:["was","were","are"], a:1, w:["\"They\" is plural: <b>were</b>.","Yes: they → <b>were</b>.","\"Last night\" is the past."]},
      {k:"order", ref:"was and were", q:"Build the question.", words:["Was","she","at","home"], a:"Was she at home?", w:"The past glue jumps to the front, like Module 1."},
      {k:"mcq", ref:"Regular verbs", q:"He ___ in a bank two years ago.", o:["work","works","worked"], a:2, w:["\"Ago\" needs the past.","No S in the past, and \"ago\" needs -ed.","Yes: <b>worked</b>. Same form for every WHO."]},
      {k:"mcq", ref:"What it is for", q:"Revision: which sentence is happening right now?", o:["I cooked.","I'm cooking.","I cook every day."], a:1, w:["Finished, in the past.","Yes: <b>am + -ing</b> = now.","A habit (Module 2)."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Tell what happened: <i>I went to the market. She called me last night. We watched a movie.</i>",
          "Say no and ask about the past: <i>I didn't go. Did you see it? Where did you go?</i>",
          "Describe how things were: <i>I was tired. They were at home.</i> And use the 20 most common irregular verbs."],
     teaser:"Next: <b>Present perfect.</b> The tense that links the past to now: <i>I've lived here for years. Have you ever been to Goa?</i>"}
  ]
});
