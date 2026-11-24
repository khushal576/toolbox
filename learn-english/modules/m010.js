registerModule({
  id: 10,
  title: "in / on / at and prepositions",
  sub: "time, place, movement and fixed pairs",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 10 · Start here", title:"Tiny words, huge difference",
     html:`<p>In Hindi, one word (<i>में, पर, को, से</i>) does many jobs. In English you must choose: <b>in, on, at, to, for, by…</b> Choose wrong and the sentence still gets understood, but it sounds off.</p>
           <p>Good news: it is mostly a pattern, not a lottery. Let's start with the one almost everyone gets wrong.</p>`},
    {k:"mcq", q:"The meeting is ___ Monday ___ 5 pm.",
     o:["in / at","on / at","at / on","on / in"], a:1,
     w:["<i>In Monday</i> is not used. Days take <b>on</b>.","Yes! <b>on</b> a day, <b>at</b> a clock time.","The two are swapped.","<i>In 5 pm</i> is not used. Clock times take <b>at</b>."]},
    {k:"card", ref:"Time: in / on / at", tag:"The idea · 1 of 5", title:"Time: the funnel (at → on → in)",
     html:`<p>Think of a funnel. The <b>smaller</b> the time, the smaller the word:</p>
           <table>
             <tr><th>word</th><th>for</th><th>examples</th></tr>
             <tr><td><b>at</b></td><td>an exact point</td><td>at 5 pm, at noon, at night, at the weekend, at Diwali</td></tr>
             <tr><td><b>on</b></td><td>days and dates</td><td>on Monday, on 15 August, on my birthday, on Friday morning</td></tr>
             <tr><td><b>in</b></td><td>long periods</td><td>in June, in 2020, in summer, in the morning / afternoon / evening, in an hour</td></tr>
           </table>
           <p class="sub">Careful: <i>in the morning</i> but <i>on Monday morning</i>. And <i>at night</i> (not in the night).</p>
           <p>No preposition with: <i>this, next, last, every, tomorrow, yesterday</i>.</p>
           <div class="right">See you <b>next</b> week. &nbsp; I go there <b>every</b> day.</div><div class="wrong">See you in next week.</div>`},
    {k:"order", q:"Translate to English.", hi:"बैठक शाम पाँच बजे है।", words:["The","meeting","is","at","five","in","the","evening"], a:"The meeting is at five in the evening.",
     w:"<b>at</b> a clock time, <b>in</b> the evening."},
    {k:"card", ref:"Place: in / on / at", tag:"The idea · 2 of 5", title:"Place: inside, surface, point",
     html:`<table>
             <tr><th>word</th><th>means</th><th>examples</th></tr>
             <tr><td><b>in</b></td><td>inside, a space or area</td><td>in the room, in Delhi, in India, in a car, in the box, in the garden</td></tr>
             <tr><td><b>on</b></td><td>on a surface or line</td><td>on the table, on the wall, on the floor, on the bus / train / plane, on the second floor</td></tr>
             <tr><td><b>at</b></td><td>a point, a place for its purpose</td><td>at the station, at home, at work, at the door, at school, at a party</td></tr>
           </table>
           <p><b>Cars vs buses:</b> you get <b>in</b> a car or taxi (small), <b>on</b> a bus, train or plane (big, you can walk inside).</p>
           <div class="right">I live <b>in</b> Pune. &nbsp; The keys are <b>on</b> the table. &nbsp; I'll wait <b>at</b> the station.</div>
           <div class="wrong">I live at Pune. &nbsp; The keys are in the table.</div>`},
    {k:"card", ref:"Movement: to / from / into", tag:"The idea · 3 of 5", title:"Movement: to, from, into, out of",
     html:`<p><b>to</b> = destination. <b>from</b> = start. <b>into / out of</b> = going inside / leaving a space. <b>on / off</b> = a bus, train or plane.</p>
           <div class="right">I go <b>to</b> school. &nbsp; I come <b>from</b> Pune. &nbsp; She walked <b>into</b> the room.</div>
           <div class="right">I got <b>on</b> the bus. &nbsp; I got <b>off</b> at the station. &nbsp; He got <b>in(to)</b> the car and got <b>out of</b> it later.</div>
           <p><b>Arrive:</b> <i>arrive <b>in</b> a city or country</i> (arrive in Delhi), <i>arrive <b>at</b> a place or point</i> (arrive at the airport). Not <i>arrive to</i>.</p>
           <p><b>go home</b> (no to), but <b>go to</b> the market.</p>
           <div class="wrong">I arrived to Delhi. &nbsp; I go to home.</div>`},
    {k:"card", ref:"for / since / by / until", tag:"The idea · 4 of 5", title:"for, since, during, by, until",
     html:`<table>
             <tr><th>word</th><th>means</th><th>example</th></tr>
             <tr><td><b>for</b></td><td>how long</td><td>I waited <b>for</b> two hours. (Module 5)</td></tr>
             <tr><td><b>since</b></td><td>from a start point till now</td><td>I've lived here <b>since</b> 2018.</td></tr>
             <tr><td><b>during</b></td><td>inside a period (+ noun)</td><td>I slept <b>during</b> the film.</td></tr>
             <tr><td><b>by</b></td><td>not later than (deadline)</td><td>Finish it <b>by</b> Friday.</td></tr>
             <tr><td><b>until</b></td><td>continuing up to a point</td><td>I'll wait <b>until</b> six.</td></tr>
           </table>
           <p class="sub"><b>by</b> = the deadline (you can finish earlier). <b>until</b> = the action continues the whole time.</p>`},
    {k:"card", ref:"Fixed pairs", tag:"The idea · 5 of 5", title:"Verbs and adjectives with fixed prepositions",
     html:`<p>Some words come glued to a preposition. Don't translate from Hindi, learn them as pairs:</p>
           <table>
             <tr><td>wait <b>for</b></td><td>listen <b>to</b></td><td>look <b>at</b> / look <b>for</b> (search)</td></tr>
             <tr><td>depend <b>on</b></td><td>good <b>at</b> / bad <b>at</b></td><td>interested <b>in</b></td></tr>
             <tr><td>afraid <b>of</b></td><td>different <b>from</b></td><td>happy <b>with</b> / angry <b>with</b></td></tr>
             <tr><td>married <b>to</b></td><td>pay <b>for</b></td><td>talk <b>about</b>, but <b>discuss</b> (no preposition)</td></tr>
           </table>
           <div class="wrong">I am waiting you. &nbsp; We discussed about it. &nbsp; I'm good in English.</div>
           <div class="right">I am waiting <b>for</b> you. &nbsp; We discussed it. &nbsp; I'm good <b>at</b> English.</div>`},
    {k:"mcq", q:"The meeting is ___ Monday.", o:["in","on","at"], a:1,
     w:["<i>In</i> is for months and years.","Yes. Days → <b>on</b>.","<i>At</i> is for clock times."]},
    {k:"mcq", q:"I wake up ___ six o'clock.", o:["on","in","at"], a:2,
     w:["<i>On</i> is for days.","<i>In</i> is for longer periods.","Yes. A clock time → <b>at</b>."]},
    {k:"mcq", q:"My birthday is ___ June.", o:["at","in","on"], a:1,
     w:["<i>At</i> is for exact points.","Yes. Months → <b>in</b>.","<i>On</i> is for days and dates (on 5 June)."]},
    {k:"mcq", q:"The keys are ___ the table.", o:["in","at","on"], a:2,
     w:["<i>In</i> would mean inside it.","<i>At</i> is for a point/place.","Yes. A surface → <b>on</b>."]},
    {k:"mcq", q:"She lives ___ Pune.", o:["at","in","on"], a:1,
     w:["<i>At</i> is for a small point.","Yes. A city → <b>in</b>.","<i>On</i> is for surfaces."]},
    {k:"mcq", q:"We arrived ___ the airport at six.", o:["in","to","at"], a:2,
     w:["<i>Arrive in</i> is for a city or country.","Never <i>arrive to</i>.","Yes. A specific place → <b>arrive at</b>."]},
    {k:"order", q:"Translate to English.", hi:"मैं सोमवार को दफ़्तर जाता हूँ।", words:["I","go","to","the","office","on","Monday"], a:"I go to the office on Monday.", alt:["On Monday I go to the office."],
     w:"<b>on</b> + a day. A habit → Module 2's simple present."},
    {k:"mcq", q:"I have been waiting ___ two hours.", o:["since","for","during"], a:1,
     w:["<i>Since</i> needs a starting point (since two o'clock).","Yes. A length of time → <b>for</b> (Module 5).","<i>During</i> goes with a noun, e.g. during the film."]},
    {k:"mcq", q:"Please finish the work ___ Friday (not later than).", o:["by","until","at"], a:0,
     w:["Yes. A deadline → <b>by</b>.","<i>Until</i> means you keep doing it up to Friday.","<i>At</i> is for exact points."]},
    {k:"mcq", q:"I'll wait here ___ you come back.", o:["by","until","for"], a:1,
     w:["<i>By</i> is a deadline.","Yes. Continuing up to that point → <b>until</b>.","<i>For</i> needs a length of time."]},
    {k:"type", q:"I'm interested ___ music. <span class='sub'>(one word)</span>", a:["in"], w:"<b>interested in</b>. A fixed pair."},
    {k:"order", q:"Translate to English.", hi:"मैं तुम्हारा इंतज़ार कर रहा हूँ।", words:["I","am","waiting","for","you"], a:"I am waiting for you.",
     w:"<b>wait for</b>, never <i>wait you</i>. Module 3's -ing + a fixed pair."},
    {k:"mcq", q:"Which is correct?", o:["We discussed about the plan.","We discussed the plan.","We discussed on the plan."], a:1,
     w:["<i>Discuss</i> needs no preposition.","Yes. <b>discuss</b> + object, no preposition.","No preposition needed."]},
    {k:"type", q:"Translate to English.", hi:"वह गणित में अच्छी है।", a:["She is good at maths.","She is good at math.","She's good at maths.","She's good at math."], w:"<b>good at</b>. A fixed pair."},
    {k:"mcq", q:"She got ___ the bus at her stop.", o:["off","out of","from"], a:0,
     w:["Yes. Buses, trains, planes → <b>get on / get off</b>.","<i>Out of</i> is for cars and small spaces.","<i>From</i> doesn't fit here."]},
    {k:"order", q:"Translate to English.", hi:"वे बाग़ में खेल रहे हैं।", words:["They","are","playing","in","the","garden"], a:"They are playing in the garden.",
     w:"<b>in</b> a space. Module 3's glue + -ing."},
    {k:"build", intro:"Your turn. Real sentences about <b>your day and your place</b>. Type each one and say it out loud.",
     items:[
      {p:"Say when you wake up.", frame:"I wake up at ______.", ex:"I wake up at six in the morning.", must:/\bat\b/i, ok:"<b>at</b> + a clock time.", tip:"<b>at</b> + time: I wake up at six."},
      {p:"Say what you do on a certain day.", frame:"On ______ I ______.", ex:"On Sundays I visit my parents.", must:/\bon\b/i, ok:"<b>on</b> + a day.", tip:"<b>On Monday</b> / <b>On Sundays</b>..."},
      {p:"Say where you live (and work or study).", frame:"I live in ______ and I work / study at ______.", ex:"I live in Pune and I work at a bank.", must:/\b(live|stay)s?\b.*\bin\b/i, ok:"<b>in</b> a city.", tip:"<b>I live in</b> + a city."},
      {p:"Say how long you have been learning English.", frame:"I have been learning English for / since ______.", ex:"I have been learning English for three months.", must:/\b(for|since)\b/i, ok:"<b>for</b> or <b>since</b>. Right.", tip:"<b>for</b> a length, <b>since</b> a starting point."},
      {p:"Say something you are interested in or good at.", frame:"I am interested in ______. / I am good at ______.", ex:"I am good at cooking.", must:/\b(interested in|good at|bad at|afraid of|fond of)\b/i, ok:"A fixed pair. Correct.", tip:"<b>interested in</b>, <b>good at</b>, <b>afraid of</b>..."}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"I'll meet you in Monday.", good:"I'll meet you on Monday.", fix:"Days take <b>on</b>; months and years take <b>in</b>; clock times take <b>at</b>."},
      {bad:"I live at Pune.", good:"I live in Pune.", fix:"Cities and countries take <b>in</b>."},
      {bad:"I am waiting you.", good:"I am waiting for you.", fix:"<b>wait for</b>. Learn verb + preposition as one chunk."},
      {bad:"We discussed about it.", good:"We discussed it.", fix:"<b>discuss</b> takes no preposition."},
      {bad:"I'm good in English.", good:"I'm good at English.", fix:"<b>good at</b>, <b>interested in</b>, <b>afraid of</b>."}
     ]},
    {k:"boss", ref:"Boss", title:"Phase 2 review: The Final Gate", pass:0.8,
     intro:"This is the last gate of Phase 2. 12 questions on prepositions plus questions, modals and articles from Modules 7 to 9. You need 10 of 12 to earn your trophy.",
     qs:[
      {k:"mcq", ref:"Time: in / on / at", q:"The film starts ___ eight o'clock.", o:["on","in","at"], a:2, w:["<i>On</i> is for days.","<i>In</i> is for longer periods.","Yes: a clock time → <b>at</b>."]},
      {k:"mcq", ref:"Time: in / on / at", q:"We go to the beach ___ summer.", o:["at","on","in"], a:2, w:["<i>At</i> is for exact points.","<i>On</i> is for days.","Yes: seasons and months → <b>in</b>."]},
      {k:"mcq", ref:"Place: in / on / at", q:"My phone is ___ the table.", o:["in","on","at"], a:1, w:["<i>In</i> would mean inside.","Yes: a surface → <b>on</b>.","<i>At</i> is a point."]},
      {k:"mcq", ref:"Place: in / on / at", q:"He lives ___ Mumbai.", o:["at","on","in"], a:2, w:["<i>At</i> is for a small point.","<i>On</i> is for surfaces.","Yes: a city → <b>in</b>."]},
      {k:"mcq", ref:"Movement: to / from / into", q:"She got ___ the car and drove away.", o:["in","on","to"], a:0, w:["Yes: cars → <b>get in</b>.","<i>On</i> is for buses and trains.","<i>To</i> doesn't work with get + the car."]},
      {k:"order", ref:"Place: in / on / at", q:"Translate to English.", hi:"मैं स्टेशन पर तुम्हारा इंतज़ार करूँगा।", words:["I","will","wait","for","you","at","the","station"], a:"I will wait for you at the station.", alt:["I will wait at the station for you."], w:"<b>wait for</b> + <b>at</b> a point. Module 6's <i>will</i>."},
      {k:"mcq", ref:"for / since / by / until", q:"I have lived here ___ 2018.", o:["for","since","by"], a:1, w:["<i>For</i> needs a length of time.","Yes: a starting point → <b>since</b>.","<i>By</i> is a deadline."]},
      {k:"type", ref:"Fixed pairs", q:"Translate to English.", hi:"मुझे संगीत में दिलचस्पी है।", a:["I am interested in music.","I'm interested in music."], w:"<b>interested in</b>."},
      {k:"mcq", ref:"Module 7: questions", q:"Which question is correct?", o:["Where does she works?","Where does she work?","Where she works?"], a:1, w:["<i>Does</i> already has the S.","Yes: wh-word + <b>does</b> + plain verb.","The helper is missing."]},
      {k:"mcq", ref:"Module 8: modals", q:"You ___ park here. It's forbidden.", o:["don't have to","can","mustn't"], a:2, w:["That means it's not necessary.","That means it's allowed.","Yes: <b>mustn't</b> = forbidden."]},
      {k:"mcq", ref:"Module 9: articles", q:"She is ___ honest woman.", o:["a","an","the"], a:1, w:["<i>Honest</i> starts with a vowel sound.","Yes: <b>an honest</b> (silent h).","<i>The</i> would mean a specific woman."]},
      {k:"mcq", ref:"Module 9: articles", q:"I need some ___.", o:["advices","an advice","advice"], a:2, w:["<i>Advice</i> has no plural.","No <i>an</i> before an uncountable noun.","Yes: <b>some advice</b>."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Place things in time and space: <i>at six, on Monday, in June, on the table, in Pune, at the station.</i>",
          "Move and wait correctly: <i>I arrived at the airport. I'm waiting for you. Get on the bus.</i>",
          "Use fixed pairs naturally: <i>interested in, good at, afraid of, discuss it, listen to.</i>"],
     teaser:"Next: <b>Phase 3, Connect Your Ideas.</b> Because, but, so, although: join your sentences into long, smooth ones."}
  ]
});
