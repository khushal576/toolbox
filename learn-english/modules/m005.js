registerModule({
  id: 5,
  title: "Present perfect (vs past)",
  sub: "linking the past to now",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 5 · Start here", title:"Same city, different tense",
     html:`<p>You moved to Pune in 2020. You <i>still</i> live there. A new colleague asks: <b>"How long have you been in Pune?"</b></p>
           <p>Module 4 taught you <i>I lived</i>. Does that work here? Try it.</p>`},
    {k:"mcq", q:"You moved to Pune in 2020 and you still live there. What do you say?",
     o:["I live in Pune since 2020.","I lived in Pune since 2020.","I am living in Pune since 2020.","I have lived in Pune since 2020."], a:3,
     w:["<i>Live</i> alone can't be used with <i>since</i>. English wants a different shape to link past and now.",
        "<i>Lived</i> means it's over. But you still live there.",
        "Closer, but <i>am living</i> doesn't pair with <i>since</i> this way.",
        "Yes! <b>have + lived</b>: it began in the past and is still true now. That's the whole module."]},
    {k:"card", ref:"What it is for", tag:"The idea · 1 of 6", title:"The tense that holds hands with now",
     html:`<p>Past simple <b>closes the door</b> on the past: <i>I lived in Delhi in 2015.</i> Done.</p>
           <p>Present perfect keeps the door <b>open to now</b>. It has three jobs:</p>
           <div class="right"><b>Experience</b> (any time in life): I've been to Goa.</div>
           <div class="right"><b>Still true</b> (started before, continues): I've lived here for five years.</div>
           <div class="right"><b>Result now</b>: I've lost my keys. <span class="sub">(so I can't get in now)</span></div>
           <p><b>Ask yourself:</b> "Is the <i>when</i> important, or the <i>now</i>?" If the when is not important, or it connects to now, use present perfect.</p>`},
    {k:"card", ref:"The frame", tag:"The idea · 2 of 6", title:"have / has + the third form",
     html:`<p>Two pieces: <b>have/has</b> + the <b>past participle</b>.</p>
           <div class="frame"><span class="who">I</span><span class="glue">have</span><span class="rest">seen it.</span></div>
           <div class="frame"><span class="who">She</span><span class="glue">has</span><span class="rest">seen it.</span></div>
           <p><b>have</b> for I / you / we / they. <b>has</b> for he / she / it. The S from Module 2 now lives in <b>has</b>, so the verb never gets an S.</p>
           <p><b>Regular verbs:</b> the participle is the same as the Module 4 past: worked, played, studied.</p>
           <p><b>Irregular verbs:</b> learn three forms together:</p>
           <table>
             <tr><th>Now</th><th>Past (M4)</th><th>Participle</th></tr>
             <tr><td>go</td><td>went</td><td><b>gone</b></td></tr>
             <tr><td>be</td><td>was/were</td><td><b>been</b></td></tr>
             <tr><td>see</td><td>saw</td><td><b>seen</b></td></tr>
             <tr><td>do</td><td>did</td><td><b>done</b></td></tr>
             <tr><td>take</td><td>took</td><td><b>taken</b></td></tr>
             <tr><td>write</td><td>wrote</td><td><b>written</b></td></tr>
             <tr><td>eat</td><td>ate</td><td><b>eaten</b></td></tr>
             <tr><td>make / buy / have / say / tell</td><td>made / bought / had / said / told</td><td><b>same as past</b></td></tr>
           </table>
           <p class="sub">Good news: many of the most common verbs have the same past and participle. Say them as chunks: <i>I have seen. I have been. I have done.</i></p>
           <div class="fb note">In speech: <b>I've, you've, we've, they've</b> and <b>she's, he's</b> (<i>she's</i> can mean <i>she is</i> or <i>she has</i>. The next word tells you: <i>she's tired</i> vs <i>she's finished</i>).</div>`},
    {k:"order", q:"Build it.", words:["I","have","never","been","to","Goa"], a:"I have never been to Goa.",
     w:"WHO + have + <b>never</b> + been. A life experience, no time needed."},
    {k:"order", q:"A different WHO.", words:["She","has","already","left"], a:"She has already left.",
     w:"<b>She has</b>. The S job belongs to <i>has</i>, so <i>left</i> stays as it is."},
    {k:"card", ref:"For and since", tag:"The idea · 3 of 6", title:"for and since: how long?",
     html:`<p>To say <b>how long</b> something has been true, you need one of two small words:</p>
           <table>
             <tr><th>for</th><th>since</th></tr>
             <tr><td>a <b>length</b> of time</td><td>a <b>starting point</b></td></tr>
             <tr><td>for five years<br>for two weeks<br>for a long time</td><td>since 2020<br>since Monday<br>since I was a child</td></tr>
           </table>
           <div class="right">I have lived here <b>for</b> five years.</div>
           <div class="right">I have lived here <b>since</b> 2020.</div>
           <div class="wrong">I have lived here since five years.</div>
           <p>The question: <b>How long have you lived here?</b></p>`},
    {k:"card", ref:"No and questions", tag:"The idea · 4 of 6", title:"No, questions and the little words",
     html:`<p>The helper is <b>have/has</b>, so it works just like the glue in Module 1:</p>
           <div class="right">I <b>haven't</b> finished. &nbsp; She <b>hasn't</b> called.</div>
           <div class="frame"><span class="glue">Have</span><span class="who">you</span><span class="rest">eaten?</span></div>
           <div class="right">Has she arrived? &nbsp; What <b>have</b> you done?</div>
           <p>Short answers: <b>Yes, I have. &nbsp; No, she hasn't.</b> (No shrinking at the end, remember.)</p>
           <p><b>Five small words that love this tense:</b></p>
           <table>
             <tr><td><b>ever</b></td><td>in questions: Have you <b>ever</b> been to Goa?</td></tr>
             <tr><td><b>never</b></td><td>I have <b>never</b> tried sushi.</td></tr>
             <tr><td><b>already</b></td><td>I have <b>already</b> eaten.</td></tr>
             <tr><td><b>yet</b></td><td>at the end, in no and questions: I haven't eaten <b>yet</b>. Have you eaten <b>yet</b>?</td></tr>
             <tr><td><b>just</b></td><td>a moment ago: I have <b>just</b> arrived.</td></tr>
           </table>`},
    {k:"card", ref:"Been vs gone", tag:"The idea · 5 of 6", title:"been or gone?",
     html:`<p>Two participles of <i>go</i>, two different meanings:</p>
           <div class="right">She has <b>been</b> to Mumbai. <span class="sub">(she went and came back; experience)</span></div>
           <div class="right">She has <b>gone</b> to Mumbai. <span class="sub">(she went and is still there, or on the way)</span></div>
           <p>That's why you ask <b>"Have you ever <u>been</u> to Goa?"</b> (not <i>gone</i>), but you say <b>"Where's Ravi? He's gone to the bank."</b></p>`},
    {k:"card", ref:"Present perfect or past simple?", tag:"The idea · 6 of 6", title:"The big choice",
     html:`<p>This is where learners get stuck. Here's the test:</p>
           <table>
             <tr><th>Past simple (Module 4)</th><th>Present perfect</th></tr>
             <tr><td><b>finished time is named</b><br>yesterday, last year, in 2019, two days ago, when I was young</td><td><b>no time, or time up to now</b><br>ever, never, already, yet, just, for, since, this week, today</td></tr>
             <tr><td>I saw him yesterday.</td><td>I have seen him.</td></tr>
           </table>
           <div class="wrong">I have seen him yesterday.</div>
           <p>The moment you add a finished time, use the past simple. Even in one conversation:</p>
           <div class="right">"Have you <b>been</b> to Goa?" &nbsp; "Yes, I <b>went</b> there in 2019."</div>
           <p class="sub">The question asks about experience (perfect). The answer gives the time, so it switches to the past.</p>`},
    {k:"mcq", q:"I ___ lunch already.", o:["have eaten","eaten","has eaten"], a:0,
     w:["Yes. I + <b>have</b> + eaten.","You need <i>have</i> before the participle.","\"I\" goes with <b>have</b>, not <i>has</i>."]},
    {k:"mcq", q:"She ___ here since 2020.", o:["lives","has lived","lived"], a:1,
     w:["<i>Since</i> needs the perfect shape.","Yes. Started in the past, still true: <b>has lived</b>.","<i>Lived</i> would mean she left."]},
    {k:"mcq", q:"I have lived here ___ five years.", o:["since","for","from"], a:1,
     w:["<i>Since</i> goes with a starting point (since 2019).","Yes. <b>for</b> + a length of time.","Not used this way."]},
    {k:"mcq", q:"I have lived here ___ 2019.", o:["for","since","in"], a:1,
     w:["<i>For</i> goes with a length of time (for five years).","Yes. <b>since</b> + a starting point.","\"I have lived here in 2019\" doesn't work."]},
    {k:"type", q:"I have ___ (see) that film.", a:["seen"], w:"see → saw → <b>seen</b>."},
    {k:"type", q:"She has ___ (write) three emails.", a:["written"], w:"write → wrote → <b>written</b>."},
    {k:"type", q:"We have ___ (be) friends since school.", a:["been"], w:"be → was/were → <b>been</b>."},
    {k:"type", q:"He has ___ (do) his homework.", a:["done"], w:"do → did → <b>done</b>."},
    {k:"mcq", q:"Have you ___ to Goa?", o:["went","gone","been"], a:2,
     w:["<i>Went</i> is the simple past. After <i>have</i> you need the participle.","<i>Gone</i> means you're still there.","Yes. Experience (you came back): <b>been</b>."]},
    {k:"mcq", q:"Which is correct?", o:["I have seen him yesterday.","I saw him yesterday.","I have saw him yesterday."], a:1,
     w:["<i>Yesterday</i> is a finished time. That needs the past simple.","Yes. Named finished time → <b>saw</b>.","<i>Saw</i> is the past; after <i>have</i> you need <i>seen</i>. And <i>yesterday</i> needs the past anyway."]},
    {k:"mcq", q:"Where's Ravi? — He ___ to the bank. He'll be back soon.", o:["has been","has gone","went"], a:1,
     w:["<i>Been</i> would mean he has already come back.","Yes. He's on his way or there now: <b>has gone</b>.","<i>Went</i> doesn't link to now."]},
    {k:"mcq", q:"He ___ his keys. He can't get in.", o:["loses","have lost","has lost"], a:2,
     w:["A result that matters now needs the perfect.","\"He\" goes with <b>has</b>.","Yes. <b>has lost</b>: past action, result now."]},
    {k:"order", q:"Build the negative.", words:["She","hasn't","called","me","yet"], a:"She hasn't called me yet.", w:"<b>hasn't</b> + participle, <i>yet</i> at the end."},
    {k:"order", q:"Build the question.", words:["Have","you","finished","your","work"], a:"Have you finished your work?", w:"The helper <b>have</b> goes first."},
    {k:"order", q:"Build the question.", words:["How","long","have","you","lived","here"], a:"How long have you lived here?", w:"How long + have + WHO + participle."},
    {k:"order", q:"Revision from Module 4!", words:["I","went","there","in","2019"], a:"I went there in 2019.", w:"<i>In 2019</i> is a finished time → past simple."},
    {k:"mcq", q:"Revision from Module 3: what is happening right NOW?", o:["I've eaten.","I ate.","I'm eating."], a:2,
     w:["Finished, with a result now.","Finished in the past.","Yes. <b>am + -ing</b> = in progress now."]},
    {k:"build", intro:"Your turn. Real sentences about <b>your life so far</b>. Type each one and say it out loud.",
     items:[
      {p:"Tell me about a place you have been, or never been.", frame:"I have been to ______. / I have never been to ______.", ex:"I have never been to Goa, but I want to go.", must:/\b(i have|i've)\s+(never\s+)?been\b/i, ok:"Experience, no time needed. Right.", tip:"<b>I have (never) been to ...</b>"},
      {p:"How long have you lived where you live, or studied English?", frame:"I have ______ for / since ______.", ex:"I have lived here for ten years.", must:/\b(i have|i've)\b.*\b(for|since)\b/i, ok:"<i>for</i> or <i>since</i> with the perfect. Exactly right.", tip:"<b>I have lived here for ... years</b> or <b>since ...</b>"},
      {p:"Something you have already done today.", frame:"I have already ______.", ex:"I've already had breakfast.", must:/\b(i have|i've)\s+already\b/i, ok:"<i>already</i> sits between have and the participle.", tip:"<b>I've already ...</b> + participle"},
      {p:"Something you haven't done yet.", frame:"I haven't ______ yet.", ex:"I haven't called my mother yet.", must:/(haven't|have not)/i, ok:"<i>haven't</i> + participle + <i>yet</i>.", tip:"<b>I haven't ... yet.</b>"},
      {p:"Ask me about my experience, starting with Have you ever.", frame:"Have you ever ______?", ex:"Have you ever eaten sushi?", must:/^\s*(have|has|how long|what have)\b/i, ok:"A real present-perfect question.", tip:"Start with <b>Have you ever ...?</b>"}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"I have seen him yesterday.", good:"I saw him yesterday.", fix:"Finished time (yesterday, last year, ago) → past simple."},
      {bad:"I live here since 2020.", good:"I have lived here since 2020.", fix:"<i>Since / for</i> with something still true → present perfect."},
      {bad:"I have lived here since five years.", good:"I have lived here for five years.", fix:"<b>for</b> + length, <b>since</b> + starting point."},
      {bad:"She have finished.", good:"She has finished.", fix:"he / she / it → <b>has</b>."},
      {bad:"Have you went there?", good:"Have you gone / been there?", fix:"After <i>have</i> use the participle (gone/been), not the past (went)."}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: The Interview", pass:0.8,
     intro:"A friendly interviewer asks about your life so far. This also revisits Modules 1 to 4. You need 8 of 10.",
     qs:[
      {k:"mcq", ref:"The frame", q:"She ___ finished her work.", o:["have","has","is"], a:1, w:["\"She\" goes with <b>has</b>.","Yes: <b>has finished</b>.","<i>Is finished</i> is a different structure."]},
      {k:"type", ref:"The frame", q:"I have ___ (take) the medicine.", a:["taken"], w:"take → took → <b>taken</b>."},
      {k:"mcq", ref:"For and since", q:"He has worked here ___ 2018.", o:["for","since","from"], a:1, w:["<i>For</i> needs a length of time.","Yes: <b>since</b> + starting point.","Not used this way."]},
      {k:"mcq", ref:"For and since", q:"We have been friends ___ ten years.", o:["for","since","in"], a:0, w:["Yes: <b>for</b> + a length of time.","<i>Since</i> needs a starting point (since 2015).","Not used this way."]},
      {k:"mcq", ref:"Present perfect or past simple?", q:"Which is correct?", o:["I have visited Delhi last year.","I visited Delhi last year.","I have visit Delhi last year."], a:1, w:["<i>Last year</i> is a finished time → past simple.","Yes: <b>visited</b>.","The participle form is wrong too."]},
      {k:"order", ref:"No and questions", q:"Build the question.", words:["Have","you","ever","eaten","sushi"], a:"Have you ever eaten sushi?", w:"<b>Have</b> + WHO + ever + participle."},
      {k:"order", ref:"No and questions", q:"Build the negative.", words:["She","hasn't","called","me","yet"], a:"She hasn't called me yet.", w:"<b>hasn't</b> + participle + <i>yet</i>."},
      {k:"mcq", ref:"Been vs gone", q:"Where is Ravi? — He has ___ to the bank. He'll be back soon.", o:["been","gone","went"], a:1, w:["<i>Been</i> would mean he already came back.","Yes: <b>gone</b> (still away).","<i>Went</i> doesn't link to now."]},
      {k:"type", ref:"No and questions", q:"They ___ the film yet. <span class='sub'>(not + see)</span>", a:["haven't seen","have not seen"], w:"<b>haven't seen</b>."},
      {k:"mcq", ref:"Present perfect or past simple?", q:"Have you been to Goa? — Yes, I ___ there in 2019.", o:["went","have been","have gone"], a:0, w:["Yes: the time is named (<i>in 2019</i>), so → <b>went</b>.","A named finished time needs the past simple.","A named finished time needs the past simple."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Talk about experiences: <i>I've been to Goa. I've never tried sushi. Have you ever been to Delhi?</i>",
          "Say how long: <i>I've lived here for five years. I've known her since school.</i>",
          "Ask and answer about things done or not done: <i>Have you eaten yet? I've already finished.</i> And choose between <i>I saw</i> and <i>I've seen</i>."],
     teaser:"Next: <b>Future.</b> Plans, decisions and predictions: <i>I'll call you. I'm going to study tonight.</i>"}
  ]
});
