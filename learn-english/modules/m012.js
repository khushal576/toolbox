registerModule({
  id: 12,
  title: "Comparing and opinions",
  sub: "bigger, the best, I think…",
  steps: [
    {k:"card", ref:"The puzzle", tag:"Module 12 · Start here", title:"Everything is a comparison",
     html:`<p>Which phone is better? Which road is shorter? Who is the funniest in your family? We compare all day, and then we give <i>opinions</i> about it.</p>
           <p>English has a neat system for this. First, a quick test of your ear.</p>`},
    {k:"mcq", q:"Delhi is ___ than Pune.",
     o:["more big","most big","biger","bigger"], a:3,
     w:["<i>More</i> goes with long words only. <i>Big</i> is short.","<i>Most</i> is for the superlative (the biggest).","Close, but short words that end in one vowel + one consonant double the last letter.","Yes! <b>bigger</b>: short word + <b>er</b>, and the g doubles."]},
    {k:"card", ref:"Comparatives", tag:"The idea · 1 of 5", title:"Comparing two things: -er / more … than",
     html:`<table>
             <tr><th>word type</th><th>do this</th><th>example</th></tr>
             <tr><td>short (1 syllable)</td><td>+ er</td><td>tall → taller<br>cheap → cheaper</td></tr>
             <tr><td>short, one vowel + one consonant</td><td>double the last letter</td><td>big → bigger<br>hot → hotter</td></tr>
             <tr><td>ends in y</td><td>y → ier</td><td>happy → happier<br>easy → easier</td></tr>
             <tr><td>long (2+ syllables)</td><td>more + word</td><td>more expensive<br>more comfortable</td></tr>
             <tr><td>irregular</td><td>learn them</td><td>good → <b>better</b><br>bad → <b>worse</b><br>far → farther / further</td></tr>
           </table>
           <p>Then <b>than</b>: <i>My brother is taller <b>than</b> me. This phone is more expensive <b>than</b> that one.</i></p>
           <div class="wrong">more bigger &nbsp; more better &nbsp; taller that me</div>
           <p class="sub">Make it stronger: <b>much / a lot / far</b> + comparative: <i>much cheaper, a lot better</i>. Slightly: <i>a bit taller</i>.</p>`},
    {k:"order", q:"Translate to English.", hi:"मैं तुमसे ज़्यादा तेज़ दौड़ सकता हूँ।", words:["I","can","run","faster","than","you"], a:"I can run faster than you.",
     w:"<b>fast + er</b> + <b>than</b>. Module 8's <i>can</i> + plain verb."},
    {k:"card", ref:"Superlatives", tag:"The idea · 2 of 5", title:"The top one: the -est / the most",
     html:`<p>Compare <b>three or more</b>, and name the top (or bottom). Always with <b>the</b>:</p>
           <table>
             <tr><th>comparative</th><th>superlative</th></tr>
             <tr><td>taller</td><td>the <b>tallest</b></td></tr>
             <tr><td>bigger</td><td>the <b>biggest</b></td></tr>
             <tr><td>happier</td><td>the <b>happiest</b></td></tr>
             <tr><td>more expensive</td><td>the <b>most expensive</b></td></tr>
             <tr><td>better / worse</td><td>the <b>best</b> / the <b>worst</b></td></tr>
           </table>
           <div class="right">She is <b>the smartest</b> girl <b>in</b> my class. &nbsp; It's <b>the most beautiful</b> place <b>in</b> India.</div>
           <p><b>in</b> + a group (in the class, in the world) · <b>of</b> + a set (of all, of the three).</p>
           <p><b>Handy pattern:</b> <i>one of the best films I have seen</i> (plural noun + Module 5's present perfect).</p>
           <div class="wrong">She is the most tall. &nbsp; the more best</div>`},
    {k:"card", ref:"as … as", tag:"The idea · 3 of 5", title:"Equal and not equal: as … as",
     html:`<div class="right">My brother is <b>as tall as</b> me. <span class="sub">(the same height)</span></div>
           <div class="right">This phone is <b>not as expensive as</b> that one. <span class="sub">(cheaper)</span></div>
           <div class="right">She speaks English <b>as fluently as</b> a native speaker.</div>
           <p>Other ways: <b>the same as</b> (<i>Your bag is the same as mine</i>), <b>different from</b>, <b>similar to</b>.</p>
           <p><b>Amounts:</b> <b>more</b> (both kinds), <b>less</b> + uncountable (<i>less sugar</i>), <b>fewer</b> + countable (<i>fewer people</i>).</p>
           <div class="wrong">fewer water &nbsp; less people</div>`},
    {k:"card", ref:"Opinions", tag:"The idea · 4 of 5", title:"Giving your opinion",
     html:`<table>
             <tr><th>say</th><th>example</th></tr>
             <tr><td>I think / I believe / I feel (that)</td><td>I think this is the best option.</td></tr>
             <tr><td>In my opinion, … / To me, …</td><td>In my opinion, trains are more comfortable than buses.</td></tr>
             <tr><td>Asking</td><td>What do you think of / about …? Do you agree?</td></tr>
             <tr><td>How sure?</td><td>I'm sure / probably / maybe / I'm not sure</td></tr>
           </table>
           <p><b>Say the negative first.</b> English moves <i>not</i> forward:</p>
           <div class="right">I <b>don't think</b> he is right.</div>
           <div class="wrong">I think he isn't right.</div>
           <p><b>Give a reason</b> to make it strong (Module 11): <i>I think it's too expensive <b>because</b> the quality is average. For example, …</i></p>`},
    {k:"card", ref:"Agree and disagree", tag:"The idea · 5 of 5", title:"Agreeing and disagreeing without a fight",
     html:`<table>
             <tr><th>agree</th><th>polite disagreement</th></tr>
             <tr><td>I agree. &nbsp; Exactly. &nbsp; That's true.</td><td>I see what you mean, <b>but</b>…</td></tr>
             <tr><td>You're right. &nbsp; I think so too.</td><td>That's true, <b>but</b> have you thought about…?</td></tr>
             <tr><td>Absolutely.</td><td>I'm not sure I agree. &nbsp; I'm afraid I don't agree.</td></tr>
           </table>
           <p><b>The formula:</b> <i>acknowledge first</i> (I see what you mean / That's a good point) + <i>but</i> + your idea.</p>
           <div class="right">I see your point, but I think the other option is cheaper.</div>
           <div class="wrong">You are wrong. &nbsp; That's nonsense.</div>
           <p class="sub">Soft words help: <i>I think, maybe, a bit, I'm afraid, honestly</i>. (Module 15 uses these in real conversations.)</p>`},
    {k:"mcq", q:"This phone is ___ than that one.", o:["more expensive","expensiver","most expensive"], a:0,
     w:["Yes. A long word → <b>more expensive</b>.","Long words don't take <i>-er</i>.","<i>Most expensive</i> is the superlative."]},
    {k:"type", q:"good → better → the ___", a:["best"], w:"Irregular: good → better → <b>the best</b>."},
    {k:"mcq", q:"She is the ___ student in the class.", o:["tall","taller","tallest"], a:2,
     w:["<i>Tall</i> is the plain word.","<i>Taller</i> compares two.","Yes. <b>the tallest</b>, compared with all in the class."]},
    {k:"mcq", q:"My brother is ___ me.", o:["as tall as","as taller as","tall as"], a:0,
     w:["Yes. <b>as + plain adjective + as</b>.","After <i>as</i>, the plain word, not the -er form.","Needs the first <i>as</i> too."]},
    {k:"mcq", q:"Which is correct?", o:["He is more taller than me.","He is taller than me.","He is tallest than me."], a:1,
     w:["Never <i>more</i> + <i>-er</i> together.","Yes. <b>taller than</b>.","<i>Tallest</i> needs <i>the</i> and compares many."]},
    {k:"order", q:"Translate to English.", hi:"यह फ़िल्म उस फ़िल्म से बेहतर है।", words:["This","film","is","better","than","that","film"], a:"This film is better than that film.",
     w:"<b>good → better</b> + <b>than</b>."},
    {k:"order", q:"Translate to English.", hi:"वह मेरी कक्षा की सबसे होशियार लड़की है।", words:["She","is","the","smartest","girl","in","my","class"], a:"She is the smartest girl in my class.",
     w:"<b>the + -est</b> + <b>in</b> + a group."},
    {k:"mcq", q:"I ___ it's a good idea.", o:["think","am thinking","thinks"], a:0,
     w:["Yes. An opinion uses the simple form: <b>I think</b>.","<i>I am thinking</i> means the thinking is in progress (Module 3).","\"I\" takes no S."]},
    {k:"mcq", q:"Which is more natural?", o:["I think he isn't right.","I don't think he is right.","I think he not right."], a:1,
     w:["English moves <i>not</i> forward.","Yes. <b>I don't think</b> + positive.","The glue is missing."]},
    {k:"type", q:"Translate to English.", hi:"मेरी राय में यह सबसे अच्छा विकल्प है।", a:["In my opinion, this is the best option.","In my opinion this is the best option.","I think this is the best option."], w:"<b>In my opinion</b> + the best."},
    {k:"mcq", q:"Which is the polite way to disagree?", o:["You are wrong.","That's nonsense.","I see what you mean, but I'm not sure I agree."], a:2,
     w:["Direct and blunt.","Rude.","Yes. Acknowledge, then <b>but</b>, softly."]},
    {k:"mcq", q:"There were ___ people today than yesterday. <span class='sub'>(a smaller number)</span>", o:["less","fewer","few"], a:1,
     w:["<i>Less</i> is for uncountable nouns.","Yes. Countable → <b>fewer</b>.","<i>Few</i> is not a comparative."]},
    {k:"order", q:"Translate to English.", hi:"यह उतना महँगा नहीं है जितना मैंने सोचा था।", words:["It","is","not","as","expensive","as","I","thought"], a:"It is not as expensive as I thought.",
     w:"<b>not as … as</b>: less than expected. Module 4's <i>thought</i>."},
    {k:"mcq", q:"It is one of the ___ films I have seen.", o:["better","best","good"], a:1,
     w:["<i>Better</i> compares two.","Yes. <b>one of the best</b> + plural noun.","The pattern needs a superlative."]},
    {k:"mcq", q:"Revision from Module 11: I think it's good, ___ it's too expensive.", o:["because","but","so"], a:1,
     w:["<i>Because</i> would give a reason for it being good.","Yes. A contrast → <b>but</b>.","<i>So</i> shows a result."]},
    {k:"build", intro:"Your turn. Compare and give opinions about <b>your own world</b>. Type each one and say it out loud.",
     items:[
      {p:"Compare two people or things you know.", frame:"______ is ______er / more ______ than ______.", ex:"My phone is newer than my laptop.", must:/\b\w+er\b.*\bthan\b|\bmore\b.*\bthan\b|\b(better|worse)\b.*\bthan\b/i, ok:"A comparison with <b>than</b>.", tip:"<b>taller than / more expensive than / better than</b>."},
      {p:"Name the best of something you know.", frame:"The best ______ in ______ is ______.", ex:"The best restaurant in my city is Annapurna.", must:/\b(the best|the most \w+|the \w+est)\b/i, ok:"A superlative with <b>the</b>.", tip:"<b>the best / the biggest / the most ...</b>"},
      {p:"Say two things are the same.", frame:"______ is as ______ as ______.", ex:"My sister is as tall as my mother.", must:/\bas\b.*\bas\b/i, ok:"<b>as … as</b> = equal.", tip:"<b>as + plain adjective + as</b>."},
      {p:"Give an opinion about something, with a reason.", frame:"In my opinion, ______ because ______.", ex:"I think trains are better than buses because they are more comfortable.", must:/\b(i think|in my opinion|i believe|i feel|to me)\b/i, ok:"Opinion + reason. Strong.", tip:"<b>I think ... because ...</b> / <b>In my opinion, ...</b>"},
      {p:"Disagree politely with this: \"Cricket is boring.\"", frame:"I see what you mean, but ______.", ex:"I see what you mean, but I think cricket is very exciting.", must:/\b(i see|i'm afraid|i'm not sure|that's true|i understand)\b.*\bbut\b|\bi'm afraid\b|\bnot sure\b/i, ok:"Acknowledge + <b>but</b> + your idea. Polite and clear.", tip:"<b>I see what you mean, but ...</b>"}
     ]},
    {k:"trap", ref:"Mistake trap", title:"The 5 classic traps",
     items:[
      {bad:"more bigger / more better", good:"bigger / better", fix:"Never <i>more</i> + <i>-er</i> together."},
      {bad:"He is taller that me.", good:"He is taller than me.", fix:"Comparatives use <b>than</b>."},
      {bad:"She is the most tall girl.", good:"She is the tallest girl.", fix:"Short words: <i>the -est</i>. Long words: <i>the most + word</i>."},
      {bad:"I think he isn't right.", good:"I don't think he is right.", fix:"Move <i>not</i> forward: I don't think ..."},
      {bad:"fewer water / less people", good:"less water / fewer people", fix:"<b>less</b> + uncountable, <b>fewer</b> + countable."}
     ]},
    {k:"boss", ref:"Boss", title:"Boss challenge: The Debate", pass:0.8,
     intro:"You are in a friendly debate: compare, rank and give opinions. This also revisits Modules 1 to 11. You need 8 of 10.",
     qs:[
      {k:"mcq", ref:"Comparatives", q:"This bag is ___ than that one.", o:["cheap","more cheap","cheaper"], a:2, w:["That's the plain word.","Short words take <i>-er</i>, not <i>more</i>.","Yes: <b>cheaper than</b>."]},
      {k:"type", ref:"Superlatives", q:"bad → worse → the ___", a:["worst"], w:"Irregular: bad → worse → <b>the worst</b>."},
      {k:"mcq", ref:"Comparatives", q:"Which is correct?", o:["She is more taller than me.","She is taller than me.","She is taller that me."], a:1, w:["Never <i>more</i> + <i>-er</i>.","Yes: <b>taller than</b>.","Comparatives use <i>than</i>."]},
      {k:"mcq", ref:"Superlatives", q:"He is the ___ boy in the class.", o:["tall","taller","tallest"], a:2, w:["Plain word.","Compares two.","Yes: <b>the tallest</b>."]},
      {k:"mcq", ref:"as … as", q:"I'm ___ tall as my brother.", o:["as","more","so"], a:0, w:["Yes: <b>as tall as</b>.","<i>More</i> doesn't fit with <i>as</i>.","<i>So tall as</i> is not the pattern."]},
      {k:"mcq", ref:"Opinions", q:"I don't think it ___ a good idea.", o:["isn't","is","not"], a:1, w:["Double negative.","Yes: <b>I don't think it is</b> (not goes forward).","Not natural."]},
      {k:"order", ref:"Comparatives", q:"Translate to English.", hi:"यह कमरा उस कमरे से बड़ा है।", words:["This","room","is","bigger","than","that","room"], a:"This room is bigger than that room.", w:"<b>big → bigger</b> (double the g) + <b>than</b>."},
      {k:"type", ref:"Opinions", q:"Translate to English.", hi:"मेरी राय में वह सही है।", a:["In my opinion, he is right.","In my opinion he is right.","I think he is right.","In my opinion, she is right.","I think she is right."], w:"<b>In my opinion</b> + a full sentence."},
      {k:"mcq", ref:"Agree and disagree", q:"Which is the most polite disagreement?", o:["That's wrong.","No way.","That's true, but I think there's another way to look at it."], a:2, w:["Blunt.","Rude.","Yes: acknowledge + <b>but</b>."]},
      {k:"mcq", ref:"Module 11: connectors", q:"It was cold, ___ we wore jackets.", o:["but","so","although"], a:1, w:["<i>But</i> would show a contrast.","Yes: a result → <b>so</b>.","<i>Although</i> shows a surprise."]}
     ]},
    {k:"done", title:"You can now say…",
     can:["Compare things: <i>This is cheaper than that. She is taller than me. It's as good as the old one.</i>",
          "Name the top and bottom: <i>the best, the worst, the most expensive, one of the best films I've seen.</i>",
          "Give opinions and disagree politely: <i>I think… In my opinion… I see what you mean, but…</i>"],
     teaser:"Next: <b>Conditionals.</b> Real and imaginary \"if\": <i>If I had time, I would help. If I had studied, I would have passed.</i>"}
  ]
});
