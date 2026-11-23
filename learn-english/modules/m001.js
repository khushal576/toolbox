registerModule({
  id: 1,
  title: "The sentence skeleton",
  sub: "am / is / are",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 1 · Start here", title:"A tiny puzzle",
     html:`<p>You feel tired. You want to say it. Four people try. <b>Only one</b> sounds natural to an English speaker.</p>
           <p>Don't worry about the rule. Just trust your ear. It takes 10 seconds.</p>`},
    {k:"mcq", q:"Which one sounds natural?",
     o:["I tired.","Me tired.","Tired I am.","I am tired."], a:3,
     w:["Close, but something is missing. A small word is hiding between \"I\" and \"tired\".",
        "That is how a baby talks. \"Me\" cannot be the one doing the feeling.",
        "That's how Yoda talks. English word order is strict: who first, then the glue word.",
        "Yes! The little word <b>am</b> is the secret of this whole module."]},
    {k:"card", ref:"The skeleton", tag:"The idea · 1 of 5", title:"Every sentence has a skeleton",
     html:`<p>An English sentence is built from three parts:</p>
           <div class="frame"><span class="who">WHO</span><span class="glue">GLUE</span><span class="rest">REST</span></div>
           <div class="frame"><span class="who">I</span><span class="glue">am</span><span class="rest">tired.</span></div>
           <div class="frame"><span class="who">She</span><span class="glue">is</span><span class="rest">at home.</span></div>
           <div class="frame"><span class="who">They</span><span class="glue">are</span><span class="rest">my friends.</span></div>
           <p><b>WHO</b> is who you talk about. <b>GLUE</b> joins it to the information. <b>REST</b> says how they feel, where they are, or what they are.</p>
           <p>Change the WHO and the REST as much as you like. The skeleton stays the same. That is how you build <i>any</i> sentence without memorizing it.</p>`},
    {k:"order", q:"Build it: tap the words in the right order.", words:["I","am","happy"], a:"I am happy.",
     w:"WHO (I) + GLUE (am) + REST (happy). That's the skeleton."},
    {k:"order", q:"Build it.", words:["She","is","at","home"], a:"She is at home.",
     w:"Same skeleton. Only the WHO and the REST changed."},
    {k:"order", q:"One more.", words:["They","are","my","friends"], a:"They are my friends.",
     w:"Three sentences built. You have already used the pattern that does about a third of everyday English."},
    {k:"card", ref:"The three forms", tag:"The idea · 2 of 5", title:"The glue changes shape: am, is, are",
     html:`<p>The glue word has three shapes. You pick one by looking at the WHO:</p>
           <table>
             <tr><th>WHO</th><th>GLUE</th><th>Example</th></tr>
             <tr><td><b>I</b></td><td><b>am</b></td><td>I am ready.</td></tr>
             <tr><td><b>he / she / it</b><br><span class="sub">or any <u>one</u> person or thing</span></td><td><b>is</b></td><td>My brother is tall.<br>The phone is new.</td></tr>
             <tr><td><b>you / we / they</b><br><span class="sub">or <u>more than one</u></span></td><td><b>are</b></td><td>You are right.<br>The keys are here.</td></tr>
           </table>
           <p>Easy way to remember: <b>only "I" gets <i>am</i></b>. Exactly one other thing gets <i>is</i>. Everything else, including <b>you</b>, gets <i>are</i>.</p>
           <p class="sub">Not sure which to use? Count the WHO. "My parents" is two people, so <b>are</b>. "My mother" is one, so <b>is</b>.</p>`},
    {k:"card", ref:"Why you can't skip it", tag:"The idea · 3 of 5", title:"Why English will not let you skip the glue",
     html:`<p>Some languages say "She happy" and everybody understands. English will understand you too, but it sounds like a sentence with a missing leg. Native speakers hear the gap right away.</p>
           <div class="wrong">She happy.</div><div class="right">She is happy.</div>
           <div class="wrong">We at home.</div><div class="right">We are at home.</div>
           <div class="wrong">The weather nice today.</div><div class="right">The weather is nice today.</div>
           <p><b>Rule of thumb:</b> before you say the REST, check you said a glue word. If the REST is a feeling, a place, or a description, the glue is <i>am / is / are</i>.</p>`},
    {k:"card", ref:"Shrinking", tag:"The idea · 4 of 5", title:"How people really talk: shrinking",
     html:`<p>In real speech, the WHO and the glue squeeze together:</p>
           <table>
             <tr><td>I am</td><td><b>I'm</b></td><td>I'm tired.</td></tr>
             <tr><td>she is</td><td><b>she's</b></td><td>She's at home.</td></tr>
             <tr><td>they are</td><td><b>they're</b></td><td>They're my friends.</td></tr>
             <tr><td>we are</td><td><b>we're</b></td><td>We're late.</td></tr>
           </table>
           <p>Use the short form when you speak. It sounds smooth, not lazy.</p>
           <div class="fb note"><b>One exception:</b> never shrink at the very end of an answer. Say <b>"Yes, I am."</b> Not "Yes, I'm."</div>`},
    {k:"card", ref:"No and questions", tag:"The idea · 5 of 5", title:"Saying NO and asking questions",
     html:`<p><b>To say no, add <i>not</i> after the glue:</b></p>
           <div class="right">I am not hungry. &nbsp;→ <b>I'm not hungry.</b></div>
           <div class="right">She is not here. → <b>She isn't here.</b></div>
           <div class="right">They are not late. → <b>They aren't late.</b></div>
           <p class="sub">There is no "amn't". For "I", always say <b>I'm not</b>.</p>
           <p><b>To ask a question, swap the first two parts.</b> The glue jumps to the front:</p>
           <div class="frame"><span class="who">You</span><span class="glue">are</span><span class="rest">ready.</span></div>
           <div class="frame"><span class="glue">Are</span><span class="who">you</span><span class="rest">ready?</span></div>
           <p>Same idea with a question word first: <b>Where are you from? &nbsp; How is your mother? &nbsp; Who is that?</b></p>`},
    {k:"mcq", q:"My sister ___ very kind.", o:["am","is","are"], a:1,
     w:["\"am\" belongs only to \"I\".","Yes. \"My sister\" is one person, so <b>is</b>.","\"are\" is for more than one (or \"you\"). One sister means <b>is</b>."]},
    {k:"mcq", q:"We ___ ready.", o:["is","am","are"], a:2,
     w:["\"is\" is for one person or thing. \"We\" means more than one.","\"am\" belongs only to \"I\".","Yes. \"We\" goes with <b>are</b>."]},
    {k:"mcq", q:"The keys ___ on the table.", o:["is","are","am"], a:1,
     w:["Look at the WHO: \"keys\" is more than one, so <b>is</b> is wrong.","Yes. \"The keys\" is plural, so <b>are</b>.","\"am\" belongs only to \"I\"."]},
    {k:"type", q:"My parents ___ at home. <span class='sub'>(am / is / are)</span>", a:["are"],
     w:"\"My parents\" is two people, so the glue is <b>are</b>."},
    {k:"mcq", q:"Which sentence is correct?", o:["He are my brother.","He am my brother.","He is my brother."], a:2,
     w:["\"He\" is one person, so it needs <b>is</b>.","\"am\" belongs only to \"I\".","Yes. He = one person → <b>is</b>."]},
    {k:"order", q:"Make it a question.", words:["Are","you","ready"], a:"Are you ready?",
     w:"The glue jumps to the front: You are ready → <b>Are you</b> ready?"},
    {k:"type", q:"___ she your teacher? <span class='sub'>(Is / Are)</span>", a:["is"],
     w:"\"She\" is one person, and the glue goes to the front: <b>Is</b> she your teacher?"},
    {k:"mcq", q:"Are you tired? — Yes, ___", o:["I'm.","I am.","I are."], a:1,
     w:["Never shrink at the end of an answer. It sounds unfinished.","Yes. At the end of an answer, say it in full: <b>Yes, I am.</b>","\"I are\" breaks the rule: only \"I\" goes with <b>am</b>."]},
    {k:"order", q:"Say it the way people really say it.", words:["We're","not","late"], a:"We're not late.",
     w:"Shrunk form, then <b>not</b>: <b>We're not late.</b> Natural and smooth."},
    {k:"mcq", q:"He ___ at work today.", o:["amn't","aren't","isn't"], a:2,
     w:["There is no \"amn't\" in English, and it isn't for \"he\" either.","\"aren't\" goes with you/we/they.","Yes. \"He\" is one person: <b>isn't</b>."]},
    {k:"build", intro:"Now the best part. Make sentences about <b>your own life</b>. Type each one, then say it out loud. Your mouth needs practice, not just your eyes.",
     items:[
      {p:"Say how you feel right now.", frame:"I am ______.", ex:"I'm a bit tired, but happy.", must:/\b(i am|i'm)\b/i, ok:"You used the skeleton: I + am + REST.", tip:"Start with <b>I am</b> or <b>I'm</b>, then say the feeling."},
      {p:"Describe one person in your family.", frame:"My ______ is ______.", ex:"My mother is very kind.", must:/\b(is|'s)\b/i, ok:"One person, so <b>is</b>. Correct.", tip:"One person → <b>is</b>. Try: My brother is ..."},
      {p:"Say where you are right now.", frame:"I am at / in ______.", ex:"I'm at home, in my room.", must:/\b(i am|i'm)\b.*\b(at|in|on)\b/i, ok:"Good: I'm + place.", tip:"Try: I am at home / I'm in my room."},
      {p:"Say something you are NOT.", frame:"I am not ______.", ex:"I'm not hungry.", must:/\b(i am not|i'm not)\b/i, ok:"Perfect negative.", tip:"Use <b>I'm not</b> (never \"amn't\")."},
      {p:"Ask me a question about me, starting with Are / Is.", frame:"Are you ______?", ex:"Are you a teacher?", must:/^\s*(are|is)\b/i, ok:"The glue jumped to the front. That's a real question.", tip:"Start with the glue: <b>Are you ...?</b>"}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 mistakes almost every learner makes",
     items:[
      {bad:"She happy.", good:"She is happy.", fix:"Skipping the glue. Before the REST, say am / is / are."},
      {bad:"I is tired. / He are here.", good:"I am tired. / He is here.", fix:"Look at the WHO. I → am, one → is, you/we/they/many → are."},
      {bad:"I am agree.", good:"I agree.", fix:"\"Agree\" is already an action word, so it doesn't need <i>am</i>. Use am/is/are before feelings, places, descriptions. (More in Module 2.)"},
      {bad:"I have 25 years.", good:"I am 25 years old. / I'm 25.", fix:"In English, age uses <b>be</b>, not <i>have</i>."},
      {bad:"Where you are from?", good:"Where are you from?", fix:"In questions the glue comes right after the question word: Where <b>are</b> you from?"}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: The Airport Officer", pass:0.8,
     intro:"A strict but friendly airport officer asks you 10 questions. You need 8 right to get through. You can retry, and if you miss, I'll show you exactly where to look.",
     qs:[
      {k:"mcq", ref:"The three forms", q:"Which is correct?", o:["My friends is late.","My friends am late.","My friends are late."], a:2, w:["\"Friends\" is plural, so it needs <b>are</b>.","\"am\" belongs only to \"I\".","Yes: plural → <b>are</b>."]},
      {k:"order", ref:"Shrinking", q:"Build it (short form).", words:["I'm","not","ready"], a:"I'm not ready.", w:"I'm + not + ready."},
      {k:"type", ref:"The three forms", q:"She ___ my best friend. <span class='sub'>(am / is / are)</span>", a:["is"], w:"One person → <b>is</b>."},
      {k:"mcq", ref:"No and questions", q:"Which question is correct?", o:["Where you are from?","Where are you from?","Where from you are?"], a:1, w:["The glue must come right after the question word.","Yes: <b>Where are you from?</b>","Word order is strict in English."]},
      {k:"mcq", ref:"Shrinking", q:"Is he at home? — Yes, ___", o:["he's.","he is.","he are."], a:1, w:["Don't shrink at the end of an answer.","Yes: <b>Yes, he is.</b>","One person → <b>is</b>."]},
      {k:"order", ref:"No and questions", q:"Make a question.", words:["Is","your","phone","new"], a:"Is your phone new?", w:"The glue goes first: <b>Is</b> your phone new?"},
      {k:"type", ref:"The three forms", q:"I ___ not hungry. <span class='sub'>(am / is / are)</span>", a:["am"], w:"\"I\" always takes <b>am</b>."},
      {k:"mcq", ref:"Why you can't skip it", q:"What is missing? <i>The weather nice today.</i>", o:["Nothing, it's fine.","The glue word: The weather <b>is</b> nice today.","An extra word at the end."], a:1, w:["It is understandable, but it sounds broken.","Yes: the glue <b>is</b>.","The problem is in the middle, not the end."]},
      {k:"mcq", ref:"Mistake trap", q:"Which sentence is wrong?", o:["I'm 25 years old.","I have 25 years.","She is 30."], a:1, w:["Correct English.","Yes, this is the wrong one: age uses <b>be</b> (I am 25).","Correct English."]},
      {k:"mcq", ref:"Why you can't skip it", q:"Which sentence is correct?", o:["We at the station.","We are at the station.","We is at the station."], a:1, w:["Missing the glue.","Yes: We <b>are</b> at the station.","\"We\" needs <b>are</b>, not \"is\"."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Say how you feel, who someone is and where things are: <i>I'm tired. My brother is tall. The keys are on the table.</i>",
          "Say no and ask quick questions: <i>She isn't here. Are you ready? Where are you from?</i>",
          "Hear a sentence with a missing glue word and fix it instantly."],
     teaser:"Next: <b>Present simple.</b> Your first real actions: <i>I work, she works, we don't…</i> Talk about habits and routines."}
  ]
});
