registerModule({
  id: 13,
  title: "Conditionals",
  sub: "real and imaginary if",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 13 · Start here", title:"Dreaming in grammar",
     html:`<p>"If I win the lottery…" Everyone says it. But there are <b>three different ifs</b> hiding here: something that might really happen, something imaginary, and something you wish you had done differently.</p>
           <p>English changes the <i>tense</i> to show how real an idea is. The more imaginary, the further back the tense goes. Let's try the imaginary one first.</p>`},
    {k:"mcq", q:"If I had a million rupees, I ___ travel the world.",
     o:["will","am going to","can be","would"], a:3,
     w:["<i>Will</i> is for real possibilities. A million rupees isn't real right now.","<i>Am going to</i> is a plan, not an imaginary result.","Doesn't fit the grammar.","Yes! <b>If + past, would + verb</b> = an imaginary situation."]},
    {k:"card", ref:"Zero and first", tag:"The idea · 1 of 5", title:"Zero and first: real situations",
     html:`<p><b>Zero:</b> facts that are always true. <b>if + present, present.</b></p>
           <div class="right">If you heat ice, it <b>melts</b>. &nbsp; If I'm tired, I <b>go</b> to bed early.</div>
           <p><b>First:</b> a real possibility in the future. <b>if + present, will + plain verb.</b></p>
           <div class="right">If it <b>rains</b> tomorrow, we <b>will stay</b> at home.</div>
           <p>The trap you already know (Modules 6 and 11): <b>no will after if</b>.</p>
           <div class="wrong">If it will rain, we will stay home.</div>
           <p>You can swap the order, with no comma: <i>We will stay home if it rains.</i> The main part can also use modals: <i>If you're tired, you should rest. If you hurry, you might catch it.</i></p>
           <p class="sub"><b>unless</b> = if not (Module 11): <i>Unless you hurry, you'll miss it.</i></p>`},
    {k:"order", q:"Translate to English.", hi:"अगर तुम जल्दी करो तो हम ट्रेन पकड़ लेंगे।", words:["If","you","hurry","we","will","catch","the","train"], a:"If you hurry, we will catch the train.", alt:["We will catch the train if you hurry."],
     w:"<b>if + present</b>, <b>will + plain verb</b>."},
    {k:"card", ref:"Second conditional", tag:"The idea · 2 of 5", title:"Second: imaginary now",
     html:`<div class="frame"><span class="rest">If</span><span class="who">WHO</span><span class="glue">past simple,</span><span class="who">WHO</span><span class="glue">would</span><span class="rest">plain verb</span></div>
           <div class="right">If I <b>had</b> time, I <b>would help</b> you. <span class="sub">(but I don't have time)</span></div>
           <div class="right">If she <b>won</b> the lottery, she <b>would buy</b> a house. <span class="sub">(unlikely)</span></div>
           <p><b>The past tense here is not about the past.</b> It is "distance from reality". The situation isn't real, so the verb steps back.</p>
           <p><b>With be, use <i>were</i> for every WHO</b> (formal, and best for exams): <i>If I <b>were</b> rich… If he <b>were</b> here…</i> In casual speech <i>was</i> is also heard.</p>
           <p><b>Advice:</b> <i>If I were you, I would take the job.</i></p>
           <p>Questions: <i>What would you do if you won the lottery?</i> Short: <i>I'd travel.</i> (<i>'d</i> = would here)</p>
           <div class="wrong">If I would have time, I would help. &nbsp; If I am you, I will go.</div>`},
    {k:"card", ref:"Third conditional", tag:"The idea · 3 of 5", title:"Third: imaginary past (regrets)",
     html:`<div class="frame"><span class="rest">If</span><span class="who">WHO</span><span class="glue">had + participle,</span><span class="who">WHO</span><span class="glue">would have</span><span class="rest">participle</span></div>
           <div class="right">If I <b>had studied</b>, I <b>would have passed</b>. <span class="sub">(I didn't study, I didn't pass)</span></div>
           <div class="right">If she <b>hadn't been</b> late, she <b>wouldn't have missed</b> the train.</div>
           <p>Both parts use <b>Module 5's participle</b> (studied, been, missed). This is the grammar of <i>regret</i> and <i>what might have been</i>.</p>
           <p class="sub"><b>'d</b> is a tricky shortcut: <i>I'd go</i> = I would go; <i>I'd gone</i> = I had gone. The next word tells you which.</p>
           <div class="wrong">If I studied harder, I would have passed. &nbsp; If I had known, I would told you.</div>`},
    {k:"card", ref:"Which one?", tag:"The idea · 4 of 5", title:"Which if? Ask: how real is it?",
     html:`<table>
             <tr><th>how real</th><th>if part</th><th>main part</th><th>example</th></tr>
             <tr><td>fact</td><td>present</td><td>present</td><td>If you heat ice, it melts.</td></tr>
             <tr><td>real possibility</td><td>present</td><td>will</td><td>If it rains, I'll stay home.</td></tr>
             <tr><td>imaginary now / unlikely</td><td>past</td><td>would</td><td>If I had time, I'd help.</td></tr>
             <tr><td>imaginary past (too late)</td><td>had + participle</td><td>would have + participle</td><td>If I'd studied, I'd have passed.</td></tr>
           </table>
           <p><b>One step further from reality = one step back in tense.</b></p>
           <p class="sub">Test: <i>Could this really still happen?</i> If yes → first. If it's imaginary today → second. If it's about the past, already finished → third.</p>`},
    {k:"card", ref:"I wish", tag:"The idea · 5 of 5", title:"I wish: the same idea, as a feeling",
     html:`<p><b>wish</b> follows the same step-back logic:</p>
           <div class="right">I wish I <b>had</b> a car. <span class="sub">(I don't have one now)</span></div>
           <div class="right">I wish I <b>were</b> taller. &nbsp; I wish I <b>could</b> swim.</div>
           <div class="right">I wish I <b>had told</b> him the truth. <span class="sub">(regret about the past)</span></div>
           <div class="right">I wish he <b>would</b> stop talking. <span class="sub">(annoyance)</span></div>
           <p class="sub">After <i>wish</i>, never <i>I wish I can…</i>. Use <i>could</i>. <b>If only</b> is the stronger version: <i>If only I had a car!</i></p>`},
    {k:"mcq", q:"If it rains, I ___ stay home.", o:["would","will","am"], a:1,
     w:["<i>Would</i> is for imaginary situations.","Yes. A real possibility → <b>will</b>.","<i>Am</i> doesn't fit here."]},
    {k:"mcq", q:"If I ___ more time, I would help you.", o:["have","had","will have"], a:1,
     w:["<i>Have</i> + <i>would</i> mixes two types.","Yes. Second conditional → <b>if + past</b>.","No <i>will</i> after <i>if</i>."]},
    {k:"mcq", q:"If I ___ you, I would apologize.", o:["am","were","will be"], a:1,
     w:["<i>If I am you</i> isn't natural.","Yes. <b>If I were you</b>: the classic advice phrase.","No <i>will</i> after <i>if</i>."]},
    {k:"mcq", q:"If she had studied, she ___ passed.", o:["would have","would","will have"], a:0,
     w:["Yes. Third conditional → <b>would have + participle</b>.","This needs <i>have + participle</i> for the past.","<i>Will</i> doesn't fit a past regret."]},
    {k:"type", q:"If you heat ice, it ___. <span class='sub'>(melt)</span>", a:["melts"], w:"A fact: <b>present + present</b>. <i>It</i> takes an S."},
    {k:"order", q:"Translate to English.", hi:"अगर मेरे पास समय होता तो मैं तुम्हारी मदद करता।", words:["If","I","had","time","I","would","help","you"], a:"If I had time, I would help you.", alt:["I would help you if I had time."],
     w:"<b>if + past</b>, <b>would + plain verb</b>."},
    {k:"order", q:"Translate to English.", hi:"अगर मैंने पढ़ाई की होती तो मैं पास हो जाता।", words:["If","I","had","studied","I","would","have","passed"], a:"If I had studied, I would have passed.", alt:["I would have passed if I had studied."],
     w:"<b>had + participle</b>, <b>would have + participle</b>."},
    {k:"mcq", q:"What would you do if you ___ the lottery?", o:["win","won","will win"], a:1,
     w:["<i>Would</i> in the question goes with a past form after <i>if</i>.","Yes. <b>would … if you won</b>.","No <i>will</i> after <i>if</i>."]},
    {k:"mcq", q:"Which is correct?", o:["If I would have time, I would help.","If I had time, I would help.","If I will have time, I would help."], a:1,
     w:["Never <i>would</i> after <i>if</i> in this pattern.","Yes. <b>if + past</b>, <b>would</b>.","No <i>will</i> after <i>if</i>."]},
    {k:"type", q:"Translate to English.", hi:"काश मेरे पास एक कार होती।", a:["I wish I had a car."], w:"<b>wish</b> + past = a present wish."},
    {k:"mcq", q:"If he hadn't been late, he ___ the train.", o:["won't miss","wouldn't miss","wouldn't have missed"], a:2,
     w:["Wrong tense for a past regret.","Needs <i>have + participle</i>.","Yes. <b>wouldn't have missed</b>."]},
    {k:"mcq", q:"I wish I ___ taller.", o:["am","were","will be"], a:1,
     w:["<i>Wish</i> steps back: not <i>am</i>.","Yes. <b>I wish I were</b>.","<i>Will be</i> doesn't fit a wish."]},
    {k:"order", q:"Translate to English.", hi:"अगर मैं तुम्हारी जगह होता तो मैं माफ़ी माँगता।", words:["If","I","were","you","I","would","apologize"], a:"If I were you, I would apologize.", alt:["I would apologize if I were you."],
     w:"The advice pattern: <b>If I were you, I would…</b>"},
    {k:"type", q:"If I were you, I ___ apologize. <span class='sub'>(one word)</span>", a:["would"], w:"Second conditional → <b>would</b>."},
    {k:"mcq", q:"Which one is about a REAL possibility?", o:["If I win the lottery, I will buy a house.","If I won the lottery, I would buy a house.","If I had won the lottery, I would have bought a house."], a:0,
     w:["Yes. <b>if + present, will</b> = still possible.","<b>Second</b> = imaginary.","<b>Third</b> = imaginary past."]},
    {k:"mcq", q:"Revision from Module 11: She was tired, ___ she went to bed early.", o:["so","but","if"], a:0,
     w:["Yes. A result → <b>so</b>.","<i>But</i> shows contrast.","<i>If</i> shows a condition."]},
    {k:"build", intro:"Your turn. Dream, plan and regret. Type each one and say it out loud.",
     items:[
      {p:"Say what you will do if the weather is bad tomorrow.", frame:"If it ______ tomorrow, I will ______.", ex:"If it rains tomorrow, I will stay home and cook.", must:/(?=.*\bif\b)(?=.*(\bwill\b|'ll))/i, ok:"<b>if + present</b>, <b>will</b>. Real possibility.", tip:"<b>If it rains ..., I will ...</b> (no will after if)."},
      {p:"Imagine you had a million rupees.", frame:"If I had a million rupees, I would ______.", ex:"If I had a million rupees, I would build a school.", must:/(?=.*\bif\b)(?=.*\b(would|'d)\b)/i, ok:"<b>if + past</b>, <b>would</b>. Imaginary.", tip:"<b>If I had ..., I would ...</b>"},
      {p:"Give advice to a friend.", frame:"If I were you, I would ______.", ex:"If I were you, I would talk to your boss.", must:/\bif i (were|was) you\b/i, ok:"The advice pattern. Natural.", tip:"<b>If I were you, I would ...</b>"},
      {p:"Say a regret from your past.", frame:"If I had ______, I would have ______.", ex:"If I had started earlier, I would have finished on time.", must:/(?=.*\bhad\b)(?=.*(would have|'d have))/i, ok:"Third conditional: a regret.", tip:"<b>If I had + participle, I would have + participle.</b>"},
      {p:"Make a wish.", frame:"I wish I ______.", ex:"I wish I could speak English fluently.", must:/\bi wish\b/i, ok:"<b>wish</b> steps back. Right.", tip:"<b>I wish I could / had / were ...</b>"}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"If it will rain, I will stay home.", good:"If it rains, I will stay home.", fix:"No <i>will</i> after <i>if</i>."},
      {bad:"If I would have time, I would help.", good:"If I had time, I would help.", fix:"No <i>would</i> after <i>if</i>. Use the past: <i>if I had</i>."},
      {bad:"If I am you, I will go.", good:"If I were you, I would go.", fix:"Advice: <b>If I were you, I would…</b>"},
      {bad:"If I studied harder, I would have passed.", good:"If I had studied harder, I would have passed.", fix:"Third conditional needs <b>had + participle</b> in the if-part."},
      {bad:"I wish I can swim.", good:"I wish I could swim.", fix:"After <i>wish</i>, step back: could, had, were."}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: The Time Machine", pass:0.8,
     intro:"Real, imaginary and regretful: switch between the three ifs. This also revisits Modules 1 to 12. You need 8 of 10.",
     qs:[
      {k:"mcq", ref:"Zero and first", q:"If you heat water to 100 degrees, it ___.", o:["boils","would boil","will boiled"], a:0, w:["Yes: a fact → present + present.","That's the imaginary pattern.","Not a correct form."]},
      {k:"mcq", ref:"Zero and first", q:"If it rains tomorrow, we ___ stay at home.", o:["would","will","had"], a:1, w:["<i>Would</i> is for imaginary situations.","Yes: a real possibility → <b>will</b>.","<i>Had</i> doesn't fit."]},
      {k:"mcq", ref:"Second conditional", q:"If I had a car, I ___ drive to work.", o:["will","would","would have"], a:1, w:["<i>Will</i> is for real possibilities.","Yes: <b>would</b> + plain verb.","<i>Would have</i> is the past version."]},
      {k:"mcq", ref:"Second conditional", q:"If I ___ you, I would take the job.", o:["am","were","will be"], a:1, w:["Not natural.","Yes: <b>If I were you</b>.","No <i>will</i> after <i>if</i>."]},
      {k:"mcq", ref:"Third conditional", q:"If I had known, I ___ told you.", o:["would","would have","will have"], a:1, w:["Needs <i>have</i> for the past.","Yes: <b>would have + participle</b>.","<i>Will</i> doesn't fit a regret."]},
      {k:"type", ref:"Third conditional", q:"If she hadn't been late, she wouldn't have ___ the train. <span class='sub'>(miss)</span>", a:["missed"], w:"Participle of miss → <b>missed</b>."},
      {k:"order", ref:"Second conditional", q:"Translate to English.", hi:"अगर मेरे पास पैसे होते तो मैं एक नया फ़ोन ख़रीदता।", words:["If","I","had","money","I","would","buy","a","new","phone"], a:"If I had money, I would buy a new phone.", alt:["I would buy a new phone if I had money."], w:"<b>if + past</b>, <b>would</b>."},
      {k:"type", ref:"I wish", q:"Translate to English.", hi:"काश मैं तैर सकता।", a:["I wish I could swim."], w:"<b>wish</b> steps back: <b>could</b>."},
      {k:"mcq", ref:"Which one?", q:"Which sentence is about an imaginary PAST?", o:["If I win, I will celebrate.","If I won, I would celebrate.","If I had won, I would have celebrated."], a:2, w:["That's a real future possibility.","That's imaginary now.","Yes: <b>had + participle</b> + <b>would have</b>."]},
      {k:"mcq", ref:"Module 12: comparing", q:"Which is correct?", o:["He is more taller than me.","He is taller than me.","He is taller that me."], a:1, w:["Never <i>more</i> + <i>-er</i>.","Yes: <b>taller than</b>.","Comparatives use <i>than</i>."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Talk about real possibilities: <i>If it rains, I'll stay home. If you hurry, we'll catch the train.</i>",
          "Dream and give advice: <i>If I had time, I would help. If I were you, I would apologize.</i>",
          "Express regrets and wishes: <i>If I had studied, I would have passed. I wish I could swim.</i>"],
     teaser:"Next: <b>Reporting what people said.</b> <i>He said he was tired. She asked where I lived. He told me to wait.</i>"}
  ]
});
