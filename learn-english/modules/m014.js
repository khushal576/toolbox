registerModule({
  id: 14,
  title: "Reporting what people said",
  sub: "he said that…, she asked if…",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 14 · Start here", title:"The messenger problem",
     html:`<p>Your friend says, <i>"I am tired."</i> An hour later you tell someone else what they said. Do you repeat the exact words? Almost never. You <b>report</b> them: <i>"He said he was tired."</i></p>
           <p>Something quietly changes between the two: the tense steps back one step. Let's see if you can feel it.</p>`},
    {k:"mcq", q:"He said, \"I am tired.\" Now you report it: He said he ___ tired.",
     o:["is","am","were","was"], a:3,
     w:["<i>Is</i> would be okay only if he is <i>still</i> tired right now. The usual report steps back.","<i>Am</i>: the speaker changes, so \"I\" becomes \"he\" and the verb must change too.","<i>Were</i> is for you/we/they.","Yes! <b>am → was</b>: one step back in time."]},
    {k:"card", ref:"say and tell", tag:"The idea · 1 of 5", title:"say or tell?",
     html:`<p>Direct speech uses quote marks. Reported speech doesn't. The little word <b>that</b> is optional.</p>
           <div class="right">"I'm busy," he said. &nbsp; → &nbsp; He <b>said</b> (that) he was busy.</div>
           <p><b>say</b> + what was said. <b>tell</b> + <b>who</b> was told:</p>
           <div class="right">He <b>told me</b> that he was busy. &nbsp; He <b>said to me</b> that he was busy.</div>
           <div class="wrong">He said me that he was busy. &nbsp; He told that he was busy.</div>
           <p class="sub">Test: if you can't say who heard it, use <i>said</i>. If you name the listener right after, use <i>told</i>.</p>`},
    {k:"card", ref:"Tenses step back", tag:"The idea · 2 of 5", title:"The tense steps back one step",
     html:`<table>
             <tr><th>said</th><th>reported</th></tr>
             <tr><td>am / is / are</td><td><b>was / were</b></td></tr>
             <tr><td>work / works (simple present)</td><td><b>worked</b></td></tr>
             <tr><td>am working (continuous)</td><td><b>was working</b></td></tr>
             <tr><td>worked (simple past)</td><td><b>had worked</b></td></tr>
             <tr><td>have worked (present perfect)</td><td><b>had worked</b></td></tr>
             <tr><td>will</td><td><b>would</b></td></tr>
             <tr><td>can / may / must</td><td><b>could / might / had to</b></td></tr>
           </table>
           <div class="right">"I live in Pune." → She said she <b>lived</b> in Pune.</div>
           <div class="right">"I will call you." → He said he <b>would</b> call me.</div>
           <div class="right">"I have finished." → She said she <b>had finished</b>.</div>
           <h3>Little words move too</h3>
           <p>I → he / she · my → his / her · <b>today → that day</b> · <b>tomorrow → the next day</b> · <b>yesterday → the day before</b> · <b>now → then</b> · <b>here → there</b> · <b>this → that</b> · ago → before</p>
           <p class="sub">No step back is needed when it is still true or you report something just said: <i>She says she is tired.</i> / <i>He said the Earth goes round the Sun.</i></p>`},
    {k:"order", q:"Translate to English.", hi:"उसने कहा कि वह थका हुआ है।", words:["He","said","that","he","was","tired"], a:"He said that he was tired.",
     w:"<b>said that</b> + step back: <i>is → was</i>."},
    {k:"card", ref:"Reporting questions", tag:"The idea · 3 of 5", title:"Reporting questions: no flipping",
     html:`<p>This is Module 7's polite-question rule again: after <i>asked</i>, use <b>normal statement order</b>. No <i>do/does/did</i>, no question mark.</p>
           <div class="right">"Where do you live?" → She asked me where <b>I lived</b>.</div>
           <div class="right">"What is your name?" → He asked what <b>my name was</b>.</div>
           <div class="wrong">She asked me where did I live. &nbsp; She asked where do I live?</div>
           <p><b>Yes/no questions</b> use <b>if</b> or <b>whether</b>:</p>
           <div class="right">"Are you tired?" → He asked <b>if</b> I <b>was</b> tired. &nbsp; "Do you like tea?" → She asked <b>whether</b> I <b>liked</b> tea.</div>
           <p class="sub">The step-back rule still applies: <i>do live → lived, are → was, will → would.</i></p>`},
    {k:"card", ref:"Commands and requests", tag:"The idea · 4 of 5", title:"Reporting commands and requests",
     html:`<p>Use <b>told / asked + person + to + plain verb</b>:</p>
           <div class="right">"Sit down." → She <b>told me to sit</b> down.</div>
           <div class="right">"Please help me." → He <b>asked me to help</b> him.</div>
           <p>For <b>no</b>, put <b>not</b> before <b>to</b>:</p>
           <div class="right">"Don't be late." → She <b>told me not to be</b> late.</div>
           <div class="wrong">She said me to sit. &nbsp; She told me don't be late.</div>
           <p class="sub"><b>tell</b> = a command. <b>ask</b> = a request. Both need the person right after.</p>`},
    {k:"card", ref:"Reporting verbs", tag:"The idea · 5 of 5", title:"Better verbs than \"said\"",
     html:`<p>Reporting verbs show <i>how</i> something was said:</p>
           <table>
             <tr><td><b>promised</b> (to / that)</td><td>He promised to call. / He promised that he would call.</td></tr>
             <tr><td><b>suggested</b> (-ing / that)</td><td>She suggested going together.</td></tr>
             <tr><td><b>warned</b> (me not to)</td><td>He warned me not to go.</td></tr>
             <tr><td><b>refused</b> (to)</td><td>She refused to answer.</td></tr>
             <tr><td><b>admitted</b> (that)</td><td>He admitted that he was wrong.</td></tr>
             <tr><td><b>explained</b> (that)</td><td>She explained that the shop was closed.</td></tr>
             <tr><td><b>advised</b> (me to)</td><td>The doctor advised me to rest.</td></tr>
           </table>
           <p><b>Everyday use:</b> passing on messages: <i>Mom said she'd be late. The boss said the meeting was tomorrow. He asked if you could call him back.</i></p>`},
    {k:"mcq", q:"She said, \"I will call you.\" → She said she ___ call me.", o:["will","would","did"], a:1,
     w:["The tense steps back: <i>will → would</i>.","Yes. <b>will → would</b>.","<i>Did</i> doesn't fit."]},
    {k:"mcq", q:"He ___ me that he was busy.", o:["said","told","spoke"], a:1,
     w:["<i>Said</i> doesn't take a person directly: <i>said to me</i>.","Yes. <b>told me</b>: the listener comes right after.","<i>Spoke</i> doesn't fit this pattern."]},
    {k:"mcq", q:"She said, \"I live in Pune.\" → She said she ___ in Pune.", o:["lives","lived","was lived"], a:1,
     w:["Step back: <i>live → lived</i>.","Yes. <b>live → lived</b>.","Not a correct form."]},
    {k:"mcq", q:"\"Where do you live?\" → She asked me where I ___.", o:["live","lived","did live"], a:1,
     w:["Step back to the past: <i>lived</i>.","Yes. <b>where I lived</b>: normal order and the tense steps back.","Don't use <i>did</i> in reported questions."]},
    {k:"mcq", q:"\"Are you tired?\" → He asked me ___ I was tired.", o:["that","if","what"], a:1,
     w:["<i>That</i> reports statements, not yes/no questions.","Yes. A yes/no question → <b>if</b> (or <i>whether</i>).","<i>What</i> asks for information."]},
    {k:"order", q:"Translate to English.", hi:"उसने मुझसे पूछा कि मैं कहाँ रहता हूँ।", words:["She","asked","me","where","I","lived"], a:"She asked me where I lived.",
     w:"Normal order + step back: <b>where I lived</b>."},
    {k:"order", q:"Translate to English.", hi:"माँ ने मुझसे जल्दी आने को कहा।", words:["Mom","told","me","to","come","early"], a:"Mom told me to come early.",
     w:"<b>told me to</b> + plain verb."},
    {k:"type", q:"Translate to English.", hi:"उसने कहा कि वह कल फ़ोन करेगा।", a:["He said he would call tomorrow.","He said that he would call tomorrow.","He said he would call the next day.","He said that he would call the next day."], w:"<b>will → would</b>. <i>tomorrow</i> can become <i>the next day</i>."},
    {k:"order", q:"Translate to English.", hi:"उसने मुझसे पूछा कि क्या मैं भूखा हूँ।", words:["He","asked","me","if","I","was","hungry"], a:"He asked me if I was hungry.",
     w:"Yes/no question → <b>if</b> + normal order + step back."},
    {k:"mcq", q:"Which is correct?", o:["She asked me where did I go.","She asked me where I went.","She asked me where I go did."], a:1,
     w:["No <i>did</i> in a reported question.","Yes. Normal order.","Wrong order."]},
    {k:"mcq", q:"\"Don't be late.\" → She told me ___ late.", o:["to not be","not to be","don't be"], a:1,
     w:["<i>Not</i> goes before <i>to</i>.","Yes. <b>told me not to be</b>.","Commands become <i>to</i> + verb."]},
    {k:"mcq", q:"\"I have finished.\" → He said he ___ finished.", o:["has","had","have"], a:1,
     w:["Step back: <i>have</i> → <i>had</i>.","Yes. Present perfect → <b>past perfect</b>.","<i>He</i> needs a changed verb."]},
    {k:"mcq", q:"\"I will come tomorrow.\" → She said she would come ___.", o:["tomorrow","the next day","yesterday"], a:1,
     w:["<i>Tomorrow</i> shifts when reporting later.","Yes. <b>tomorrow → the next day</b>.","<i>Yesterday</i> is the wrong direction."]},
    {k:"mcq", q:"He ___ to call me back, but he didn't.", o:["promised","said","told"], a:0,
     w:["Yes. <b>promised to</b> + verb.","<i>Said</i> doesn't fit <i>to call</i>.","<i>Told</i> needs a person first."]},
    {k:"mcq", q:"Revision from Module 13: If I had time, I ___ help you.", o:["would","will","had"], a:0,
     w:["Yes. <b>if + past, would</b>.","<i>Will</i> is for real possibilities.","<i>Had</i> doesn't fit."]},
    {k:"build", intro:"Your turn. Pass on messages from <b>your own life</b>. Type each one and say it out loud.",
     items:[
      {p:"Report what a friend or family member said today.", frame:"My ______ said that ______.", ex:"My mother said that she would be late.", must:/\b(said|told me)\b/i, ok:"Reported statement with a step back.", tip:"<b>My friend said (that) he/she was ...</b>"},
      {p:"Report a question someone asked you.", frame:"She asked me where / if ______.", ex:"My colleague asked me where I lived.", must:/\basked\b.*\b(if|whether|where|what|when|why|how|who)\b/i, ok:"No flipping after asked.", tip:"<b>asked me where I lived</b> / <b>asked if I was ...</b>"},
      {p:"Report a request from your boss, teacher or parent.", frame:"My ______ asked / told me to ______.", ex:"My boss asked me to send the report.", must:/\b(told|asked)\b.*\bto\b/i, ok:"<b>told/asked + me + to + verb</b>.", tip:"<b>asked me to + plain verb</b>"},
      {p:"Report a promise.", frame:"He / She promised to ______.", ex:"My brother promised to help me move.", must:/\bpromised\b/i, ok:"<b>promised to</b>.", tip:"<b>promised to + plain verb</b>"},
      {p:"Report the weather forecast.", frame:"The forecast said it would ______.", ex:"The forecast said it would rain tomorrow.", must:/\b(said|says)\b.*\bwould\b/i, ok:"<b>will → would</b>. Perfect.", tip:"<b>The forecast said it would rain.</b>"}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"He said me that he was tired.", good:"He told me that he was tired. / He said that he was tired.", fix:"<b>tell</b> + person. <b>say</b> + what was said."},
      {bad:"She asked me where did I live.", good:"She asked me where I lived.", fix:"After asked: normal order, no <i>do/did</i>."},
      {bad:"He told that he was tired.", good:"He told me that he was tired.", fix:"<i>Tell</i> needs a person right after."},
      {bad:"She said me to sit.", good:"She told me to sit.", fix:"Commands: <b>told me to</b> + plain verb."},
      {bad:"He said he will come. (said earlier)", good:"He said he would come.", fix:"Step back: <i>will → would</i>."}
     ]},
    {k:"boss", ref:"Boss", title:"Phase 3 review: The Messenger", pass:0.8,
     intro:"This is the last gate of Phase 3. 12 questions on reporting speech, plus connectors, comparing and conditionals from Modules 11 to 13. You need 10 of 12 to earn your trophy.",
     qs:[
      {k:"mcq", ref:"Tenses step back", q:"\"I am busy.\" → He said he ___ busy.", o:["is","was","were"], a:1, w:["Step back for the usual report.","Yes: <b>am → was</b>.","<i>Were</i> is for you/we/they."]},
      {k:"mcq", ref:"Tenses step back", q:"\"I will help.\" → She said she ___ help.", o:["will","would","did"], a:1, w:["Step back.","Yes: <b>will → would</b>.","<i>Did</i> doesn't fit."]},
      {k:"mcq", ref:"say and tell", q:"She ___ me that she was late.", o:["said","told","spoke"], a:1, w:["<i>Said</i> doesn't take a person directly.","Yes: <b>told me</b>.","Doesn't fit."]},
      {k:"mcq", ref:"Reporting questions", q:"\"Where do you work?\" → He asked where I ___.", o:["work","worked","did work"], a:1, w:["Step back.","Yes: <b>worked</b>, normal order.","No <i>did</i> in reported questions."]},
      {k:"mcq", ref:"Commands and requests", q:"\"Don't touch it.\" → She told me ___ it.", o:["not to touch","to not touch","don't touch"], a:0, w:["Yes: <b>not to</b> + plain verb.","<i>Not</i> goes before <i>to</i>.","Commands become <i>to</i> + verb."]},
      {k:"order", ref:"Reporting questions", q:"Translate to English.", hi:"उसने मुझसे पूछा कि मैं कब आऊँगा।", words:["He","asked","me","when","I","would","come"], a:"He asked me when I would come.", w:"Normal order + <b>will → would</b>."},
      {k:"type", ref:"Tenses step back", q:"Translate to English.", hi:"उसने कहा कि वह व्यस्त है।", a:["He said he was busy.","He said that he was busy.","She said she was busy.","She said that she was busy."], w:"<b>is → was</b>."},
      {k:"mcq", ref:"Module 11: connectors", q:"I didn't go ___ I was ill.", o:["so","because","although"], a:1, w:["<i>So</i> goes before the result.","Yes: a reason → <b>because</b>.","<i>Although</i> shows a surprise."]},
      {k:"mcq", ref:"Module 12: comparing", q:"Delhi is ___ than Pune.", o:["more big","bigger","biggest"], a:1, w:["Short words take <i>-er</i>.","Yes: <b>bigger than</b>.","<i>Biggest</i> needs <i>the</i>."]},
      {k:"mcq", ref:"Module 13: conditionals", q:"If I had money, I ___ buy it.", o:["will","would","had"], a:1, w:["<i>Will</i> is for real possibilities.","Yes: second conditional → <b>would</b>.","<i>Had</i> doesn't fit."]},
      {k:"mcq", ref:"Module 13: conditionals", q:"If it rains, we ___ stay home.", o:["would","will","had"], a:1, w:["That is imaginary.","Yes: real possibility → <b>will</b>.","Doesn't fit."]},
      {k:"mcq", ref:"Module 12: comparing", q:"Which is the most polite disagreement?", o:["That's wrong.","I see what you mean, but I'm not sure I agree.","No way."], a:1, w:["Blunt.","Yes: acknowledge + <b>but</b>.","Rude."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Pass on what people said: <i>He said he was tired. Mom said she would be late. The boss told me the meeting was tomorrow.</i>",
          "Report questions without flipping: <i>She asked where I lived. He asked if I was hungry.</i>",
          "Report requests and promises: <i>She told me to sit. He asked me not to be late. He promised to call.</i>"],
     teaser:"Next: <b>Phase 4, Real Life.</b> Introduce yourself, ask for help, disagree, complain, tell a story and make phone calls."}
  ]
});
