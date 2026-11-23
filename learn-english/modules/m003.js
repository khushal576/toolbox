registerModule({
  id: 3,
  title: "Present continuous",
  sub: "what is happening now",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 3 · Start here", title:"The phone call",
     html:`<p>Your friend calls. You are cooking dinner <i>at this exact moment</i>. They ask: <b>"What are you doing?"</b></p>
           <p>Module 2 gave you <i>I cook</i>. Is that the right answer? Let's find out.</p>`},
    {k:"mcq", q:"You are cooking right now. What do you say?",
     o:["I cook.","I cooking.","I am cook.","I'm cooking."], a:3,
     w:["<i>I cook</i> is for habits (Module 2): \"I cook every evening.\" It doesn't say \"right now\".",
        "Close! But the glue word from Module 1 is missing.",
        "You have the glue, but the action word needs <b>-ing</b>.",
        "Yes! <b>Glue (am) + action-ing</b>. That's the whole module."]},
    {k:"card", ref:"What it is for", tag:"The idea · 1 of 6", title:"What it is for: now, and around now",
     html:`<p>Present continuous shows an action <b>in progress</b>:</p>
           <div class="right">I'm cooking. <span class="sub">(right now)</span></div>
           <div class="right">She's studying for an exam this month. <span class="sub">(around now, not this second)</span></div>
           <div class="right">I'm staying with my cousin for a few days. <span class="sub">(temporary)</span></div>
           <p>Compare with Module 2:</p>
           <table>
             <tr><td><b>I work</b> in a bank.</td><td class="sub">always, my normal life</td></tr>
             <tr><td><b>I'm working</b> from home today.</td><td class="sub">now / temporary</td></tr>
           </table>
           <p><b>Simple test:</b> if you could add <i>"…at the moment"</i> and it still makes sense, use present continuous.</p>`},
    {k:"card", ref:"The frame", tag:"The idea · 2 of 6", title:"The glue comes back",
     html:`<p>Remember Module 1? <i>am / is / are</i> is back, with a new job. Now it is a <b>helper</b> for the action word:</p>
           <div class="frame"><span class="who">She</span><span class="glue">is</span><span class="rest">working.</span></div>
           <div class="frame"><span class="who">They</span><span class="glue">are</span><span class="rest">sleeping.</span></div>
           <div class="frame"><span class="who">I</span><span class="glue">am</span><span class="rest">reading.</span></div>
           <p>You pick <i>am / is / are</i> exactly as before (I → am, one → is, you/we/they/many → are). Then add <b>verb + ing</b>.</p>
           <p><b>You need both halves.</b> The glue alone or the -ing alone is not enough:</p>
           <div class="wrong">She working.</div><div class="wrong">She is work.</div><div class="right">She is working.</div>
           <p class="sub">Notice there is no S on the verb now. The S job belongs to <b>is</b>. One signal per sentence, same idea as Module 2.</p>`},
    {k:"order", q:"Build it.", words:["I","am","working","from","home","today"], a:"I am working from home today.",
     w:"I + <b>am</b> + working. The glue and the -ing travel together."},
    {k:"order", q:"One more.", words:["They're","playing","football","outside"], a:"They're playing football outside.",
     w:"They're = They are. Shrunk glue + verb-ing."},
    {k:"card", ref:"Spelling -ing", tag:"The idea · 3 of 6", title:"Spelling -ing",
     html:`<table>
             <tr><th>Verb</th><th>Do this</th><th>Example</th></tr>
             <tr><td>most verbs</td><td>+ ing</td><td>work → working<br>play → playing<br>study → studying</td></tr>
             <tr><td>ends in silent <b>e</b></td><td>drop the e</td><td>make → making<br>write → writing<br>come → coming</td></tr>
             <tr><td>short word: consonant + vowel + consonant</td><td>double the last letter</td><td>run → running<br>sit → sitting<br>stop → stopping</td></tr>
             <tr><td>ends in <b>ie</b></td><td>ie → y</td><td>lie → lying<br>die → dying</td></tr>
           </table>
           <p class="sub">Why double? It keeps the vowel short. <i>runing</i> would look like it's read "ROO-ning". <i>running</i> keeps the "uh" sound.</p>
           <p class="sub">Don't double for w, x, y: <i>snowing, fixing, playing</i>. Don't double when the stress is not on the last part: <i>visiting, opening</i>.</p>`},
    {k:"card", ref:"No and questions", tag:"The idea · 4 of 6", title:"No and questions: you already know this",
     html:`<p>No new tools here. It is Module 1 again, because the glue is the first word:</p>
           <div class="right">I'm not working. &nbsp; She <b>isn't</b> working. &nbsp; They <b>aren't</b> working.</div>
           <div class="frame"><span class="glue">Are</span><span class="who">you</span><span class="rest">working?</span></div>
           <div class="right">Is she sleeping? &nbsp; What <b>are</b> you doing? &nbsp; Where <b>is</b> he going?</div>
           <p>Short answers keep the glue, in full: <b>Yes, I am. &nbsp; No, she isn't.</b> (Remember: no shrinking at the end.)</p>
           <div class="fb note"><b>Do / does is not used here.</b> The glue is already the helper.</div>
           <div class="wrong">Do you working?</div><div class="wrong">Are you work?</div><div class="right">Are you working?</div>`},
    {k:"card", ref:"Verbs that don't like -ing", tag:"The idea · 5 of 6", title:"Verbs that don't like -ing",
     html:`<p>Some verbs are not actions you can "do in progress". They are <b>states</b>, meaning what you know, feel, want or own:</p>
           <p><b>know, understand, believe, like, love, hate, want, need, prefer, own</b></p>
           <p>With these, use the simple form even when you mean "right now":</p>
           <div class="wrong">I am knowing the answer.</div><div class="right">I know the answer.</div>
           <div class="wrong">She is wanting a coffee.</div><div class="right">She wants a coffee.</div>
           <p class="sub">Why? You can't "be in the middle of knowing". You either know it or you don't. (<i>I'm lovin' it</i> is an advertising slogan, a joke on this rule. Don't copy it in exams.)</p>
           <p><b>Careful with <i>have</i>:</b> owning is a state (<i>I have a car</i>), but doing is an action (<i>I'm having lunch</i>).</p>`},
    {k:"card", ref:"Now or always?", tag:"The idea · 6 of 6", title:"Now or always? How to choose",
     html:`<p>Look for the clue words:</p>
           <table>
             <tr><th>Present simple (Module 2)</th><th>Present continuous</th></tr>
             <tr><td>always, usually, often, every day, never</td><td>now, right now, at the moment, today, this week</td></tr>
             <tr><td>I drink tea.</td><td>I'm drinking tea.</td></tr>
           </table>
           <p>Also: <b>Look!</b> and <b>Listen!</b> usually bring continuous: <i>Look! It's snowing.</i></p>
           <p>Both can live in one sentence, and that is how real people talk:</p>
           <div class="right">She usually <b>drinks</b> coffee, but today she <b>is drinking</b> tea.</div>`},
    {k:"mcq", q:"Shh! The baby ___.", o:["sleeps","is sleeping","is sleep"], a:1,
     w:["<i>Sleeps</i> is a habit. Here something is happening now.","Yes. Right now → <b>is sleeping</b>.","The glue is there, but the action needs <b>-ing</b>."]},
    {k:"mcq", q:"I ___ English every day.", o:["am studying","studying","study"], a:2,
     w:["\"Every day\" is a habit, so use Module 2.","The glue is missing, and it's a habit anyway.","Yes. <b>Every day</b> → present simple: I study."]},
    {k:"mcq", q:"They ___ football in the park right now.", o:["play","is playing","are playing"], a:2,
     w:["\"Right now\" needs -ing.","\"They\" is plural, so the glue is <b>are</b>.","Yes. They + are + playing."]},
    {k:"type", q:"He is ___ (run) in the park.", a:["running"], w:"Short word, consonant + vowel + consonant → double the n: <b>running</b>."},
    {k:"type", q:"She is ___ (make) dinner.", a:["making"], w:"Drop the silent e: make → <b>making</b>."},
    {k:"type", q:"We are ___ (sit) outside.", a:["sitting"], w:"Double the t: <b>sitting</b>."},
    {k:"mcq", q:"Which question is correct?", o:["Do you working now?","Are you work now?","Are you working now?"], a:2,
     w:["No <i>do</i> here. The glue is the helper.","The action needs <b>-ing</b>.","Yes. Glue first, then verb-ing."]},
    {k:"order", q:"Build the question.", words:["What","are","you","doing"], a:"What are you doing?", w:"Question word, then the glue, then WHO, then the -ing verb."},
    {k:"order", q:"Build the negative.", words:["She","isn't","answering","her","phone"], a:"She isn't answering her phone.", w:"Glue + not (Module 1) + verb-ing."},
    {k:"mcq", q:"I ___ this song.", o:["am loving","loves","love"], a:2,
     w:["<i>Love</i> is a state verb. It doesn't take -ing.","The WHO is I, so no S.","Yes. State verbs stay simple: <b>I love</b> this song."]},
    {k:"mcq", q:"She usually ___ coffee, but today she ___ tea.", o:["is drinking / drinks","drinks / is drinking","drinks / drinks"], a:1,
     w:["The order is reversed: usually → simple, today → continuous.","Yes. <b>usually → drinks</b> (habit), <b>today → is drinking</b>.","\"Today\" needs the continuous."]},
    {k:"order", q:"Revision from Module 1!", words:["Is","he","at","home"], a:"Is he at home?", w:"No -ing here. This is a Module 1 sentence: the glue jumps to the front."},
    {k:"build", intro:"Your turn. Real sentences about <b>what's happening around you</b>. Type each one and say it out loud.",
     items:[
      {p:"What are you doing right now?", frame:"I am ______ing.", ex:"I'm sitting on my bed and studying English.", must:/\b(i am|i'm)\s+\w+ing\b/i, ok:"Glue + verb-ing. Right.", tip:"Start with <b>I'm</b> + a verb ending in <b>-ing</b>."},
      {p:"What is someone near you doing?", frame:"My ______ is ______ing.", ex:"My mother is cooking in the kitchen.", must:/\b(is|'s)\s+\w+ing\b/i, ok:"One person → <b>is</b> + -ing.", tip:"One person → <b>is</b> + verb-ing."},
      {p:"Say something you are NOT doing now.", frame:"I'm not ______ing.", ex:"I'm not watching TV.", must:/(i'm not|i am not)\s+\w+ing/i, ok:"Perfect negative.", tip:"<b>I'm not</b> + verb-ing."},
      {p:"Something you are doing this week that is different from normal.", frame:"This week I'm ______ing.", ex:"This week I'm working late.", must:/\b(i'm|i am)\s+\w+ing\b/i, ok:"Temporary situation: exactly right for this tense.", tip:"<b>This week I'm ...ing</b>"},
      {p:"Ask me a question about what I'm doing.", frame:"What are you ______ing? / Are you ______ing?", ex:"What are you doing?", must:/^\s*(are|is|what|where|who|why)\b/i, ok:"A real question.", tip:"Start with <b>Are</b> or a question word + <b>are</b>."}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"She working now.", good:"She is working now.", fix:"-ing needs the glue (am/is/are) in front, as in Module 1."},
      {bad:"I am work now.", good:"I am working now.", fix:"Glue + verb-<b>ing</b>. Both halves."},
      {bad:"Do you working?", good:"Are you working?", fix:"No do/does here. The glue is the helper."},
      {bad:"I am knowing the answer.", good:"I know the answer.", fix:"State verbs (know, like, want, need, love) stay simple."},
      {bad:"He is runing. / She is makeing.", good:"He is running. / She is making.", fix:"Double the last letter in short words (run → running). Drop the silent e (make → making)."}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: The Live Reporter", pass:0.8,
     intro:"You are a reporter describing what's happening, right now. This also revisits Modules 1 and 2. You need 8 of 10.",
     qs:[
      {k:"type", ref:"The frame", q:"They ___ waiting outside. <span class='sub'>(am / is / are)</span>", a:["are"], w:"They → <b>are</b>. Glue from Module 1."},
      {k:"type", ref:"Spelling -ing", q:"She is ___ (sit) on the sofa.", a:["sitting"], w:"Double the t: sitting."},
      {k:"mcq", ref:"Now or always?", q:"Look! It ___.", o:["snows","is snowing","snowing"], a:1, w:["<i>Look!</i> means now, so use -ing.","Yes: <b>is snowing</b>.","The glue is missing."]},
      {k:"order", ref:"No and questions", q:"Build the question.", words:["Are","you","listening","to","me"], a:"Are you listening to me?", w:"Glue first, then WHO, then verb-ing."},
      {k:"mcq", ref:"Verbs that don't like -ing", q:"I ___ the answer.", o:["am knowing","know","knowing"], a:1, w:["<i>Know</i> is a state verb. No -ing.","Yes: <b>I know</b>.","The glue and the verb form are both wrong."]},
      {k:"mcq", ref:"No and questions", q:"Which is correct?", o:["Does she working?","Is she working?","Is she work?"], a:1, w:["No does/do here.","Yes: <b>Is she working?</b>","The action needs -ing."]},
      {k:"type", ref:"Spelling -ing", q:"He is ___ (write) a letter.", a:["writing"], w:"Drop the e: <b>writing</b>."},
      {k:"mcq", ref:"Now or always?", q:"My dad ___ in a bank. This week he ___ from home.", o:["is working / works","works / is working","works / works"], a:1, w:["Reversed. The normal job is simple, the temporary one is -ing.","Yes: <b>works</b> (normal) / <b>is working</b> (this week).","\"This week\" needs the -ing form."]},
      {k:"order", ref:"No and questions", q:"Build the negative.", words:["She","isn't","working","today"], a:"She isn't working today.", w:"Glue + not + verb-ing."},
      {k:"mcq", ref:"What it is for", q:"Which sentence is about a habit, not about now?", o:["I'm drinking tea.","She is reading.","I drink tea every morning."], a:2, w:["That's happening now.","That's happening now.","Yes: <b>every morning</b> → habit → present simple."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Say what is happening right now: <i>I'm cooking. They're playing outside. It's raining.</i>",
          "Talk about temporary situations: <i>I'm working from home this week.</i>",
          "Ask what people are doing: <i>What are you doing? Are you coming?</i> And choose correctly between <i>I work</i> and <i>I'm working</i>."],
     teaser:"Next: <b>Past simple.</b> Talk about what already happened: <i>I worked, she went, did you see it?</i>"}
  ]
});
