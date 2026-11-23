registerModule({
  id: 8,
  title: "Modals (can, should, must, would)",
  sub: "ability, advice, rules and politeness",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 8 · Start here", title:"The day-off request",
     html:`<p>You need tomorrow off. Your boss is in a hurry. Same request, four ways to say it. Some of them are fine for friends, but a bit risky with a boss.</p>
           <p>The difference lives in a tiny group of words called <b>modal verbs</b>. Let's see if your ear can spot the polite one.</p>`},
    {k:"mcq", q:"You ask your boss for tomorrow off. Which sounds best?",
     o:["Give me tomorrow off.","I take tomorrow off.","You must give me tomorrow off.","Could I possibly take tomorrow off?"], a:3,
     w:["That's an order, not a request.","<i>I take</i> is a habit form (Module 2), not a request.","<i>Must</i> sounds like you are in charge.","Yes! <b>Could I possibly…?</b> is soft, polite and clear."]},
    {k:"card", ref:"What modals are", tag:"The idea · 1 of 5", title:"Modals: helpers that add a feeling",
     html:`<p>A modal verb sits in front of the main verb and adds a <b>feeling</b>: ability, permission, advice, obligation, possibility or politeness.</p>
           <p><b>can · could · should · must · would · may · might</b> (and <b>will</b> from Module 6).</p>
           <div class="frame"><span class="who">WHO</span><span class="glue">modal</span><span class="rest">plain verb</span></div>
           <p><b>Four rules, same as <i>will</i>:</b></p>
           <ul><li><b>Same form for every WHO.</b> <i>She can swim.</i> (no S)</li>
           <li><b>Plain verb after.</b> No <i>to</i>, no -ing. <i>I can swim.</i> not <i>I can to swim</i>.</li>
           <li><b>No:</b> add <b>not</b>: <i>can't, couldn't, shouldn't, mustn't, wouldn't</i>.</li>
           <li><b>Question:</b> the modal jumps first: <i>Can you swim?</i> No <i>do/does</i>.</li></ul>
           <p>Short answers: <b>Yes, I can. &nbsp; No, she can't.</b></p>
           <div class="wrong">She cans swim. &nbsp; I can to swim. &nbsp; Do you can swim?</div>`},
    {k:"order", q:"Build it.", words:["She","can","speak","three","languages"], a:"She can speak three languages.",
     w:"WHO + <b>can</b> + plain verb. No S on <i>speak</i>."},
    {k:"card", ref:"can / could", tag:"The idea · 2 of 5", title:"can and could",
     html:`<table>
             <tr><th>job</th><th>can / could</th><th>example</th></tr>
             <tr><td>ability</td><td><b>can</b></td><td>I can cook. She can drive.</td></tr>
             <tr><td>ability in the past</td><td><b>could</b></td><td>When I was five, I could swim.</td></tr>
             <tr><td>permission</td><td><b>can / could / may</b></td><td>Can I sit here? Could I borrow your pen?</td></tr>
             <tr><td>request</td><td><b>can / could</b></td><td>Could you help me, please?</td></tr>
             <tr><td>not possible / not allowed</td><td><b>can't</b></td><td>You can't park here.</td></tr>
           </table>
           <p><b>could</b> is softer and more polite than <b>can</b>. Use it with strangers, bosses, and in requests.</p>
           <p class="sub">For other tenses use <b>be able to</b>: <i>I will be able to help tomorrow. I haven't been able to call him.</i></p>`},
    {k:"card", ref:"should / must / have to", tag:"The idea · 3 of 5", title:"should, must, have to: advice or rule?",
     html:`<table>
             <tr><th>word</th><th>feeling</th><th>example</th></tr>
             <tr><td><b>should</b></td><td>advice, a good idea</td><td>You should rest. You shouldn't skip breakfast.</td></tr>
             <tr><td><b>must</b></td><td>strong, personal or serious rule</td><td>You must wear a seat belt. I must call my mother.</td></tr>
             <tr><td><b>have to / has to</b></td><td>obligation from outside (a rule, a boss, a law)</td><td>I have to wear a uniform. She has to work on Sundays.</td></tr>
           </table>
           <p><b>Have to</b> works like a normal verb: <i>Do you have to…? She doesn't have to… I had to…</i> (past).</p>
           <h3>The big trap: the two negatives</h3>
           <div class="right"><b>mustn't</b> = forbidden. <i>You mustn't smoke here.</i></div>
           <div class="right"><b>don't have to</b> = not necessary, your choice. <i>You don't have to come tomorrow.</i></div>
           <p class="sub">Also: <b>must</b> can mean "I'm sure": <i>He's been working all day. He must be tired.</i></p>`},
    {k:"card", ref:"would / may / might", tag:"The idea · 4 of 5", title:"would, may, might",
     html:`<p><b>would</b> makes things polite and gentle: <i>I would like a coffee. = I'd like a coffee.</i> Offers: <i>Would you like some tea?</i></p>
           <p><b>may</b> = formal permission (<i>May I come in?</i>) or possibility. <b>might</b> = a weaker possibility.</p>
           <p>How sure are you? A ladder from certain to unlikely:</p>
           <table>
             <tr><td><b>will</b></td><td>It will rain. (sure)</td></tr>
             <tr><td><b>will probably</b></td><td>It will probably rain.</td></tr>
             <tr><td><b>may</b></td><td>It may rain. (50/50)</td></tr>
             <tr><td><b>might</b></td><td>It might rain. (not very likely)</td></tr>
             <tr><td><b>won't</b></td><td>It won't rain. (sure not)</td></tr>
           </table>
           <p class="sub">Speaking: <i>I'd like…</i> is better than <i>I want…</i> when ordering food or asking for something.</p>`},
    {k:"card", ref:"The polite ladder", tag:"The idea · 5 of 5", title:"The polite ladder",
     html:`<p>The same request, from blunt to very polite. Choose the step that fits the person:</p>
           <table>
             <tr><td>1</td><td>Give me water.</td><td class="sub">friends only (or an order)</td></tr>
             <tr><td>2</td><td><b>Can</b> you give me water?</td><td class="sub">friends, family</td></tr>
             <tr><td>3</td><td><b>Could</b> you give me some water, <b>please</b>?</td><td class="sub">anyone, safe choice</td></tr>
             <tr><td>4</td><td><b>Would you mind</b> giving me some water?</td><td class="sub">very polite</td></tr>
             <tr><td>5</td><td>I was wondering <b>if you could</b> give me some water.</td><td class="sub">formal, a big favour</td></tr>
           </table>
           <p><b>Politely refusing:</b> <i>I'm afraid I can't.</i> / <i>Sorry, I'm not able to.</i> And <b>please</b> never hurts.</p>
           <p class="sub">When in doubt, use <b>Could you … , please?</b> It works with everyone.</p>`},
    {k:"mcq", q:"She ___ speak three languages.", o:["can","cans","can to"], a:0,
     w:["Yes. <b>can</b> never changes and is followed by a plain verb.","<i>Can</i> never gets an S.","No <i>to</i> after a modal."]},
    {k:"mcq", q:"___ I borrow your pen?", o:["Do","Could","Am"], a:1,
     w:["<i>Do</i> isn't used with modals.","Yes. <b>Could I…?</b> A polite request.","<i>Am</i> is Module 1's glue, not a modal."]},
    {k:"type", q:"You should ___ more water. <span class='sub'>(drink)</span>", a:["drink"], w:"After <b>should</b>, a plain verb: drink."},
    {k:"mcq", q:"You ___ park here. It's forbidden.", o:["don't have to","mustn't","can"], a:1,
     w:["<i>Don't have to</i> means it's not necessary, not forbidden.","Yes. <b>mustn't</b> = forbidden.","<i>Can</i> means allowed, the opposite."]},
    {k:"mcq", q:"Tomorrow is Sunday. You ___ come to the office.", o:["mustn't","don't have to","can't"], a:1,
     w:["<i>Mustn't</i> would mean you're forbidden to come.","Yes. <b>don't have to</b> = not necessary.","<i>Can't</i> would mean you are not able/allowed."]},
    {k:"order", q:"Translate to English.", hi:"क्या मैं यहाँ बैठ सकता हूँ?", words:["Can","I","sit","here"], a:"Can I sit here?",
     w:"Permission → <b>Can I…?</b> The modal jumps first."},
    {k:"order", q:"Translate to English.", hi:"तुम्हें डॉक्टर को दिखाना चाहिए।", words:["You","should","see","a","doctor"], a:"You should see a doctor.",
     w:"Advice → <b>should</b> + plain verb."},
    {k:"mcq", q:"Which is correct?", o:["She can to swim.","She can swim.","She cans swim."], a:1,
     w:["No <i>to</i> after a modal.","Yes. <b>can</b> + plain verb.","<i>Can</i> never takes an S."]},
    {k:"order", q:"Translate to English.", hi:"मुझे कल जल्दी उठना पड़ेगा।", words:["I","will","have","to","get","up","early","tomorrow"], a:"I will have to get up early tomorrow.", alt:["Tomorrow I will have to get up early."],
     w:"Obligation in the future: <b>will have to</b> (Module 6 + Module 8 together)."},
    {k:"mcq", q:"It's cloudy. It ___ rain later, but I'm not sure.", o:["must","might","has to"], a:1,
     w:["<i>Must</i> means you're sure.","Yes. <b>might</b> = a weak possibility.","<i>Has to</i> means obligation."]},
    {k:"type", q:"Translate to English.", hi:"मैं एक कप चाय लेना चाहूँगा।", a:["I would like a cup of tea.","I'd like a cup of tea."], w:"<b>I would like…</b> / <b>I'd like…</b> is the polite way to ask for something."},
    {k:"mcq", q:"Which is the most polite?", o:["Give me your pen.","Can you give me your pen?","Could you possibly lend me your pen, please?"], a:2,
     w:["That's blunt.","Fine with friends, but not the most polite.","Yes. <b>Could you possibly… please?</b> is the top of the ladder."]},
    {k:"mcq", q:"He's been working all day. He ___ be tired.", o:["can","must","would"], a:1,
     w:["<i>Can</i> doesn't show you're sure.","Yes. <b>must be</b> = I'm sure from the evidence.","<i>Would</i> isn't used this way."]},
    {k:"order", q:"Translate to English.", hi:"आप यहाँ सिगरेट नहीं पी सकते।", words:["You","can't","smoke","here"], a:"You can't smoke here.",
     w:"Not allowed → <b>can't</b> + plain verb."},
    {k:"mcq", q:"When I was a child, I ___ run very fast.", o:["can","could","must"], a:1,
     w:["<i>Can</i> is for the present.","Yes. Past ability → <b>could</b>.","<i>Must</i> is about obligation."]},
    {k:"type", q:"We ___ to wear a helmet. It's the law. <span class='sub'>(have)</span>", a:["have"], w:"<b>have to</b> = a rule from outside."},
    {k:"mcq", q:"Revision from Module 7: ___ you tell me the time, please?", o:["Could","Do","Are"], a:0,
     w:["Yes. A modal + <b>please</b> is polite: Could you…?","<i>Do you tell</i> is a habit question.","<i>Are you tell</i> doesn't work."]},
    {k:"build", intro:"Your turn. Real sentences about <b>you</b>. Type each one and say it out loud.",
     items:[
      {p:"Say something you can do well.", frame:"I can ______.", ex:"I can cook really good biryani.", must:/\b(i can|i'm able to|i am able to)\b/i, ok:"<b>can</b> + plain verb.", tip:"<b>I can</b> + plain verb: I can swim / cook / drive."},
      {p:"Give advice to a tired friend.", frame:"You should ______.", ex:"You should go to bed early tonight.", must:/\bshould\b/i, ok:"Advice → <b>should</b>.", tip:"<b>You should</b> + plain verb."},
      {p:"Say one rule at your work or school.", frame:"We have to ______. / We mustn't ______.", ex:"We have to arrive before nine.", must:/\b(have to|has to|must|mustn't|can't)\b/i, ok:"A rule: <b>have to / mustn't</b>.", tip:"<b>We have to ...</b> or <b>We mustn't ...</b>"},
      {p:"Ask for something politely, with Could.", frame:"Could you ______, please?", ex:"Could you open the window, please?", must:/^\s*(could|would|can)\b/i, ok:"A polite request. Perfect.", tip:"<b>Could you ... , please?</b>"},
      {p:"Say something that might happen tomorrow.", frame:"It might ______. / I might ______.", ex:"I might visit my cousin tomorrow.", must:/\b(might|may)\b/i, ok:"A possibility → <b>might</b>.", tip:"<b>might</b> + plain verb."}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"I can to swim. / She cans swim.", good:"I can swim. / She can swim.", fix:"After a modal: a plain verb. No <i>to</i>, no S."},
      {bad:"Do you can swim?", good:"Can you swim?", fix:"The modal jumps first. No <i>do/does</i>."},
      {bad:"You mustn't come tomorrow. (not necessary)", good:"You don't have to come tomorrow.", fix:"<i>mustn't</i> = forbidden. <i>don't have to</i> = not necessary."},
      {bad:"I must to go now.", good:"I must go now. / I have to go now.", fix:"<i>Must</i> is a modal: no <i>to</i>. <i>Have to</i> keeps its <i>to</i>."},
      {bad:"Give me water. (to a stranger)", good:"Could you give me some water, please?", fix:"Soften requests with <i>could</i> + <i>please</i>."}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: The Polite Traveller", pass:0.8,
     intro:"You are travelling and need to ask, advise and follow rules, politely. This also revisits Modules 1 to 7. You need 8 of 10.",
     qs:[
      {k:"mcq", ref:"What modals are", q:"Which is correct?", o:["She cans swim.","She can swim.","She can swims."], a:1, w:["<i>Can</i> never takes an S.","Yes: <b>can</b> + plain verb.","The verb stays plain."]},
      {k:"mcq", ref:"can / could", q:"___ you help me, please?", o:["Could","Do","Does"], a:0, w:["Yes: a polite request → <b>Could</b>.","<i>Do</i> isn't used with <i>help me, please?</i> like this.","<i>Does</i> needs he/she/it."]},
      {k:"mcq", ref:"should / must / have to", q:"You ___ smoke here. It's against the rules.", o:["mustn't","don't have to","can"], a:0, w:["Yes: <b>mustn't</b> = forbidden.","That means it isn't necessary.","That means it is allowed."]},
      {k:"mcq", ref:"should / must / have to", q:"It's a holiday. We ___ go to work.", o:["mustn't","don't have to","must"], a:1, w:["That would mean we're forbidden.","Yes: <b>don't have to</b> = not necessary.","That means we are required."]},
      {k:"type", ref:"would / may / might", q:"I ___ like a coffee, please. <span class='sub'>(one word)</span>", a:["would","'d"], w:"<b>I would like</b> (<b>I'd like</b>) is polite."},
      {k:"mcq", ref:"would / may / might", q:"I'm not sure, but it ___ rain tonight.", o:["must","might","has to"], a:1, w:["<i>Must</i> means you're sure.","Yes: <b>might</b> = weak possibility.","<i>Has to</i> is an obligation."]},
      {k:"order", ref:"can / could", q:"Translate to English.", hi:"क्या मैं तुम्हारा फ़ोन इस्तेमाल कर सकता हूँ?", words:["Can","I","use","your","phone"], a:"Can I use your phone?", w:"Permission → <b>Can I…?</b>"},
      {k:"type", ref:"should / must / have to", q:"Translate to English.", hi:"तुम्हें ज़्यादा पानी पीना चाहिए।", a:["You should drink more water."], w:"Advice → <b>should</b> + plain verb."},
      {k:"mcq", ref:"The polite ladder", q:"Which is the most polite?", o:["Give me the menu.","Can you give me the menu?","Could I possibly see the menu, please?"], a:2, w:["Blunt.","Fine with friends.","Yes: top of the polite ladder."]},
      {k:"mcq", ref:"The polite ladder", q:"Revision from Module 7: which is correct?", o:["Could you tell me where he lives?","Could you tell me where does he live?","Could you tell me where he does live?"], a:0, w:["Yes: polite question + normal order.","Don't flip after <i>Could you tell me</i>.","Two helpers."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Say what you can and could do, ask permission: <i>I can cook. Can I sit here? Could I borrow your pen?</i>",
          "Give advice and talk about rules: <i>You should rest. We have to wear helmets. You mustn't park here.</i>",
          "Be polite: <i>I'd like a coffee. Could you help me, please? It might rain.</i>"],
     teaser:"Next: <b>Nouns and articles.</b> A, an, the, or nothing: the small words that make your English sound natural."}
  ]
});
