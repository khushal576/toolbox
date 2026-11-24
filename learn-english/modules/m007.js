registerModule({
  id: 7,
  title: "Questions (do/does/did, what vs which)",
  sub: "ask anything, in any tense",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 7 · Start here", title:"The question that freezes you",
     html:`<p>Your friend says: <b>"I went to Delhi last week."</b> You want to know <i>when</i>. In your head the question is clear. Then your mouth freezes: where does <i>did</i> go? Is it <i>went</i> or <i>go</i>?</p>
           <p>Good news: questions follow <b>one frame</b>, and it works in every tense. Try it first.</p>`},
    {k:"mcq", q:"Your friend went to Delhi last week. How do you ask when?",
     o:["When you went?","When did you went?","When went you?","When did you go?"], a:3,
     w:["The helper <i>did</i> is missing.","<i>Did</i> already carries the past, so the verb must go back to plain: <i>go</i>.","Yoda again! English questions need a helper before the WHO.","Yes! <b>Question word + did + you + plain verb</b>."]},
    {k:"card", ref:"Two kinds of questions", tag:"The idea · 1 of 5", title:"Two kinds of questions",
     html:`<p><b>Yes / no questions</b> are answered with yes or no. <b>Wh questions</b> ask for information (what, where, when, why, who, how).</p>
           <p>Both start from the same step: <b>find the helper and put it first.</b></p>
           <table>
             <tr><th>Sentence has…</th><th>Helper</th><th>Question</th></tr>
             <tr><td>am / is / are</td><td>the glue</td><td><b>Are</b> you ready?</td></tr>
             <tr><td>a plain habit (Module 2)</td><td>do / does</td><td><b>Does</b> she work here?</td></tr>
             <tr><td>a past action (Module 4)</td><td>did</td><td><b>Did</b> you call him?</td></tr>
             <tr><td>-ing (Module 3)</td><td>am / is / are</td><td><b>Are</b> you coming?</td></tr>
             <tr><td>have + participle (Module 5)</td><td>have / has</td><td><b>Have</b> you eaten?</td></tr>
             <tr><td>will / going to (Module 6)</td><td>will / the glue</td><td><b>Will</b> it rain?</td></tr>
           </table>
           <p class="sub">Every tense you have learned already contains its own helper. Move it to the front.</p>`},
    {k:"card", ref:"The question frame", tag:"The idea · 2 of 5", title:"The frame: one helper, one plain verb",
     html:`<div class="frame"><span class="rest">Wh-word</span><span class="glue">helper</span><span class="who">WHO</span><span class="rest">plain verb …?</span></div>
           <div class="right"><b>Where does</b> she <b>work</b>? &nbsp; <b>What did</b> you <b>eat</b>? &nbsp; <b>When will</b> they <b>arrive</b>?</div>
           <p><b>One helper carries the tense.</b> The verb stays plain, the same trick as <i>doesn't work</i> and <i>didn't go</i>:</p>
           <div class="wrong">What did you ate? &nbsp; Where does she works? &nbsp; Where you are going?</div>
           <div class="right">What did you eat? &nbsp; Where does she work? &nbsp; Where are you going?</div>
           <h3>Special case: "Who called you?" (no helper)</h3>
           <p>There are two kinds of <b>who / what</b> questions:</p>
           <div class="right"><b>You don't know who did the action.</b> Put <b>who</b> straight before the verb, with <b>no did</b>: <b>Who called</b> you? &nbsp; <b>What happened</b>? &nbsp; <b>Who knows</b> the answer? <span class="sub">(किसने फ़ोन किया?)</span></div>
           <div class="right"><b>You did the action and ask about someone else.</b> Use the helper: <b>Who did you call</b>? <span class="sub">(तुमने किसे फ़ोन किया?)</span></div>
           <div class="wrong">Who did call you?</div>
           <p class="sub">Easy trick: look at the word right after <b>who</b>. A <b>verb</b> (called, knows, happened) → no <i>did</i>. <b>you / he / she / they</b> → use <i>did</i>.</p>`},
    {k:"order", q:"Build it.", words:["Where","does","she","work"], a:"Where does she work?",
     w:"Wh-word + <b>does</b> + WHO + plain verb. The S lives in <i>does</i>."},
    {k:"order", q:"Same frame, past tense.", words:["What","did","you","eat","for","lunch"], a:"What did you eat for lunch?",
     w:"<b>did</b> carries the past, so <i>eat</i> stays plain."},
    {k:"card", ref:"Wh words", tag:"The idea · 3 of 5", title:"The wh words",
     html:`<table>
             <tr><th>word</th><th>asks about</th><th>example</th></tr>
             <tr><td><b>what</b></td><td>things</td><td>What do you do?</td></tr>
             <tr><td><b>who</b></td><td>people</td><td>Who is that?</td></tr>
             <tr><td><b>where</b></td><td>place</td><td>Where did you go?</td></tr>
             <tr><td><b>when</b></td><td>time</td><td>When is the meeting?</td></tr>
             <tr><td><b>why</b></td><td>reason</td><td>Why are you late?</td></tr>
             <tr><td><b>how</b></td><td>way, manner</td><td>How do you go to work?</td></tr>
             <tr><td><b>whose</b></td><td>owner</td><td>Whose bag is this?</td></tr>
           </table>
           <p><b>how + word</b> asks about amounts: <b>how much</b> (uncountable, price) · <b>how many</b> (countable) · <b>how long</b> · <b>how often</b> · <b>how far</b> · <b>how old</b> · <b>how tall</b>.</p>
           <div class="right">How much does it cost? &nbsp; How many brothers do you have? &nbsp; How often do you go there?</div>`},
    {k:"card", ref:"What vs which", tag:"The idea · 4 of 5", title:"what or which?",
     html:`<p><b>what</b> = any answer is possible (open). <b>which</b> = choose from a set you can see or already know.</p>
           <table>
             <tr><th>what (open)</th><th>which (a limited set)</th></tr>
             <tr><td>What is your favourite colour?</td><td>Which colour do you like, red or blue?</td></tr>
             <tr><td>What time is it?</td><td>Which bus goes to the station? (we know the buses)</td></tr>
             <tr><td>What kind of music do you like?</td><td>Which one is yours?</td></tr>
           </table>
           <p><b>Shortcut:</b> If you could offer two or three choices in the same breath, use <b>which</b>. Otherwise use <b>what</b>.</p>
           <p class="sub">Good to know: <i>What time</i>, <i>what kind of</i> and <i>what colour</i> always use <b>what</b>.</p>`},
    {k:"card", ref:"Indirect questions", tag:"The idea · 5 of 5", title:"Polite questions: no flipping",
     html:`<p>When you start with <i>Could you tell me…</i> or <i>Do you know…</i>, the second part goes back to <b>normal statement order</b>: no helper jump.</p>
           <div class="right">Where is the station? &nbsp; → &nbsp; Could you tell me where <b>the station is</b>?</div>
           <div class="right">Where does he live? &nbsp; → &nbsp; Do you know where <b>he lives</b>?</div>
           <div class="wrong">Do you know where does he live?</div>
           <p>Short answers keep the helper: <b>Yes, I do. &nbsp; No, she doesn't. &nbsp; Yes, he did.</b></p>
           <p class="sub">Indirect questions sound softer and more polite. Great for strangers, bosses, and phone calls.</p>`},
    {k:"mcq", q:"___ she live here?", o:["Do","Does","Is"], a:1,
     w:["\"she\" needs <b>does</b>.","Yes. one person + habit → <b>Does</b>.","<i>Is</i> goes with feelings and places, not an action like <i>live</i>."]},
    {k:"mcq", q:"What did you ___ for dinner?", o:["ate","eaten","eat"], a:2,
     w:["<i>Did</i> already carries the past.","<i>Did</i> + participle is not used.","Yes. <b>did</b> + plain verb: eat."]},
    {k:"mcq", q:"Which is correct?", o:["Where you are going?","Where are you going?","Where do you going?"], a:1,
     w:["The helper (the glue <i>are</i>) must come before WHO.","Yes. Wh-word + glue + WHO + -ing.","<i>Do</i> and <i>going</i> don't go together. Use the glue <i>are</i>."]},
    {k:"order", q:"Translate to English.", hi:"तुम कहाँ रहते हो?", words:["Where","do","you","live"], a:"Where do you live?",
     w:"A habit → <b>do</b> + plain verb."},
    {k:"order", q:"Translate to English.", hi:"उसने तुम्हें कल क्यों फ़ोन किया?", words:["Why","did","she","call","you","yesterday"], a:"Why did she call you yesterday?",
     w:"Past → <b>did</b> + plain verb: <i>call</i>."},
    {k:"mcq", q:"Which is correct?", o:["Who did call you?","Who called you?","Who does called you?"], a:1,
     w:["When <i>who</i> comes straight before the verb, there is no helper.","Yes. <b>Who called you?</b> (answer: \"Raj.\")","Two helpers, and the verb is not plain."]},
    {k:"mcq", q:"___ is your phone number?", o:["Which","Who","What"], a:2,
     w:["<i>Which</i> needs a set to choose from.","<i>Who</i> asks about people.","Yes. An open answer → <b>What</b>."]},
    {k:"mcq", q:"There are two buses. ___ one goes to the station?", o:["What","Which","Who"], a:1,
     w:["There are only two, so it's a set.","Yes. A limited set → <b>Which</b>.","<i>Who</i> asks about people."]},
    {k:"type", q:"How ___ is the station from here? <span class='sub'>(distance)</span>", a:["far"], w:"<b>how far</b> asks about distance."},
    {k:"order", q:"Translate to English.", hi:"तुम्हारा घर यहाँ से कितनी दूर है?", words:["How","far","is","your","house","from","here"], a:"How far is your house from here?",
     w:"<b>How far</b> + glue + WHO. Here <i>is</i> is the Module 1 glue."},
    {k:"mcq", q:"Could you tell me where ___?", o:["is the station","the station is","does the station is"], a:1,
     w:["After <i>Could you tell me</i>, don't flip.","Yes. Normal order: <b>where the station is</b>.","Two mistakes in one."]},
    {k:"type", q:"Translate to English.", hi:"तुम्हारा नाम क्या है?", a:["What is your name?","What's your name?"], w:"<b>What is your name?</b> Open answer → what."},
    {k:"order", q:"Translate to English.", hi:"क्या तुमने खाना खा लिया है?", words:["Have","you","eaten","yet"], a:"Have you eaten yet?",
     w:"Module 5's helper <b>have</b> goes first, then WHO + participle."},
    {k:"mcq", q:"Revision from Module 6: ___ you going to attend the meeting?", o:["Do","Are","Will"], a:1,
     w:["<i>Do</i> doesn't pair with <i>going to</i>.","Yes. <b>going to</b> uses the glue: <b>Are</b> you going to…?","<i>Will you going to</i> is wrong. Pick one future form."]},
    {k:"build", intro:"Your turn. Ask real questions you'd like answered. Type each one and say it out loud.",
     items:[
      {p:"Ask a yes/no question with Do or Does.", frame:"Do you ______? / Does she ______?", ex:"Do you like spicy food?", must:/^\s*(do|does)\b/i, ok:"Helper first, plain verb after. Right.", tip:"Start with <b>Do</b> (you/I/we/they) or <b>Does</b> (he/she/it)."},
      {p:"Ask me about something in the past, starting with Did or a wh word + did.", frame:"What did you ______? / Did you ______?", ex:"What did you do yesterday?", must:/^\s*(did|what did|where did|when did|why did|who did|how did)\b/i, ok:"<i>did</i> + plain verb.", tip:"<b>Did you ...?</b> or <b>Where did you ...?</b>"},
      {p:"Ask me about my plans.", frame:"What are you going to ______?", ex:"What are you going to do this weekend?", must:/\bgoing to\b/i, ok:"A real plan question.", tip:"Use <b>What are you going to ...?</b>"},
      {p:"Ask a question with Which, offering two choices.", frame:"Which do you prefer, ______ or ______?", ex:"Which do you prefer, tea or coffee?", must:/\bwhich\b/i, ok:"A set of choices → <b>which</b>.", tip:"<b>Which ... , A or B?</b>"},
      {p:"Ask politely, starting with Could you tell me.", frame:"Could you tell me where ______ is?", ex:"Could you tell me where the station is?", must:/could you tell me/i, ok:"Polite and in normal order. Perfect.", tip:"<b>Could you tell me where ...</b> + normal word order."}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"Where you are going?", good:"Where are you going?", fix:"Put the helper (the glue <i>are</i>) before WHO."},
      {bad:"What did you ate?", good:"What did you eat?", fix:"<i>Did</i> carries the past. The verb stays plain."},
      {bad:"Does she works here?", good:"Does she work here?", fix:"<i>Does</i> has the S. The verb stays plain."},
      {bad:"Who did call you?", good:"Who called you?", fix:"When <i>who/what</i> comes straight before the verb, there is no helper."},
      {bad:"Do you know where does he live?", good:"Do you know where he lives?", fix:"After <i>Do you know / Could you tell me</i>, use normal statement order."}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: The Interviewer", pass:0.8,
     intro:"You are interviewing someone for a story, and every question must be right. This also revisits Modules 1 to 6. You need 8 of 10.",
     qs:[
      {k:"mcq", ref:"The question frame", q:"Which question is correct?", o:["Where does she works?","Where does she work?","Where she works?"], a:1, w:["<i>Does</i> already has the S.","Yes: wh-word + <b>does</b> + WHO + plain verb.","The helper is missing."]},
      {k:"order", ref:"The question frame", q:"Build the question.", words:["What","did","you","eat","for","lunch"], a:"What did you eat for lunch?", w:"<b>did</b> + plain verb."},
      {k:"mcq", ref:"Two kinds of questions", q:"Which question can be answered with just yes or no?", o:["Where do you live?","Do you live here?","Why do you live here?"], a:1, w:["That asks for a place.","Yes: a helper-first question with no wh-word.","That asks for a reason."]},
      {k:"type", ref:"Wh words", q:"___ much does this cost? <span class='sub'>(one word)</span>", a:["how"], w:"<b>How much</b> asks about price."},
      {k:"mcq", ref:"What vs which", q:"I have a red shirt and a blue shirt. ___ one should I wear?", o:["What","Which","Who"], a:1, w:["There's a set of two.","Yes: a limited set → <b>Which</b>.","<i>Who</i> asks about people."]},
      {k:"mcq", ref:"What vs which", q:"___ time does the film start?", o:["Which","Who","What"], a:2, w:["<i>What time</i> is the fixed phrase.","<i>Who</i> asks about people.","Yes: <b>What time</b>."]},
      {k:"order", ref:"The question frame", q:"Translate to English.", hi:"तुम कल कहाँ गए थे?", words:["Where","did","you","go","yesterday"], a:"Where did you go yesterday?", alt:["Where did you go yesterday?"], w:"Past → <b>did</b> + plain verb."},
      {k:"type", ref:"The question frame", q:"Translate to English.", hi:"वह कब आ रहा है? (he)", a:["When is he coming?","When's he coming?"], w:"<b>When is he coming?</b> The glue is the helper (Module 3)."},
      {k:"mcq", ref:"Indirect questions", q:"Do you know where ___?", o:["she lives","does she live","she does live"], a:0, w:["Yes: after <i>Do you know</i>, normal order.","Don't flip after <i>Do you know</i>.","Two helpers."]},
      {k:"mcq", ref:"The question frame", q:"Who ___ the window? Sam broke it.", o:["broke","did break","did broke"], a:0, w:["Yes: <b>Who broke</b> the window? Who is straight before the verb, so no helper.","No helper when <i>who</i> comes straight before the verb.","Two mistakes."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Ask any yes/no question, in any tense: <i>Do you like tea? Did you call? Have you eaten? Will it rain?</i>",
          "Ask for information: <i>Where does she work? What did you eat? How far is it?</i> and choose between <i>what</i> and <i>which</i>.",
          "Ask politely: <i>Could you tell me where the station is?</i>"],
     teaser:"Next: <b>Modals.</b> Can, could, should, must, would: ask for permission, give advice and be polite."}
  ]
});
