registerModule({
  id: 9,
  title: "Nouns and articles",
  sub: "a, an, the, or nothing",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 9 · Start here", title:"The invisible words",
     html:`<p>Hindi has no <i>a</i>, <i>an</i> or <i>the</i>. So when you say "I am engineer", it feels complete. To an English ear, it sounds like a sentence with a tooth missing.</p>
           <p>These tiny words are not decoration. They tell the listener <b>which one</b> you mean. Let's test your ear first: there is a trick hiding in this one.</p>`},
    {k:"mcq", q:"She is ___ honest person.",
     o:["a","the","(nothing)","an"], a:3,
     w:["Close, but <i>honest</i> starts with a silent <b>h</b>. You say \"onest\".","<i>The</i> means a specific person we both know.","A singular person needs an article.","Yes! <b>an</b> goes before a <i>vowel sound</i>, and the h in <i>honest</i> is silent."]},
    {k:"card", ref:"Countable or not", tag:"The idea · 1 of 5", title:"Step 1: can you count it?",
     html:`<p>Nouns are <b>countable</b> (you can say 1, 2, 3) or <b>uncountable</b> (you can't).</p>
           <table>
             <tr><th>countable</th><th>uncountable</th></tr>
             <tr><td>an apple, two apples<br>a chair, three chairs<br>a friend, five friends</td><td>water, rice, milk, tea<br>money, time, music<br><b>advice, information, news, furniture, luggage, homework</b></td></tr>
           </table>
           <p><b>Uncountable nouns have no plural and no a/an.</b> Use <i>some</i> or a measure word:</p>
           <div class="right">some advice &nbsp; some information &nbsp; a piece of news &nbsp; a glass of water</div>
           <div class="wrong">an advice &nbsp; informations &nbsp; furnitures &nbsp; a luggage</div>
           <p class="sub">Hindi counts some of these as plural (जानकारी, सलाह). English doesn't. Memorize the list above.</p>`},
    {k:"card", ref:"a / an", tag:"The idea · 2 of 5", title:"a / an: one, any, not yet known",
     html:`<p>Use <b>a / an</b> with <b>one countable</b> thing when:</p>
           <div class="right">it is <b>new</b> to the listener: <i>I saw a dog.</i></div>
           <div class="right">you say what someone <b>is</b> (job, type): <i>She is a doctor. He is an engineer.</i></div>
           <div class="right">you mean <b>any one</b>: <i>I need a pen.</i></div>
           <p><b>Which one? Listen to the sound, not the spelling:</b></p>
           <table>
             <tr><th>starts with a…</th><th>use</th><th>examples</th></tr>
             <tr><td>consonant <b>sound</b></td><td>a</td><td>a book, a <b>u</b>niversity (sounds "yoo"), a one-day trip</td></tr>
             <tr><td>vowel <b>sound</b></td><td>an</td><td>an apple, an <b>h</b>our (silent h), an honest man, an MBA</td></tr>
           </table>`},
    {k:"order", q:"Translate to English.", hi:"मैं एक शिक्षक हूँ।", words:["I","am","a","teacher"], a:"I am a teacher.",
     w:"A job needs <b>a/an</b>. Module 1's glue + <b>a</b> + noun."},
    {k:"card", ref:"the", tag:"The idea · 3 of 5", title:"the: which one? You know and I know",
     html:`<p>Use <b>the</b> when the listener knows <b>exactly which one</b>:</p>
           <div class="right"><b>Second mention:</b> I bought <u>a</u> shirt. <b>The</b> shirt is red.</div>
           <div class="right"><b>Only one exists:</b> the sun, the moon, the sky, the Earth, the internet</div>
           <div class="right"><b>Clear from the situation:</b> Please close <b>the</b> door. (the one in this room)</div>
           <div class="right"><b>Made specific:</b> The book <i>on the table</i> is mine.</div>
           <div class="right"><b>Superlatives:</b> the best, the tallest, the first</div>
           <p class="sub">Test: if the listener can ask "which one?" and the answer is obvious, use <i>the</i>. If they'd ask "which one?" and you'd say "any", use <i>a</i>.</p>`},
    {k:"card", ref:"No article", tag:"The idea · 4 of 5", title:"No article at all (very common)",
     html:`<p>Use <b>nothing</b> when you talk about things <b>in general</b>:</p>
           <div class="right">I like <b>tea</b>. &nbsp; <b>Dogs</b> are loyal. &nbsp; <b>Music</b> relaxes me. &nbsp; <b>Honesty</b> matters.</div>
           <p>Also no article for: <b>languages</b> (I speak Hindi), <b>meals</b> (have lunch), <b>sports</b> (play cricket), <b>days/months</b> (on Monday), and places used for their <b>purpose</b>:</p>
           <div class="right">go to <b>school</b> (study) · go to <b>work</b> · be in <b>hospital</b> (ill) · go <b>home</b> · go to <b>bed</b></div>
           <div class="wrong">I like the music. (meaning music in general)</div>
           <p class="sub">Compare: <i>I like music.</i> (all music) vs <i>I like the music in this film.</i> (that specific music).</p>`},
    {k:"card", ref:"Plurals and amounts", tag:"The idea · 5 of 5", title:"Plurals and how much",
     html:`<table>
             <tr><th>rule</th><th>example</th></tr>
             <tr><td>most: + s</td><td>book → books</td></tr>
             <tr><td>s, sh, ch, x: + es</td><td>bus → buses, watch → watches</td></tr>
             <tr><td>consonant + y: → ies</td><td>baby → babies</td></tr>
             <tr><td>f/fe → ves</td><td>knife → knives, leaf → leaves</td></tr>
             <tr><td>irregular</td><td>man → men, woman → women, child → children, foot → feet, person → people</td></tr>
           </table>
           <table>
             <tr><th></th><th>countable</th><th>uncountable</th></tr>
             <tr><td>a lot of</td><td>✓</td><td>✓</td></tr>
             <tr><td>many / a few / few</td><td>✓</td><td>✗</td></tr>
             <tr><td>much / a little / little</td><td>✗</td><td>✓</td></tr>
             <tr><td>some (yes) / any (no, ?)</td><td>✓</td><td>✓</td></tr>
           </table>
           <div class="right">How <b>many</b> people? &nbsp; How <b>much</b> money? &nbsp; I don't have <b>any</b> time. &nbsp; There are <b>a few</b> chairs.</div>
           <p class="sub"><b>a few / a little</b> = some (positive). <b>few / little</b> = almost none (negative).</p>`},
    {k:"mcq", q:"I need ___ advice.", o:["an","some","a"], a:1,
     w:["<i>Advice</i> is uncountable. No a/an.","Yes. Uncountable → <b>some advice</b>.","No a/an before an uncountable noun."]},
    {k:"mcq", q:"She is ___ engineer.", o:["a","an","the"], a:1,
     w:["<i>Engineer</i> starts with a vowel sound.","Yes. Job + vowel sound → <b>an engineer</b>.","<i>The</i> would mean a specific engineer we both know."]},
    {k:"mcq", q:"He studies at ___ university.", o:["an","the","a"], a:2,
     w:["Listen: <i>university</i> starts with a \"y\" sound (yoo).","<i>The</i> means a specific one we both know.","Yes. Consonant sound → <b>a university</b>."]},
    {k:"mcq", q:"Look at ___ moon! It's so bright.", o:["a","the","(nothing)"], a:1,
     w:["There's only one moon in the sky.","Yes. Only one exists → <b>the moon</b>.","A singular countable noun needs an article."]},
    {k:"type", q:"I ate ___ orange. <span class='sub'>(a / an)</span>", a:["an"], w:"<i>Orange</i> starts with a vowel sound → <b>an</b>."},
    {k:"order", q:"Translate to English.", hi:"मुझे चाय पसंद है।", words:["I","like","tea"], a:"I like tea.",
     w:"Tea in general → <b>no article</b>."},
    {k:"mcq", q:"I like ___ music.", o:["a","the","(nothing)"], a:2,
     w:["<i>Music</i> is uncountable: no a/an.","<i>The</i> is for specific music. Here it's general.","Yes. In general → <b>no article</b>."]},
    {k:"mcq", q:"There isn't ___ milk in the fridge.", o:["many","much","a few"], a:1,
     w:["<i>Many</i> is for countable nouns.","Yes. Uncountable → <b>much</b>.","<i>A few</i> is for countable nouns."]},
    {k:"mcq", q:"How ___ people are there in the room?", o:["many","much","a lot"], a:0,
     w:["Yes. <i>People</i> is countable → <b>many</b>.","<i>Much</i> is for uncountable nouns.","<i>How a lot</i> isn't used."]},
    {k:"type", q:"one child, two ___", a:["children"], w:"Irregular plural: child → <b>children</b>."},
    {k:"order", q:"Translate to English.", hi:"मुझे कुछ सलाह चाहिए।", words:["I","need","some","advice"], a:"I need some advice.",
     w:"<i>Advice</i> is uncountable → <b>some advice</b>."},
    {k:"mcq", q:"Which is correct?", o:["I have two bag.","I have two bags.","I have two bagses."], a:1,
     w:["After <i>two</i>, the noun must be plural.","Yes. Plural: bag → <b>bags</b>.","Just add <b>s</b>."]},
    {k:"order", q:"Translate to English.", hi:"आसमान में चाँद बहुत सुंदर है।", words:["The","moon","is","very","beautiful","in","the","sky"], a:"The moon is very beautiful in the sky.",
     w:"Only one moon, only one sky → <b>the</b> both times."},
    {k:"mcq", q:"Which is correct?", o:["She gave me an informations.","She gave me some information.","She gave me informations."], a:1,
     w:["<i>Information</i> is uncountable: no <i>an</i>, no plural.","Yes. <b>some information</b>.","<i>Information</i> has no plural."]},
    {k:"mcq", q:"I go to ___ school by bus. (I am a student.)", o:["the","a","(nothing)"], a:2,
     w:["<i>The school</i> would mean a specific building.","<i>A school</i> would be any school building.","Yes. A place used for its purpose → <b>no article</b>."]},
    {k:"type", q:"Translate to English.", hi:"मेरे पास दो भाई हैं।", a:["I have two brothers."], w:"After <i>two</i>, a plural noun: <b>brothers</b>."},
    {k:"mcq", q:"Revision from Module 8: ___ I have a glass of water, please?", o:["Could","Do","Am"], a:0,
     w:["Yes. A polite request: <b>Could I have…?</b>","<i>Do I have</i> asks something else.","<i>Am I have</i> is wrong."]},
    {k:"build", intro:"Your turn. Real sentences about <b>you</b>. Type each one and say it out loud.",
     items:[
      {p:"Tell me your job or what you study.", frame:"I am a / an ______.", ex:"I am a student. / I am an accountant.", must:/\b(i am|i'm)\s+(a|an|the)\s+\w+/i, ok:"A job needs <b>a / an</b>. Right.", tip:"<b>I am a / an</b> + your job. Check the sound: an engineer, a teacher."},
      {p:"Say what you have in your bag.", frame:"I have a ______, two ______ and some ______.", ex:"I have a bottle, two pens and some papers.", must:/\b(a|an|some|two|three|four|\d)\b/i, ok:"You counted and used <b>some</b> for the rest.", tip:"Use <b>a/an</b>, a number + plural, and <b>some</b>."},
      {p:"Say something you like, in general.", frame:"I like ______.", ex:"I like music and spicy food.", must:/\bi like\b/i, ok:"In general → no article. Perfect.", tip:"<b>I like</b> + plural or uncountable noun. No <i>the</i>."},
      {p:"Say something unique in the world.", frame:"The ______ is ______.", ex:"The sun is very hot today.", must:/\bthe\b/i, ok:"Only one → <b>the</b>.", tip:"Things that exist once: the sun, the moon, the sky."},
      {p:"Tell me something you ate today: first mention, then specific.", frame:"I ate a ______. The ______ was ______.", ex:"I ate a mango. The mango was very sweet.", must:/\b(a|an)\b.*\bthe\b/i, ok:"First mention <b>a</b>, then <b>the</b>. Exactly right.", tip:"<b>I ate a ... The ... was ...</b>"}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"I am engineer.", good:"I am an engineer.", fix:"Jobs and types need <b>a / an</b>."},
      {bad:"I need an advice. / some informations.", good:"I need some advice. / some information.", fix:"Uncountable nouns: no a/an, no plural. (advice, information, news, furniture, luggage, homework)"},
      {bad:"I like the music. (in general)", good:"I like music.", fix:"General things take no article."},
      {bad:"She is a honest woman.", good:"She is an honest woman.", fix:"Go by the sound: <i>honest</i> starts with an \"o\" sound."},
      {bad:"I have two sister.", good:"I have two sisters.", fix:"After a number above one, the noun is plural."}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: The Shopkeeper", pass:0.8,
     intro:"A shopkeeper tests your small words. This also revisits Modules 1 to 8. You need 8 of 10.",
     qs:[
      {k:"mcq", ref:"a / an", q:"He is ___ university student.", o:["a","an","the"], a:0, w:["Yes: <i>university</i> starts with a \"y\" sound → <b>a</b>.","<i>An</i> is for vowel sounds. Say it aloud: \"yoo-ni…\".","<i>The</i> means a specific one."]},
      {k:"mcq", ref:"Countable or not", q:"I need some ___.", o:["advices","advice","an advice"], a:1, w:["<i>Advice</i> has no plural.","Yes: uncountable → <b>some advice</b>.","No <i>an</i> before an uncountable noun."]},
      {k:"mcq", ref:"the", q:"Look at ___ sun!", o:["a","an","the"], a:2, w:["There is only one sun.","<i>An</i> is also wrong: only one sun exists.","Yes: <b>the sun</b>."]},
      {k:"type", ref:"Plurals and amounts", q:"one man, two ___", a:["men"], w:"Irregular plural: man → <b>men</b>."},
      {k:"mcq", ref:"No article", q:"I love ___ coffee.", o:["the","a","(no article)"], a:2, w:["<i>The</i> is for a specific coffee.","<i>Coffee</i> in general is uncountable.","Yes: in general → <b>no article</b>."]},
      {k:"mcq", ref:"Plurals and amounts", q:"How ___ water do you drink in a day?", o:["many","much","few"], a:1, w:["<i>Water</i> is uncountable.","Yes: uncountable → <b>much</b>.","<i>Few</i> isn't used in this question."]},
      {k:"order", ref:"a / an", q:"Translate to English.", hi:"मैं एक डॉक्टर हूँ।", words:["I","am","a","doctor"], a:"I am a doctor.", w:"Job → <b>a</b>."},
      {k:"type", ref:"No article", q:"Translate to English.", hi:"मुझे संगीत पसंद है।", a:["I like music."], w:"In general → no article."},
      {k:"mcq", ref:"Plurals and amounts", q:"There are ___ chairs in the room, so we can sit.", o:["much","a few","a little"], a:1, w:["<i>Much</i> is for uncountable nouns.","Yes: countable → <b>a few</b>.","<i>A little</i> is for uncountable nouns."]},
      {k:"mcq", ref:"a / an", q:"Revision from Module 8: Could I have ___ glass of water, please?", o:["a","an","some"], a:0, w:["Yes: <b>a glass</b>, one countable thing.","<i>Glass</i> starts with a consonant sound.","<i>Some glass</i> would mean the material."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Name jobs and things naturally: <i>I am an engineer. She is a doctor. I need a pen.</i>",
          "Tell the difference between general and specific: <i>I like music. I like the music in this film. Close the door.</i>",
          "Count and measure correctly: <i>some advice, a few chairs, how much money, two children.</i>"],
     teaser:"Next: <b>Prepositions.</b> In, on, at and the small words that glue time, place and verbs together."}
  ]
});
