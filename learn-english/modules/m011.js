registerModule({
  id: 11,
  title: "Connectors (because, but, so, if, although)",
  sub: "join ideas into long, smooth sentences",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 11 · Start here", title:"Short sentences sound like a robot",
     html:`<p>"I was tired. I went to the party. I was happy." Every sentence is correct, but listen to it. It sounds like a robot reading a list.</p>
           <p>Real speakers <b>join</b> ideas with small words: <i>and, but, so, because, although, if</i>. Each one tells the listener how two ideas are connected. Pick the right one and you instantly sound smoother.</p>`},
    {k:"mcq", q:"I was very tired, ___ I went to the party.",
     o:["so","because","if","but"], a:3,
     w:["<i>So</i> shows a result. Being tired doesn't cause going to a party.","<i>Because</i> shows a reason, but the logic is the wrong way round here.","<i>If</i> makes it a condition. It already happened.","Yes! <b>but</b> joins two ideas that don't go together (tired vs. party)."]},
    {k:"card", ref:"and / but / or / so", tag:"The idea · 1 of 5", title:"The four joiners: and, but, or, so",
     html:`<table>
             <tr><th>word</th><th>joins ideas that…</th><th>example</th></tr>
             <tr><td><b>and</b></td><td>add</td><td>I like tea <b>and</b> I like coffee.</td></tr>
             <tr><td><b>but</b></td><td>contrast</td><td>I like tea, <b>but</b> I don't like coffee.</td></tr>
             <tr><td><b>or</b></td><td>give a choice</td><td>Do you want tea <b>or</b> coffee?</td></tr>
             <tr><td><b>so</b></td><td>show a result</td><td>I was tired, <b>so</b> I went to bed.</td></tr>
           </table>
           <p><b>Commas:</b> when you join two complete sentences with <i>but / so / or</i>, put a comma before it: <i>I was tired, so I went to bed.</i> With <i>and</i> and short pieces, no comma is needed.</p>
           <p class="sub">Short answers use them too: "Tea or coffee?" · "Tired but happy."</p>`},
    {k:"card", ref:"because / so", tag:"The idea · 2 of 5", title:"because (reason) and so (result)",
     html:`<p>The same fact, told in two directions:</p>
           <div class="right">It was raining, <b>so</b> we stayed at home. <span class="sub">(cause first, then result)</span></div>
           <div class="right">We stayed at home <b>because</b> it was raining. <span class="sub">(result first, then reason)</span></div>
           <div class="right"><b>Because</b> it was raining, we stayed at home.</div>
           <p><b>Use one, not both.</b></p>
           <div class="wrong">Because it was raining, so we stayed at home.</div>
           <p><b>because + a sentence</b> (WHO + verb). <b>because of + a noun</b>: <i>We stayed home because of the rain.</i></p>
           <p>Answering <i>Why?</i> you can start with <b>Because</b>: <i>Why are you late? — Because I missed the bus.</i></p>`},
    {k:"order", q:"Translate to English.", hi:"मैं थका हुआ था, इसलिए मैं जल्दी सो गया।", words:["I","was","tired","so","I","went","to","bed","early"], a:"I was tired, so I went to bed early.",
     w:"Cause first → <b>so</b> → result. A comma before <i>so</i>."},
    {k:"card", ref:"although", tag:"The idea · 3 of 5", title:"although: a surprise",
     html:`<p><b>although</b> (or <b>even though</b>, stronger) says: <i>this happened, and you might expect the opposite.</i></p>
           <div class="right"><b>Although</b> it was raining, we went out.</div>
           <div class="right">We went out <b>although</b> it was raining.</div>
           <p><b>Don't use although and but together.</b> One joiner is enough:</p>
           <div class="wrong">Although it was raining, but we went out.</div>
           <p><b>although + a sentence.</b> With a noun use <b>despite</b> or <b>in spite of</b>: <i>Despite the rain, we went out.</i></p>
           <p class="sub"><b>however</b> starts a new sentence: <i>It was raining. However, we went out.</i> (It means "but".)</p>`},
    {k:"card", ref:"if / unless", tag:"The idea · 4 of 5", title:"if and unless: conditions",
     html:`<p><b>if</b> = maybe it will happen. <b>unless</b> = if not.</p>
           <div class="right"><b>If</b> it rains tomorrow, we'll stay at home.</div>
           <div class="right">You'll be late <b>unless</b> you hurry. <span class="sub">(= if you don't hurry)</span></div>
           <p><b>The trap from Module 6:</b> after <i>if, unless, when, before, after</i>, use the <b>simple present</b>, even though the meaning is future. <i>Will</i> goes only in the main part.</p>
           <div class="wrong">If it will rain, I will stay home. &nbsp; If I will have time, I'll help.</div>
           <div class="right">If it rains, I will stay home. &nbsp; If I have time, I'll help.</div>
           <p class="sub"><b>if</b> = maybe. <b>when</b> = sure it will happen. <i>When I get home, I'll call you.</i> (Module 13 goes deeper into if.)</p>`},
    {k:"card", ref:"Sequence words", tag:"The idea · 5 of 5", title:"Sequence words: tell things in order",
     html:`<p>For steps, stories and instructions:</p>
           <p><b>First, … &nbsp; Then / Next, … &nbsp; After that, … &nbsp; Finally, …</b></p>
           <div class="right"><b>First</b>, mix the flour and water. <b>Then</b> add salt. <b>After that</b>, knead the dough. <b>Finally</b>, cook it.</div>
           <p>Time joiners inside a sentence: <b>before, after, while, when, as soon as, until</b>.</p>
           <div class="right">Wash your hands <b>before</b> you eat. &nbsp; I'll call you <b>as soon as</b> I arrive.</div>
           <p class="sub">After before/after/when/as soon as, the verb is in the present, as with <i>if</i> (Module 6).</p>`},
    {k:"mcq", q:"It was raining, ___ we stayed at home.", o:["but","so","although"], a:1,
     w:["<i>But</i> would show a contrast.","Yes. Rain caused staying home → <b>so</b> (result).","<i>Although</i> would show a surprise."]},
    {k:"mcq", q:"We stayed at home ___ it was raining.", o:["because","so","but"], a:0,
     w:["Yes. The reason follows <b>because</b>.","<i>So</i> goes before the result.","<i>But</i> shows contrast."]},
    {k:"mcq", q:"___ it was raining, we went out.", o:["Because","Although","So"], a:1,
     w:["<i>Because</i> would give a reason for going out. But the rain is a reason not to go.","Yes. A surprise → <b>Although</b>.","<i>So</i> doesn't start a sentence like this."]},
    {k:"mcq", q:"Which is correct?", o:["Although it was raining, but we went out.","Although it was raining, we went out.","Although it was raining we but went out."], a:1,
     w:["Don't use <i>although</i> and <i>but</i> together.","Yes. One joiner is enough.","Wrong word order."]},
    {k:"mcq", q:"I'll call you if I ___ time.", o:["will have","have","had"], a:1,
     w:["No <i>will</i> after <i>if</i>.","Yes. After <b>if</b>, the simple present.","<i>Had</i> changes the meaning (Module 13)."]},
    {k:"type", q:"You'll be late ___ you hurry. <span class='sub'>(= if you don't hurry)</span>", a:["unless"], w:"<b>unless</b> = if not."},
    {k:"order", q:"Translate to English.", hi:"मैं देर से पहुँचा क्योंकि बस छूट गई थी।", words:["I","arrived","late","because","I","missed","the","bus"], a:"I arrived late because I missed the bus.", alt:["Because I missed the bus, I arrived late."],
     w:"<b>because</b> + a full sentence (Module 4's past)."},
    {k:"order", q:"Translate to English.", hi:"बारिश के बावजूद हम घूमने गए।", words:["We","went","out","although","it","was","raining"], a:"We went out although it was raining.", alt:["Although it was raining, we went out."],
     w:"A surprise → <b>although</b> + a sentence."},
    {k:"type", q:"Translate to English.", hi:"चाय या कॉफ़ी?", a:["Tea or coffee?"], w:"<b>or</b> offers a choice."},
    {k:"mcq", q:"I'll call you ___ I arrive.", o:["because","but","when"], a:2,
     w:["<i>Because</i> gives a reason, not a time.","<i>But</i> shows contrast.","Yes. <b>when</b> + present (Module 6 rule)."]},
    {k:"mcq", q:"Which is correct?", o:["Because I was late, so I ran.","Because I was late, I ran.","I was late because so I ran."], a:1,
     w:["<i>Because</i> and <i>so</i> together is a classic mistake. Use one.","Yes. One joiner is enough.","Wrong order."]},
    {k:"order", q:"Translate to English.", hi:"पहले आटा गूँधो, फिर उसे बेलो और आख़िर में पकाओ।", words:["First","knead","the","dough","then","roll","it","and","finally","cook","it"], a:"First knead the dough, then roll it, and finally cook it.",
     w:"<b>First, then, finally</b> keep the steps in order."},
    {k:"mcq", q:"He is rich, ___ he isn't happy.", o:["so","because","but"], a:2,
     w:["<i>So</i> shows a result.","<i>Because</i> shows a reason.","Yes. Money and unhappiness don't go together → <b>but</b>."]},
    {k:"mcq", q:"Unless you hurry, you'll be late. This means:", o:["If you hurry, you'll be late.","If you don't hurry, you'll be late.","Because you hurry, you'll be late."], a:1,
     w:["The opposite meaning.","Yes. <b>unless</b> = if not.","<i>Because</i> doesn't fit."]},
    {k:"type", q:"She was ill, ___ she didn't go to work. <span class='sub'>(a result)</span>", a:["so"], w:"A result → <b>so</b>."},
    {k:"mcq", q:"Revision from Module 10: I'll see you ___ Monday.", o:["on","in","at"], a:0,
     w:["Yes. Days → <b>on</b>.","<i>In</i> is for months and years.","<i>At</i> is for clock times."]},
    {k:"build", intro:"Your turn. Join ideas about <b>your own life</b>. Type each one and say it out loud.",
     items:[
      {p:"Give a reason for something you did.", frame:"I ______ because ______.", ex:"I stayed home because I was tired.", must:/\bbecause\b/i, ok:"<b>because</b> + a full sentence.", tip:"<b>I ... because I ...</b>"},
      {p:"Say a cause and its result.", frame:"It was ______, so ______.", ex:"It was hot, so we turned on the fan.", must:/\bso\b/i, ok:"A result → <b>so</b>.", tip:"<b>It was ..., so we ...</b>"},
      {p:"Show a contrast with but.", frame:"I like ______, but I don't like ______.", ex:"I like cricket, but I don't like football.", must:/\bbut\b/i, ok:"<b>but</b> joins opposite ideas.", tip:"<b>I like ..., but I ...</b>"},
      {p:"Use although.", frame:"Although ______, I ______.", ex:"Although I was tired, I went to the gym.", must:/\b(although|even though|though)\b/i, ok:"A surprise → <b>although</b>, with no <i>but</i>.", tip:"<b>Although + sentence, + sentence.</b>"},
      {p:"Say what you will do if the weather is bad tomorrow.", frame:"If it ______ tomorrow, I will ______.", ex:"If it rains tomorrow, I will stay at home.", must:/\bif\b/i, ok:"<b>if + present</b>, <b>will</b> in the main part.", tip:"<b>If it rains ..., I will ...</b> (no will after if)."}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"Because I was late, so I ran.", good:"Because I was late, I ran.", fix:"Use <b>because</b> or <b>so</b>, never both in one sentence."},
      {bad:"Although it was cold, but I went out.", good:"Although it was cold, I went out.", fix:"<b>although</b> and <b>but</b> don't go together."},
      {bad:"If I will have time, I'll help.", good:"If I have time, I'll help.", fix:"No <i>will</i> after <i>if / when / before / after</i>."},
      {bad:"I didn't go because of I was ill.", good:"I didn't go because I was ill. / because of my illness.", fix:"<b>because</b> + sentence; <b>because of</b> + noun."},
      {bad:"I was tired. So I went to bed. (as one idea)", good:"I was tired, so I went to bed.", fix:"Join the ideas with a comma, not a full stop, for a smoother sentence."}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: The Storyteller", pass:0.8,
     intro:"Join ideas smoothly and tell a story in order. This also revisits Modules 1 to 10. You need 8 of 10.",
     qs:[
      {k:"mcq", ref:"because / so", q:"She was hungry, ___ she ate a sandwich.", o:["because","so","although"], a:1, w:["<i>Because</i> would introduce the reason.","Yes: the result → <b>so</b>.","<i>Although</i> shows a surprise."]},
      {k:"mcq", ref:"because / so", q:"He didn't come ___ he was ill.", o:["so","but","because"], a:2, w:["<i>So</i> goes before the result.","<i>But</i> shows contrast.","Yes: a reason → <b>because</b>."]},
      {k:"mcq", ref:"although", q:"___ he was ill, he came to work.", o:["Because","Although","So"], a:1, w:["<i>Because</i> would mean being ill is the reason for coming.","Yes: a surprise → <b>Although</b>.","<i>So</i> doesn't start a sentence like this."]},
      {k:"mcq", ref:"although", q:"Which is correct?", o:["Although he is rich, but he is unhappy.","Although he is rich, he is unhappy.","Although he is rich he but is unhappy."], a:1, w:["Don't use <i>although</i> and <i>but</i> together.","Yes: one joiner.","Wrong word order."]},
      {k:"mcq", ref:"if / unless", q:"I won't go out ___ it stops raining.", o:["unless","because","although"], a:0, w:["Yes: <b>unless</b> = if it doesn't stop.","<i>Because</i> gives a reason.","<i>Although</i> shows a surprise."]},
      {k:"type", ref:"if / unless", q:"If it ___ tomorrow, I'll stay home. <span class='sub'>(rain)</span>", a:["rains"], w:"After <b>if</b>, the simple present: <b>rains</b>."},
      {k:"order", ref:"and / but / or / so", q:"Translate to English.", hi:"मुझे चाय पसंद है, लेकिन मुझे कॉफ़ी पसंद नहीं है।", words:["I","like","tea","but","I","don't","like","coffee"], a:"I like tea, but I don't like coffee.", w:"<b>but</b> joins a contrast."},
      {k:"type", ref:"because / so", q:"Translate to English.", hi:"वह बीमार थी, इसलिए वह दफ़्तर नहीं गई।", a:["She was ill, so she didn't go to work.","She was sick, so she didn't go to work."], w:"Cause → <b>so</b> → result."},
      {k:"mcq", ref:"Sequence words", q:"___, mix the flour and water. Then add salt.", o:["First","Finally","Although"], a:0, w:["Yes: the first step starts with <b>First</b>.","<i>Finally</i> is for the last step.","<i>Although</i> doesn't fit."]},
      {k:"mcq", ref:"Module 10: prepositions", q:"I'll meet you ___ five o'clock.", o:["on","in","at"], a:2, w:["<i>On</i> is for days.","<i>In</i> is for longer periods.","Yes: a clock time → <b>at</b>."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Give reasons and results: <i>I was tired, so I left. I left because I was tired.</i>",
          "Show contrast and surprise: <i>I like tea, but not coffee. Although it rained, we went out.</i>",
          "Set conditions and tell things in order: <i>If it rains, I'll stay home. First…, then…, finally…</i>"],
     teaser:"Next: <b>Comparing and opinions.</b> Bigger, the best, as tall as, and how to say \"I think…\" and disagree politely."}
  ]
});
