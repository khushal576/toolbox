registerModule({
  id: 6,
  title: "Future",
  sub: "will, going to and plans",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 6 · Start here", title:"The lunch bill",
     html:`<p>You and a friend finish lunch. Your friend looks in their wallet and says, <b>"Oh no, I forgot my money."</b></p>
           <p>You want to say, kindly and fast, <i>"Don't worry, I'm paying."</i> Which words come out of your mouth? English has more than one way to talk about the future, and the choice says something about <i>you</i>.</p>`},
    {k:"mcq", q:"Your friend forgot their money. You decide, right now, to pay. What do you say?",
     o:["I pay.","I'm paying.","I'm going pay.","I'll pay."], a:3,
     w:["<i>I pay</i> is a habit (Module 2), not a decision.",
        "<i>I'm paying</i> means it was already arranged (Module 3's -ing, more later).",
        "Close, but <i>going</i> needs <b>to</b>, and this decision just happened.",
        "Yes! <b>will</b> is the tool for decisions, offers and promises made <i>right now</i>."]},
    {k:"card", ref:"What it is for", tag:"The idea · 1 of 6", title:"There is no single future tense",
     html:`<p>English has no future verb ending (like <i>-ed</i> for the past). Instead we pick a small helper, depending on <b>how you feel about the future</b>:</p>
           <div class="right"><b>will</b>: you decide now, you offer, you promise, you predict. <i>I'll help you.</i></div>
           <div class="right"><b>going to</b>: you already planned it, or you can see it coming. <i>I'm going to study tonight.</i></div>
           <div class="right"><b>am/is/are + -ing</b>: it's arranged, with a time and often a person. <i>I'm meeting Raj at six.</i></div>
           <p>Good news: all three build on pieces you already own (<i>glue</i> from Module 1, <i>-ing</i> from Module 3).</p>`},
    {k:"card", ref:"will", tag:"The idea · 2 of 6", title:"will: the simplest one",
     html:`<div class="frame"><span class="who">I</span><span class="glue">will</span><span class="rest">help you.</span></div>
           <div class="frame"><span class="who">She</span><span class="glue">will</span><span class="rest">help you.</span></div>
           <p><b>Same word for every WHO</b>, then the <b>plain verb</b>. No S (Module 2), no -ing, no <i>to</i>. Nothing to conjugate.</p>
           <div class="wrong">She wills help. &nbsp; I will to help. &nbsp; I will helps.</div>
           <p><b>Speaking:</b> <i>I'll, you'll, she'll, we'll, they'll</i>. <b>No:</b> <i>won't</i> (= will not). <b>Question:</b> the helper jumps first: <i>Will you help me?</i></p>
           <p><b>Use will for:</b></p>
           <div class="right">a decision made now: <i>It's hot. I'll open the window.</i></div>
           <div class="right">an offer or promise: <i>I'll carry that. I won't tell anyone.</i></div>
           <div class="right">a prediction with <i>I think / probably</i>: <i>It will probably rain.</i></div>
           <p class="sub">Short answers keep the full form: <b>Yes, I will. &nbsp; No, I won't.</b> Not "Yes, I'll."</p>`},
    {k:"order", q:"Build it.", words:["I","will","help","you"], a:"I will help you.",
     w:"WHO + <b>will</b> + plain verb. That's the whole thing."},
    {k:"order", q:"Say no.", words:["He","won't","come","tomorrow"], a:"He won't come tomorrow.", alt:["Tomorrow he won't come."],
     w:"<b>won't</b> (will not) + plain verb. No S on <i>come</i>."},
    {k:"card", ref:"going to", tag:"The idea · 3 of 6", title:"going to: plans and evidence",
     html:`<p>This one is old friends joined together: the glue (Module 1) + <i>going</i> (Module 3) + <b>to</b> + plain verb.</p>
           <div class="frame"><span class="who">I</span><span class="glue">am going to</span><span class="rest">study tonight.</span></div>
           <div class="frame"><span class="who">She</span><span class="glue">is going to</span><span class="rest">study tonight.</span></div>
           <p>The glue changes (am/is/are). After <b>to</b>, always the plain verb.</p>
           <p><b>Use going to for:</b></p>
           <div class="right">a plan you made <i>before</i> speaking: <i>I'm going to visit my cousin on Sunday.</i></div>
           <div class="right">something you can <i>see</i> is about to happen: <i>Look at those clouds. It's going to rain.</i></div>
           <p>No: <i>I'm not going to cook.</i> Question: <i>Are you going to come?</i> In fast, casual speech people say <b>"gonna"</b>. Understand it, but write <i>going to</i>.</p>`},
    {k:"card", ref:"Will or going to?", tag:"The idea · 4 of 6", title:"will or going to? How to choose",
     html:`<table>
             <tr><th>Ask yourself</th><th>Use</th></tr>
             <tr><td>Did I decide <b>just now</b>?</td><td><b>will</b></td></tr>
             <tr><td>Am I <b>offering</b> or <b>promising</b>?</td><td><b>will</b></td></tr>
             <tr><td>Was the plan <b>already made</b>?</td><td><b>going to</b></td></tr>
             <tr><td>Can I <b>see</b> it coming now?</td><td><b>going to</b></td></tr>
           </table>
           <p>Same situation, two speakers:</p>
           <div class="right">"There's no milk." &nbsp; "<b>I'll</b> buy some." <span class="sub">(decides now)</span></div>
           <div class="right">"Why are you going out?" &nbsp; "I'<b>m going to</b> buy milk." <span class="sub">(already planned)</span></div>
           <p class="sub">Native speakers often use either one in casual talk. But for <b>offers, promises and quick decisions</b>, <i>will</i> sounds right, and for <b>plans and evidence</b>, <i>going to</i> does.</p>`},
    {k:"card", ref:"Plans with -ing", tag:"The idea · 5 of 6", title:"The fixed arrangement: am / is / are + -ing",
     html:`<p>Module 3's <i>-ing</i> can also mean future, <b>if there is a time or a fixed arrangement</b>:</p>
           <div class="right">I'm meeting Raj at six. <span class="sub">(we both agreed)</span></div>
           <div class="right">She's flying to Delhi on Friday. <span class="sub">(the ticket is booked)</span></div>
           <div class="right">What are you doing this weekend?</div>
           <p>Compare: <i>I'm meeting Raj at six</i> (fixed) vs <i>I'll meet Raj</i> (decided now) vs <i>I'm going to meet Raj</i> (planned, not fixed).</p>
           <p class="sub">Without a time word, <i>-ing</i> means <i>right now</i> (Module 3). The time word is what pushes it into the future.</p>`},
    {k:"card", ref:"Time words", tag:"The idea · 6 of 6", title:"Time words, and one trap",
     html:`<p><b>Future time words:</b> tomorrow, tonight, next week / month / year, soon, later, in an hour, in two days, this weekend.</p>
           <p><b>The trap:</b> after <b>when, before, after, as soon as</b>, the verb stays in the <b>simple present</b>, even though the meaning is future. <i>Will</i> goes only in the main part:</p>
           <div class="wrong">I'll call you when I will arrive.</div>
           <div class="right">I'll call you when I <b>arrive</b>.</div>
           <div class="right">Let's eat before the film <b>starts</b>.</div>
           <p>Also: don't use the simple present alone for a decision. <i>Tomorrow I go to Delhi</i> sounds wrong. Say <i>I'll go</i>, <i>I'm going to go</i> or <i>I'm going</i>.</p>`},
    {k:"mcq", q:"It's hot in here. ___ the window.", o:["I opened","I'll open","I'm open"], a:1,
     w:["<i>Opened</i> is the past (Module 4).","Yes. A decision made now → <b>I'll open</b>.","<i>I'm open</i> means something else entirely."]},
    {k:"mcq", q:"Look at those black clouds! It ___ rain.", o:["goes to","is going to","has gone to"], a:1,
     w:["<i>Goes to</i> is not a future form.","Yes. You can <i>see</i> it coming → <b>is going to</b>.","<i>Has gone to</i> is a Module 5 shape: a different meaning."]},
    {k:"type", q:"She will ___ (call) you tonight.", a:["call"], w:"After <b>will</b>, always the plain verb: call. No S, no -ing."},
    {k:"type", q:"We are going ___ visit Goa next month. <span class='sub'>(one small word)</span>", a:["to"], w:"<b>going to</b> + plain verb. Don't forget <b>to</b>."},
    {k:"order", q:"Translate to English.", hi:"मैं कल तुम्हें फ़ोन करूँगा।", words:["I","will","call","you","tomorrow"], a:"I will call you tomorrow.", alt:["Tomorrow I will call you."],
     w:"Decision/promise → <b>will</b> + plain verb."},
    {k:"order", q:"Translate to English.", hi:"हम अगले हफ़्ते गोवा घूमने जाने वाले हैं।", words:["We","are","going","to","visit","Goa","next","week"], a:"We are going to visit Goa next week.", alt:["Next week we are going to visit Goa."],
     w:"A plan → glue + <b>going to</b> + plain verb."},
    {k:"mcq", q:"Don't worry. I ___ tell anyone.", o:["don't","won't","am not"], a:1,
     w:["<i>Don't</i> is about habits, not a promise.","Yes. A promise → <b>won't</b> (will not).","<i>Am not</i> is Module 1's glue, not a promise."]},
    {k:"order", q:"Translate to English.", hi:"वह शायद देर से आएगा।", words:["He","will","probably","be","late"], a:"He will probably be late.",
     w:"<b>will</b> + <i>probably</i> + plain verb. Here the verb is <b>be</b>, the same verb as Module 1."},
    {k:"mcq", q:"Will you help me? — Yes, I ___.", o:["'ll","will","am"], a:1,
     w:["Never shrink at the end of an answer.","Yes. Short answers keep the full form: <b>Yes, I will.</b>","The question used <i>will</i>, so the answer uses <i>will</i>."]},
    {k:"order", q:"Translate to English.", hi:"मैं आज रात खाना नहीं बनाऊँगा।", words:["I","am","not","going","to","cook","dinner","tonight"], a:"I am not going to cook dinner tonight.", alt:["Tonight I am not going to cook dinner."],
     w:"Negative of <b>going to</b>: glue + <b>not</b> + going to + plain verb."},
    {k:"type", q:"Translate to English. <span class='sub'>(use will)</span>", hi:"मैं तुम्हारी मदद करूँगा।", a:["I will help you.","I'll help you.","i will help you"], w:"<b>I will help you</b> / <b>I'll help you</b>. An offer → will."},
    {k:"order", q:"Build the question.", words:["What","are","you","going","to","do","this","weekend"], a:"What are you going to do this weekend?", w:"Question word + glue + WHO + going to + plain verb."},
    {k:"mcq", q:"I ___ the dentist at 5 pm tomorrow. I have an appointment.", o:["will see","am seeing","see"], a:1,
     w:["<i>Will see</i> is for a decision made now. This is already booked.","Yes. A fixed arrangement with a time → <b>am + -ing</b>.","The simple present can't carry a personal plan like this."]},
    {k:"mcq", q:"I'll call you when I ___ home.", o:["will get","get","got"], a:1,
     w:["No <i>will</i> after <i>when</i>. It's in the main part only.","Yes. After <b>when</b>, use the simple present: when I <b>get</b> home.","<i>Got</i> is the past, but the meaning is future."]},
    {k:"mcq", q:"Revision from Module 4: Last year she ___ in Pune. Next year she ___ in Delhi.", o:["lived / will live","will live / lived","lives / lives"], a:0,
     w:["Yes. <b>Last year</b> → lived (past). <b>Next year</b> → will live (future).","The order is reversed.","Both clues point away from the present."]},
    {k:"build", intro:"Your turn. Real sentences about <b>your own future</b>. Type each one and say it out loud.",
     items:[
      {p:"Tell me one plan for this weekend.", frame:"This weekend I am going to ______.", ex:"This weekend I'm going to visit my grandparents.", must:/\b(i am going to|i'm going to|i'm gonna)\b/i, ok:"A plan → <b>going to</b>. Right.", tip:"Use <b>I'm going to</b> + a plain verb."},
      {p:"Offer to help someone right now.", frame:"I'll ______.", ex:"I'll carry your bag.", must:/\b(i'll|i will)\s+\w+/i, ok:"A quick offer → <b>will</b>.", tip:"<b>I'll</b> + a plain verb: I'll help / I'll carry / I'll call."},
      {p:"Make a prediction about tomorrow.", frame:"I think it will ______.", ex:"I think it will rain tomorrow.", must:/\bwill\b/i, ok:"Prediction + <b>will</b>.", tip:"Use <b>I think ... will</b>."},
      {p:"Say something you will never do.", frame:"I will never ______.", ex:"I will never give up.", must:/(will never|'ll never|won't)/i, ok:"<i>will never</i> + plain verb.", tip:"<b>I will never</b> + plain verb, or <b>I won't</b>."},
      {p:"Ask me about my plans.", frame:"What are you going to ______?", ex:"What are you going to do tomorrow?", must:/^\s*(what|are|will|where|when|who)\b.*\b(going to|will)\b/i, ok:"A real future question.", tip:"<b>What are you going to ...?</b> or <b>Will you ...?</b>"}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"I will to go. / She will goes.", good:"I will go. / She will go.", fix:"After <b>will</b>, only the plain verb: no <i>to</i>, no S, no -ing."},
      {bad:"I'll call you when I will arrive.", good:"I'll call you when I arrive.", fix:"After when / before / after / as soon as, use the simple present."},
      {bad:"Tomorrow I go to Delhi.", good:"Tomorrow I'm going to Delhi. / I'll go to Delhi.", fix:"A plan or decision needs <i>will</i>, <i>going to</i> or <i>-ing</i>. The plain present is for habits."},
      {bad:"Yes, I'll.", good:"Yes, I will.", fix:"Never shrink at the end of an answer."},
      {bad:"I'm going cook tonight.", good:"I'm going to cook tonight.", fix:"Don't forget the little word <b>to</b>."}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: The Fortune Teller", pass:0.8,
     intro:"A fortune teller needs you to predict and plan. This also revisits Modules 1 to 5. You need 8 of 10.",
     qs:[
      {k:"mcq", ref:"will", q:"Which is correct?", o:["She will helps you.","She will help you.","She wills help you."], a:1, w:["After <i>will</i>, no S.","Yes: <b>will + plain verb</b>.","<i>Will</i> never changes."]},
      {k:"type", ref:"will", q:"He will ___ (come) tomorrow.", a:["come"], w:"After <b>will</b>, the plain verb: come."},
      {k:"mcq", ref:"going to", q:"Look! The baby ___ fall!", o:["will fall","is going to fall","goes to fall"], a:1, w:["Evidence you can <i>see</i> → <i>going to</i> is the natural choice.","Yes: <b>is going to</b> (you can see it coming).","<i>Goes to</i> is not a future form."]},
      {k:"order", ref:"going to", q:"Build the question.", words:["Are","you","going","to","join","us"], a:"Are you going to join us?", w:"Glue first, then WHO, then going to + plain verb."},
      {k:"mcq", ref:"Will or going to?", q:"The phone is ringing. What do you say?", o:["I answer it.","I'll answer it.","I'm answered it."], a:1, w:["A habit form can't make a decision.","Yes: a quick decision → <b>I'll</b>.","<i>Answered</i> is the past."]},
      {k:"order", ref:"will", q:"Translate to English.", hi:"वह कल नहीं आएगा।", words:["He","won't","come","tomorrow"], a:"He won't come tomorrow.", alt:["Tomorrow he won't come."], w:"<b>won't</b> + plain verb."},
      {k:"order", ref:"going to", q:"Translate to English.", hi:"मैं इस साल नई नौकरी ढूँढने वाला हूँ।", words:["I","am","going","to","look","for","a","new","job","this","year"], a:"I am going to look for a new job this year.", alt:["This year I am going to look for a new job."], w:"A plan → glue + <b>going to</b> + plain verb."},
      {k:"mcq", ref:"Time words", q:"I'll call you when I ___ there.", o:["get","will get","got"], a:0, w:["Yes: after <b>when</b>, the simple present.","No <i>will</i> after <i>when</i>.","Past form, but the meaning is future."]},
      {k:"mcq", ref:"Plans with -ing", q:"I ___ Raj at six. We fixed it yesterday.", o:["will meet","am meeting","meet"], a:1, w:["<i>Will</i> is for a decision made now.","Yes: a fixed arrangement → <b>am meeting</b>.","The plain present is a habit."]},
      {k:"mcq", ref:"What it is for", q:"Revision: which is correct?", o:["I will see him yesterday.","I saw him yesterday.","I will saw him tomorrow."], a:1, w:["<i>Yesterday</i> is past: it needs <i>saw</i>.","Yes: finished time → <b>saw</b> (Module 4).","After <i>will</i>, the plain verb: <i>will see</i>."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Make decisions, offers and promises: <i>I'll help you. I'll call you later. I won't tell anyone.</i>",
          "Talk about plans: <i>I'm going to study tonight. We're going to visit Goa next week.</i>",
          "Say fixed arrangements and ask about plans: <i>I'm meeting Raj at six. What are you doing this weekend?</i>"],
     teaser:"Next: <b>Questions.</b> Do, does, did, what vs which: ask anything, in any tense, without freezing."}
  ]
});
