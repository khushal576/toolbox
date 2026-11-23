registerModule({
  id: 15,
  title: "Real situations",
  sub: "introduce, ask for help, disagree, complain, tell a story, phone",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 15 · Start here", title:"Grammar is the engine. This is the road.",
     html:`<p>You now know the engine: tenses, questions, modals, connectors. This module is the road test. Six real situations you will face again and again, each with ready-made phrases you can use today.</p>
           <p>First, a quick one. You ordered soup, and the waiter brought salad.</p>`},
    {k:"mcq", q:"You ordered soup, but you got salad. What do you say?",
     o:["This is the wrong food!","You made a mistake.","Take this back.","Excuse me, I ordered the soup, but I got the salad. Could you check, please?"], a:3,
     w:["It is true but it sounds like an attack.","Blaming the person makes them defensive.","That's an order, not a request.","Yes! <b>Excuse me</b> + the facts + <b>Could you…, please?</b>: calm, clear and polite."]},
    {k:"card", ref:"Introduce yourself", tag:"Situation 1 of 6", title:"Introduce yourself",
     html:`<p><b>The 6-step template:</b> greet → name → where you're from → what you do → one interest → ask back.</p>
           <div class="right">"<b>Hi, I'm Raj.</b> Nice to meet you. <b>I'm from Pune</b>, but I live in Mumbai now. <b>I work as</b> an accountant. <b>In my free time</b> I like playing cricket. <b>What about you?</b>"</div>
           <table>
             <tr><th>you say</th><th>they say</th></tr>
             <tr><td>Nice to meet you.</td><td>Nice to meet you too. / Pleased to meet you.</td></tr>
             <tr><td>How are you?</td><td>I'm fine, thanks. And you?</td></tr>
           </table>
           <p><b>Small talk questions:</b> Where are you from? · What do you do? · How long have you lived here? · What do you do in your free time?</p>
           <div class="wrong">My good name is Raj. &nbsp; I am agree with you.</div>
           <p class="sub">Always finish with a question (<i>What about you?</i>). That keeps the conversation alive.</p>`},
    {k:"card", ref:"Ask for help", tag:"Situation 2 of 6", title:"Ask for help",
     html:`<p>Start with <b>Excuse me</b> or <b>Sorry to bother you</b>, then <b>Could you…</b>, and end with <b>thanks</b>:</p>
           <div class="right">Excuse me, <b>could you help me</b>? &nbsp; <b>Could you tell me</b> how to get to the station?</div>
           <p><b>When you don't understand</b> (very useful, never be shy):</p>
           <div class="right">Sorry, <b>I didn't catch that</b>. Could you say it again? &nbsp; Could you speak a bit <b>more slowly</b>?</div>
           <div class="right">What does <i>deadline</i> <b>mean</b>? &nbsp; How do you <b>say</b> <i>चाबी</i> in English? &nbsp; How do you <b>spell</b> that?</div>
           <p><b>Directions:</b> go straight · turn left / right · at the corner · opposite · next to · behind · on your left</p>
           <div class="right">Thanks a lot, that's very helpful. &nbsp; I really appreciate it.</div>`},
    {k:"card", ref:"Disagree politely", tag:"Situation 3 of 6", title:"Disagree politely",
     html:`<p>(Module 12's formula again.) <b>Acknowledge → but → your view.</b></p>
           <table>
             <tr><td><b>I see your point, but</b> I think…</td><td><b>I'm afraid</b> I don't agree.</td></tr>
             <tr><td><b>That's true, but</b> have you thought about…?</td><td><b>I'm not sure</b> about that.</td></tr>
             <tr><td><b>I understand</b>, but…</td><td>Maybe, but…</td></tr>
           </table>
           <p><b>Find a middle way:</b> <i>How about…? &nbsp; Why don't we…? &nbsp; Let's meet in the middle.</i></p>
           <div class="wrong">You are wrong. &nbsp; That's nonsense.</div>
           <div class="right">I see what you mean, but I think the other plan is cheaper.</div>
           <p class="sub">Soften with <b>I think, maybe, a bit, honestly, I'm afraid</b>.</p>`},
    {k:"card", ref:"Complain", tag:"Situation 4 of 6", title:"Complain without making enemies",
     html:`<p><b>Formula:</b> <i>Excuse me</i> + <b>the facts</b> (no blame) + <b>what you want</b>.</p>
           <div class="right">Excuse me, <b>I ordered</b> the food an hour ago, and <b>it hasn't arrived yet</b>. <b>Could you check</b>, please?</div>
           <div class="right">The AC in my room <b>isn't working</b>. <b>Could someone fix it</b>, please?</div>
           <div class="right">I'm sorry to bother you, but <b>I'd like a refund</b> / a replacement.</div>
           <p>Facts use tenses you know: <b>present perfect</b> for "still not happened" (<i>hasn't arrived yet</i>), <b>past</b> for what you did (<i>I ordered</i>), <b>present</b> for the state now (<i>isn't working</i>).</p>
           <div class="wrong">Your service is terrible! &nbsp; Give me my money back.</div>
           <p class="sub">Stay calm, stay polite, be clear about the solution you want. It works much better than shouting.</p>`},
    {k:"card", ref:"Tell a story", tag:"Situation 5 of 6", title:"Tell a story",
     html:`<p><b>Structure:</b> set the scene → what happened (in order) → the problem → how it ended → how you felt.</p>
           <div class="right"><b>It was</b> a rainy evening. I <b>was walking</b> home <b>when</b> I saw a puppy. <b>First</b>, I ignored it. <b>Then</b> it followed me. <b>In the end</b> I took it home!</div>
           <p><b>New and tiny: <i>was / were + -ing</i></b> = what was in progress in the background. The short event that interrupts it uses the past simple, joined with <b>when</b>:</p>
           <div class="right">I <b>was walking</b> home <b>when</b> it <b>started</b> to rain.</div>
           <p><b>Story words:</b> So… · Then… · After that… · Suddenly… · Anyway… · Finally… · Guess what happened? · You won't believe it.</p>
           <p class="sub">Use the <b>past simple</b> (Module 4) for events, <b>sequence words</b> (Module 11) to keep order.</p>`},
    {k:"card", ref:"Phone calls", tag:"Situation 6 of 6", title:"Phone calls",
     html:`<table>
             <tr><th>you want to…</th><th>say</th></tr>
             <tr><td>start</td><td>Hello, <b>this is Raj speaking</b>. &nbsp; <b>I'm calling about</b> your advertisement.</td></tr>
             <tr><td>ask for someone</td><td><b>Could I speak to</b> Mr Sharma, <b>please</b>?</td></tr>
             <tr><td>answer: that's me</td><td><b>Speaking.</b> / This is he / she.</td></tr>
             <tr><td>they aren't there</td><td>I'm afraid he isn't here. <b>Can I take a message?</b></td></tr>
             <tr><td>ask to wait</td><td><b>Hold on a moment</b>, please.</td></tr>
             <tr><td>bad line</td><td>Sorry, <b>the line is bad</b>. Could you repeat that?</td></tr>
             <tr><td>end</td><td>Thanks for calling. &nbsp; <b>I'll call back later.</b> &nbsp; Bye.</td></tr>
           </table>
           <p><b>Numbers:</b> say them one digit at a time: <i>nine-eight-seven…</i></p>
           <div class="wrong">Who are you? &nbsp; He not here. Wrong number.</div>
           <div class="right">Who's calling, please? &nbsp; I'm afraid he isn't here.</div>`},
    {k:"mcq", q:"Which is the best way to introduce yourself?", o:["My name Raj, I from Pune.","Hi, I'm Raj. I'm from Pune.","I am Raj Pune."], a:1,
     w:["The glue (am / are) is missing (Module 1).","Yes. Greeting + <b>I'm</b> + the facts.","Missing words."]},
    {k:"mcq", q:"Someone says, \"Nice to meet you.\" What do you say?", o:["Nice to meet you too.","Me also nice.","Thank you very much."], a:0,
     w:["Yes. The natural reply.","Not natural English.","Doesn't answer the greeting."]},
    {k:"order", q:"Build it.", words:["Could","you","tell","me","how","to","get","to","the","station"], a:"Could you tell me how to get to the station?",
     w:"<b>Could you tell me how to …</b> is the polite direction question (Module 7)."},
    {k:"mcq", q:"You didn't hear what he said. What do you say?", o:["What?","Sorry, I didn't catch that. Could you say it again?","Say again."], a:1,
     w:["Short and rude.","Yes. Polite and clear.","Blunt."]},
    {k:"order", q:"Translate to English.", hi:"माफ़ कीजिए, क्या आप मेरी मदद कर सकते हैं?", words:["Excuse","me","could","you","help","me"], a:"Excuse me, could you help me?",
     w:"<b>Excuse me</b> + <b>could you…?</b>"},
    {k:"mcq", q:"Your friend says, \"Cricket is boring.\" You disagree politely:", o:["No, you're wrong.","I see what you mean, but I think it's exciting.","That's silly."], a:1,
     w:["Blunt.","Yes. Acknowledge + <b>but</b> + your view.","Rude."]},
    {k:"mcq", q:"You can't agree where to eat. A friendly compromise:", o:["How about trying the Italian place?","Do what I say.","I don't care."], a:0,
     w:["Yes. A suggestion keeps things friendly.","Bossy.","Unhelpful."]},
    {k:"order", q:"Translate to English.", hi:"मैंने एक घंटे पहले खाना मँगाया था, पर वह अभी तक नहीं आया।", words:["I","ordered","food","an","hour","ago","but","it","hasn't","arrived","yet"], a:"I ordered food an hour ago, but it hasn't arrived yet.",
     w:"<b>ordered</b> (past, a finished time) + <b>hasn't arrived yet</b> (present perfect)."},
    {k:"mcq", q:"The AC in your hotel room isn't working. The best complaint:", o:["Your hotel is terrible!","Excuse me, the AC in my room isn't working. Could someone fix it, please?","Fix the AC now."], a:1,
     w:["Attacks the hotel.","Yes. Facts + a polite request.","An order."]},
    {k:"mcq", q:"I ___ walking home when it started to rain.", o:["was","were","am"], a:0,
     w:["Yes. <b>was + -ing</b> = in progress in the past.","<i>Were</i> is for you/we/they.","<i>Am</i> is the present."]},
    {k:"mcq", q:"Which is correct for a story?", o:["Yesterday I go to the market and I see my friend.","Yesterday I went to the market and I saw my friend.","Yesterday I am going to the market."], a:1,
     w:["A story about the past needs past verbs.","Yes. <b>went</b>, <b>saw</b>.","Doesn't tell a finished story."]},
    {k:"type", q:"Translate to English.", hi:"मैं राज बोल रहा हूँ।", a:["This is Raj speaking.","Raj speaking.","This is Raj."], w:"<b>This is Raj speaking.</b>"},
    {k:"mcq", q:"You answer a call for a colleague who is out. You say:", o:["He not here.","I'm afraid he isn't here. Can I take a message?","Wrong number."], a:1,
     w:["The glue is missing, and it's blunt.","Yes. Polite and helpful.","Not true, and rude."]},
    {k:"order", q:"Translate to English.", hi:"क्या मैं श्री शर्मा से बात कर सकता हूँ?", words:["Could","I","speak","to","Mr","Sharma","please"], a:"Could I speak to Mr Sharma, please?",
     w:"<b>Could I speak to…, please?</b>"},
    {k:"type", q:"Translate to English.", hi:"माफ़ कीजिए, लाइन ख़राब है। क्या आप दोबारा बोल सकते हैं?", a:["Sorry, the line is bad. Could you say that again?","Sorry, the line is bad. Could you repeat that?"], w:"<b>The line is bad. Could you say that again?</b>"},
    {k:"order", q:"Translate to English.", hi:"आपसे मिलकर अच्छा लगा।", words:["Nice","to","meet","you"], a:"Nice to meet you.",
     w:"The classic greeting."},
    {k:"mcq", q:"Revision from Module 14: She said she ___ be late.", o:["will","would","is"], a:1,
     w:["Step back: <i>will → would</i>.","Yes. <b>said she would</b>.","<i>Is</i> doesn't step back."]},
    {k:"build", intro:"Your turn: <b>six real situations</b>, one sentence group each. Type them and say them out loud like you are really there.",
     items:[
      {p:"Introduce yourself in two or three sentences.", frame:"Hi, I'm ______. I'm from ______. I ______.", ex:"Hi, I'm Raj. I'm from Pune. I work as an accountant.", must:/\b(i'm|i am)\b/i, ok:"A clear introduction.", tip:"<b>Hi, I'm ... I'm from ... I work as / study ...</b>"},
      {p:"Ask a stranger politely how to get to the station.", frame:"Excuse me, could you tell me how to get to ______?", ex:"Excuse me, could you tell me how to get to the station?", must:/\b(could|can|would)\b.*\b(you|me)\b/i, ok:"Polite and clear.", tip:"<b>Excuse me, could you tell me how to get to ...?</b>"},
      {p:"Politely disagree with: \"Winter is better than summer.\"", frame:"I see your point, but ______.", ex:"I see your point, but I think summer is more fun.", must:/\b(see|understand|true|afraid|sure)\b.*\bbut\b|\bi'm afraid\b|\bnot sure\b/i, ok:"Acknowledge + but.", tip:"<b>I see your point, but ...</b>"},
      {p:"Politely complain that your food hasn't arrived.", frame:"Excuse me, ______ hasn't arrived yet. Could you check, please?", ex:"Excuse me, my food hasn't arrived yet. Could you check, please?", must:/\bexcuse me\b|\bcould you\b|\bhasn't\b|\bhaven't\b/i, ok:"Facts + a polite request.", tip:"<b>Excuse me, ... hasn't arrived yet. Could you check, please?</b>"},
      {p:"Tell me one thing that happened to you recently, in two sentences.", frame:"I was ______ when ______. Then ______.", ex:"I was walking to work when I met an old friend. Then we had tea together.", must:/\b(was|were|went|had|saw|ate|met|took|got|\w+ed)\b/i, ok:"Past events in order.", tip:"Use the <b>past</b> and a sequence word: <b>I was ... when ...</b>"},
      {p:"Start a phone call to a company about a job advertisement.", frame:"Hello, this is ______ speaking. I'm calling about ______.", ex:"Hello, this is Raj speaking. I'm calling about your job advertisement.", must:/\b(this is|speaking|could i speak|i'm calling|i am calling)\b/i, ok:"A confident opening.", tip:"<b>Hello, this is ... speaking. I'm calling about ...</b>"}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"My good name is Raj.", good:"My name is Raj. / I'm Raj.", fix:"No \"good name\" in English introductions."},
      {bad:"Give me water.", good:"Could I have some water, please?", fix:"Requests need <i>could</i> + <i>please</i> (Module 8)."},
      {bad:"You are wrong.", good:"I see your point, but I think…", fix:"Acknowledge first, then <b>but</b>."},
      {bad:"Who are you? (on the phone)", good:"Who's calling, please? / May I ask who's calling?", fix:"On the phone, use the polite forms."},
      {bad:"I was walk home when it rained.", good:"I was walking home when it started to rain.", fix:"<b>was + -ing</b> for the background, <b>past simple</b> for the event."}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: The Real World", pass:0.8,
     intro:"Six real situations in one test. This also revisits earlier modules. You need 8 of 10.",
     qs:[
      {k:"mcq", ref:"Introduce yourself", q:"Which is the most natural way to start?", o:["Hello. My good name is Raj.","Hi, I'm Raj. Nice to meet you.","Hello, I Raj."], a:1, w:["\"Good name\" isn't used.","Yes: simple and friendly.","The glue is missing."]},
      {k:"mcq", ref:"Ask for help", q:"You need the time. What do you say?", o:["What is time?","Time?","Excuse me, could you tell me the time, please?"], a:2, w:["Not natural.","Too short and abrupt.","Yes: polite and complete."]},
      {k:"mcq", ref:"Ask for help", q:"The speaker is too fast. What do you say?", o:["Slow!","Sorry, could you speak a bit more slowly, please?","I can't understand you."], a:1, w:["Rude.","Yes: polite and clear.","Sounds like blaming."]},
      {k:"mcq", ref:"Disagree politely", q:"Which is the most polite disagreement?", o:["No way.","I see your point, but I'm not sure I agree.","That's wrong."], a:1, w:["Rude.","Yes: acknowledge + but.","Blunt."]},
      {k:"mcq", ref:"Complain", q:"Your parcel hasn't arrived. The best way to start:", o:["Excuse me, my parcel hasn't arrived yet. Could you check, please?","Where is my parcel?!","Your delivery is useless."], a:0, w:["Yes: facts + polite request.","Aggressive.","An attack."]},
      {k:"mcq", ref:"Tell a story", q:"I ___ walking when I saw a dog.", o:["was","were","did"], a:0, w:["Yes: <b>was + -ing</b> background.","<i>Were</i> is for you/we/they.","<i>Did</i> doesn't fit."]},
      {k:"mcq", ref:"Phone calls", q:"You call a company and need Mrs Gupta. You say:", o:["Give me Mrs Gupta.","Could I speak to Mrs Gupta, please?","Who is Mrs Gupta?"], a:1, w:["Rude.","Yes: polite and standard.","Doesn't ask for her."]},
      {k:"order", ref:"Phone calls", q:"Translate to English.", hi:"क्या मैं संदेश छोड़ सकता हूँ?", words:["Can","I","leave","a","message"], a:"Can I leave a message?", w:"A standard phone phrase."},
      {k:"type", ref:"Ask for help", q:"Translate to English.", hi:"क्या आप मुझे बता सकते हैं कि स्टेशन कहाँ है?", a:["Could you tell me where the station is?","Can you tell me where the station is?"], w:"A polite indirect question: normal order after <i>tell me</i> (Module 7)."},
      {k:"mcq", ref:"Module 13: conditionals", q:"If I ___ you, I would apologize.", o:["am","were","will be"], a:1, w:["Not natural.","Yes: <b>If I were you</b>.","No <i>will</i> after <i>if</i>."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Meet people and keep the chat alive: <i>Hi, I'm Raj. I'm from Pune. What about you?</i>",
          "Ask for help, disagree and complain politely: <i>Could you tell me how to…? I see your point, but… My order hasn't arrived yet.</i>",
          "Tell a story and make phone calls: <i>I was walking home when… Hello, this is Raj speaking. Could I speak to…?</i>"],
     teaser:"Next: <b>Think in English.</b> The final module: how to keep improving on your own, for life."}
  ]
});
