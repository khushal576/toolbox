"""'Ask Claude' panel (roadmap H2) in headless Chromium. The helper itself is stubbed in the page (fetch for /api/helper/*), so no Pro usage is spent."""

import json
import shutil
import time

import pytest

from conftest import BASE_URL

pytestmark = pytest.mark.browser

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
DRIVER = shutil.which("chromedriver")

STUB = r"""
window.__asks = [];
window.__chats = window.__chats || [];
window.__all = window.__all || [];
window.__policy = {policy: '# policy\n- Be brief.', default: '# default policy', max_chars: 4000};
const realFetch = window.fetch.bind(window);
const J = (o) => Promise.resolve(new Response(JSON.stringify(o), {headers: {'Content-Type': 'application/json'}}));
window.fetch = function (url, opt) {
  const U = String(url);
  if (U.indexOf('/api/helper/chats?') === 0) return J({chats: window.__chats});
  let mm = U.match(/\/api\/helper\/chats\/([^/]+)\/messages\?(.*)$/);
  if (mm) {
    const q = new URLSearchParams(mm[2]), lim = Number(q.get('limit')), before = q.get('before') ? Number(q.get('before')) : Infinity;
    const pool = window.__all.filter(m => m.id < before), page = pool.slice(Math.max(0, pool.length - lim));
    window.__pages = (window.__pages || 0) + 1;
    return J({messages: page, has_more: pool.length > page.length});
  }
  window.__pol = window.__pol || {};
  if (U.indexOf('/api/helper/policy') === 0 && (!opt || !opt.method)) { const t = (U.split('tool=')[1] || ''); return J({policy: window.__pol[t] != null ? window.__pol[t] : (t ? '# tool policy ' + t : window.__policy.policy), default: window.__policy.default, max_chars: 4000, tool: t, tools: Object.keys(window.__pol).filter(k => k)}); }
  if (U === '/api/helper/policy' && opt.method === 'PUT') { const b = JSON.parse(opt.body); const t = b.tool || ''; window.__pol[t] = b.reset ? window.__policy.default : b.policy; window.__saved = b; return J({policy: window.__pol[t], tool: t, tools: Object.keys(window.__pol).filter(k => k)}); }
  window.__reviews = window.__reviews || [];
  if (U === '/api/helper/reviews' && opt && opt.method === 'POST') { const b = JSON.parse(opt.body); window.__rated = b; if (b.rating === 'down' && b.note) window.__reviews.push({id: window.__reviews.length + 1, note: b.note, tool: b.tool, status: 'new'}); return J({ok: true, id: 1}); }
  if (U.indexOf('/api/helper/reviews/summary') === 0) return J({days: 30, tools: {'df-studio': {up: 3, down: 1}}});
  if (U.indexOf('/api/helper/reviews?') === 0) return J({reviews: window.__reviews.filter(r => r.status === 'new')});
  let rs = U.match(/\/api\/helper\/reviews\/(\d+)\/status/); if (rs) { const r = window.__reviews[Number(rs[1]) - 1]; if (r) r.status = JSON.parse(opt.body).status; return J({ok: true}); }
  if (String(url).indexOf('/api/helper/status') === 0) return Promise.resolve(new Response(JSON.stringify({state: 'ready', message: 'Ready.'}), {headers: {'Content-Type': 'application/json'}}));
  if (String(url).indexOf('/api/helper/ask') === 0) {
    const body = JSON.parse(opt.body); window.__asks.push(body);
    const tid = body.thread_id || '11111111-2222-3333-4444-555555555555';
    const ev = [{type: 'start', thread_id: tid}, {type: 'text', text: 'Hel'}, {type: 'text', text: 'lo'}, {type: 'tool', id: 't', name: 'find_actions', status: 'running'}, ...(body.message.indexOf('SAVE') >= 0 ? [{type: 'tool', id: 't', name: 'table_transform', status: 'done', saved: true, what: 'scratch.out'}] : []), {type: 'text', text: 'Done.'}, {type: 'done', thread_id: tid, text: 'Done.'}];
    const enc = new TextEncoder();
    return Promise.resolve(new Response(new ReadableStream({start(c) { ev.forEach(e => c.enqueue(enc.encode('data: ' + JSON.stringify(e) + '\n\n'))); c.close(); }})));
  }
  return realFetch(url, opt);
};
"""


@pytest.fixture(scope="module")
def driver():
    if not (CHROMIUM and DRIVER):
        pytest.skip("headless browser checks need chromium + chromedriver")
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    o = Options()
    o.binary_location = CHROMIUM
    for arg in ("--headless=new", "--no-sandbox", "--disable-gpu", "--window-size=1500,900"):
        o.add_argument(arg)
    d = webdriver.Chrome(options=o, service=Service(DRIVER))
    yield d
    d.quit()


def wait(driver, js, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if driver.execute_script(js):
            return True
        time.sleep(0.1)
    raise AssertionError("timed out waiting for: " + js)


def ask(driver, text):
    n = driver.execute_script("return window.__asks.length")
    driver.execute_script("document.getElementById('hlpIn').value = arguments[0]; document.getElementById('hlpForm').requestSubmit();", text)
    wait(driver, f"return window.__asks.length > {n} && !document.getElementById('hlpSend').disabled")


def test_panel_hidden_then_three_tools_one_thread(driver):
    driver.execute_script("try { localStorage.removeItem('toolbox_helper_cur'); } catch (e) {}")
    driver.get(BASE_URL + "/")
    wait(driver, "return document.readyState === 'complete'")
    driver.execute_script(STUB)
    assert driver.execute_script("return getComputedStyle(document.getElementById('helper')).display") == "none"      # hidden by default
    driver.execute_script("document.getElementById('helperBtn').click()")
    assert driver.execute_script("return getComputedStyle(document.getElementById('helper')).display") == "flex"
    driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'j', ctrlKey: true, bubbles: true}))")   # Ctrl+J closes
    assert driver.execute_script("return getComputedStyle(document.getElementById('helper')).display") == "none"
    driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'j', ctrlKey: true, bubbles: true}))")
    names = [n for n in driver.execute_script("return Array.from(document.querySelectorAll('#nav [data-open]')).map(a => a.dataset.open)") if n not in ("home", "status", "settings")][:3]
    assert len(names) == 3
    for i, n in enumerate(names):
        driver.execute_script("location.hash = '#/tool/' + arguments[0]", n)
        wait(driver, "return !!document.querySelector('.pane.active iframe')")
        ask(driver, f"question {i}")
    asks = driver.execute_script("return window.__asks")
    assert asks[0]["thread_id"] is None and asks[1]["thread_id"] == asks[2]["thread_id"] == "11111111-2222-3333-4444-555555555555"   # one thread follows the owner across tools
    for a, n in zip(asks, names):
        assert "Open tool:" in a["context"] and f"(id {n})" in a["context"] and len(a["context"]) < 4000
    log = driver.execute_script("return document.getElementById('hlpLog').innerText")
    assert "Hello" in log and "find_actions" in log
    driver.execute_script("document.getElementById('hlpNew').click()")
    ask(driver, "fresh")
    assert driver.execute_script("return window.__asks")[-1]["thread_id"] is None                                            # New chat = new session


def test_tool_context_message_is_capped_and_only_from_its_own_frame(driver):
    driver.get(BASE_URL + "/")
    wait(driver, "return document.readyState === 'complete'")
    driver.execute_script(STUB)
    name = driver.execute_script("return Array.from(document.querySelectorAll('#nav [data-open]')).map(a => a.dataset.open).filter(n => !['home','status','settings'].includes(n))[0]")
    driver.execute_script("location.hash = '#/tool/' + arguments[0]", name)
    wait(driver, "return !!document.querySelector('.pane.active iframe')")
    driver.execute_script("document.getElementById('helperBtn').click()")
    driver.execute_script("window.postMessage({type: 'toolbox-context', text: 'FAKE from the shell window'}, '*')")           # not from a tool frame: ignored
    time.sleep(0.3)
    ask(driver, "hi")
    assert "FAKE" not in driver.execute_script("return window.__asks")[-1]["context"]
    driver.execute_script("var f = document.querySelector('.pane.active iframe'); f.contentWindow.eval(\"parent.postMessage({type: 'toolbox-context', text: 'x'.repeat(5000)}, '*')\")")
    time.sleep(0.5)
    ask(driver, "again")
    ctx = driver.execute_script("return window.__asks")[-1]["context"]
    assert "On screen: " in ctx and len(ctx) < 3300 and ctx.count("x") <= 2800 + 40


CARD_STUB = """
window.__calls = [];
window.__card = {id: 'abc123abc123', tool: 'table_transform', target_kind: 'workspace', target: 'scratch', action: 'create_table', status: 'pending',
  plan: {what: 'Create the Vault Data table scratch.out', target: 'scratch.out', environment: 'non-prod', rows: 1234, columns: ['id', 'name'], source: 'system.orders', steps: 3}};
const prev = window.fetch;
window.fetch = function (url, opt) {
  const u = String(url);
  if (u === '/tools/ai-access/approvals') return Promise.resolve(new Response(JSON.stringify({ok: true, cards: [window.__card]}), {headers: {'Content-Type': 'application/json'}}));
  if (u.indexOf('/tools/ai-access/approvals/') === 0) {
    window.__calls.push({url: u, body: opt && opt.body});
    const body = JSON.parse((opt && opt.body) || '{}');
    if (u.endsWith('/approve') && body.pin !== 'right-pin-1') return Promise.resolve(new Response(JSON.stringify({ok: false, error: 'That PIN is not right.'})));
    window.__card.status = u.endsWith('/approve') ? 'approved' : 'rejected';
    return Promise.resolve(new Response(JSON.stringify({ok: true})));
  }
  return prev(url, opt);
};
"""


def test_plan_card_shows_facts_and_needs_the_pin_to_approve(driver):
    driver.get(BASE_URL + "/")
    wait(driver, "return document.readyState === 'complete'")
    driver.execute_script(STUB)
    driver.execute_script(CARD_STUB)
    driver.execute_script("document.getElementById('helperBtn').click()")
    wait(driver, "return !!document.querySelector('#hlpCards .pcard')")
    text = driver.execute_script("return document.getElementById('hlpCards').innerText")
    assert "scratch.out" in text and "1,234" in text and "system.orders" in text and "NON-PROD" in text.upper()
    driver.execute_script("document.querySelector('[data-card-ok]').click()")                       # no PIN typed
    assert "PIN" in driver.execute_script("return document.querySelector('.pcard .msg').textContent") and driver.execute_script("return window.__calls.length") == 0
    driver.execute_script("document.querySelector('.cpin').value = 'wrong-pin-1'; document.querySelector('[data-card-ok]').click()")
    wait(driver, "return document.querySelector('.pcard .msg').textContent.indexOf('not right') >= 0")
    n = driver.execute_script("return window.__asks.length")
    driver.execute_script("document.querySelector('.cpin').value = 'right-pin-1'; document.querySelector('[data-card-ok]').click()")
    wait(driver, f"return window.__asks.length > {n}")                                               # approval tells Claude to go ahead
    assert "approved" in driver.execute_script("return window.__asks[window.__asks.length - 1].message").lower()
    wait(driver, "return document.getElementById('hlpCards').innerText.indexOf('Approved') >= 0")


def test_plan_card_reject(driver):
    driver.get(BASE_URL + "/")
    wait(driver, "return document.readyState === 'complete'")
    driver.execute_script(STUB)
    driver.execute_script(CARD_STUB)
    driver.execute_script("document.getElementById('helperBtn').click()")
    wait(driver, "return !!document.querySelector('[data-card-no]')")
    n = driver.execute_script("return window.__asks.length")
    driver.execute_script("document.querySelector('[data-card-no]').click()")
    wait(driver, "return !document.querySelector('#hlpCards .pcard')")                                                        # a rejected card disappears by itself
    assert "rejected" in driver.execute_script("return document.getElementById('hlpLog').innerText").lower()
    assert driver.execute_script("return window.__asks.length") == n                                  # rejecting costs no tokens
    assert driver.execute_script("return window.__calls[0].url").endswith("/reject")


def test_button_toggles_and_hide_button_closes(driver):
    driver.get(BASE_URL + "/")
    wait(driver, "return document.readyState === 'complete'")
    driver.execute_script(STUB)
    shown = "return getComputedStyle(document.getElementById('helper')).display"
    assert driver.execute_script(shown) == "none" and driver.execute_script("return document.getElementById('helperBtn').textContent").strip().endswith("Ask Claude")
    driver.execute_script("document.getElementById('helperBtn').click()")
    assert driver.execute_script(shown) == "flex" and "Hide" in driver.execute_script("return document.getElementById('helperBtn').textContent")
    assert "Claude" not in driver.execute_script("return document.querySelector('#helper header').innerText")                          # icons only, no second "Ask Claude" title
    driver.execute_script("document.getElementById('helperBtn').click()")                                                              # the same button hides it
    assert driver.execute_script(shown) == "none"
    driver.execute_script("document.getElementById('helperBtn').click()")
    driver.execute_script("document.getElementById('hlpClose').click()")                                                               # the Hide button in the panel
    assert driver.execute_script(shown) == "none"
    driver.execute_script("document.getElementById('helperBtn').click()")
    assert driver.execute_script("return document.getElementById('hlpIn').getBoundingClientRect().height") >= 55                      # the box is not squashed


RECIPE_STUB = """
window.__rcalls = [];
const prev2 = window.fetch;
window.fetch = function (url, opt) {
  const u = String(url);
  if (u === '/tools/ai-access/recipes') return Promise.resolve(new Response(JSON.stringify({ok: true, recipes: [{name: 'events-to-sales', description: 'stage then load', last_status: null,
    steps: [{tool: 'stage_query', writes: true, summary: 'query -> scratch.ev'}, {tool: 'load_table', writes: true, summary: 'scratch.ev -> sales.events'}]}]})));
  if (u.indexOf('/tools/ai-access/recipes/') === 0 && opt && opt.method === 'POST') {
    const b = JSON.parse(opt.body || '{}'); window.__rcalls.push(b);
    if (!b.from_step) return Promise.resolve(new Response(JSON.stringify({ok: true, status: 'waiting_for_approval', step: 2, next_from_step: 1, steps: [{step: 1, tool: 'stage_query', ok: true, summary: 'saved scratch.ev (2 rows)'}], message: 'Step 2 wants to write.'})));
    return Promise.resolve(new Response(JSON.stringify({ok: true, status: 'done', steps: [{step: 2, tool: 'load_table', ok: true, summary: 'inserted 2 rows'}], message: 'Recipe finished.'})));
  }
  return prev2(url, opt);
};
"""


def test_recipes_run_without_ai_wait_for_approval_and_continue(driver):
    driver.get(BASE_URL + "/")
    wait(driver, "return document.readyState === 'complete'")
    driver.execute_script(STUB)
    driver.execute_script(RECIPE_STUB)
    driver.execute_script("document.getElementById('helperBtn').click()")
    driver.execute_script("document.getElementById('hlpRecipesBtn').click()")
    wait(driver, "return !!document.querySelector('[data-rcp-run]')")
    assert "events-to-sales" in driver.execute_script("return document.getElementById('hlpRecipes').innerText")
    n = driver.execute_script("return window.__asks.length")
    driver.execute_script("document.querySelector('[data-rcp-run]').click()")
    wait(driver, "return document.getElementById('hlpLog').innerText.indexOf('Step 2 wants to write') >= 0")
    driver.execute_script("Array.from(document.querySelectorAll('#hlpLog button')).find(b => b.textContent === 'Continue').click()")
    wait(driver, "return document.getElementById('hlpLog').innerText.indexOf('Recipe finished') >= 0")
    assert driver.execute_script("return window.__rcalls[1].from_step") == 1
    assert driver.execute_script("return window.__asks.length") == n                                                                    # no AI call, no tokens


def _fresh(driver):
    driver.get(BASE_URL + "/")
    driver.execute_script("try { localStorage.removeItem('toolbox_tabs_v1'); localStorage.removeItem('toolbox_helper_cur'); } catch (e) {}")
    driver.get(BASE_URL + "/#/")
    wait(driver, "return document.readyState === 'complete'")


def test_reload_shows_the_old_chat_and_loads_older_pages_on_scroll(driver):
    driver.execute_script("try { localStorage.removeItem('toolbox_helper_cur'); } catch (e) {}")
    _fresh(driver)
    driver.execute_script("""window.__chats = [{id: '11111111-2222-3333-4444-555555555555', title: 'old chat', tool: 'home', created: 1, last: Date.now() / 1000, n: 75}];
      window.__all = Array.from({length: 75}, (_, i) => ({id: i + 1, role: i % 2 ? 'assistant' : 'user', text: 'message ' + i, meta: null, ts: 1}));""")
    driver.execute_script(STUB)
    driver.execute_script("document.getElementById('helperBtn').click()")
    wait(driver, "return document.querySelectorAll('#hlpLog .hm.me, #hlpLog .hm.ai').length === 30")                      # only one page rendered, not all 75
    log = driver.execute_script("return document.getElementById('hlpLog').innerText")
    assert "message 74" in log and "message 44" not in log and "Load older" in log                                       # newest page; older ones wait
    driver.execute_script("document.getElementById('hlpLog').scrollTop = 0; document.getElementById('hlpLog').dispatchEvent(new Event('scroll'))")
    wait(driver, "return document.querySelectorAll('#hlpLog .hm.me, #hlpLog .hm.ai').length === 60")                      # scrolling up loads the next page
    wait(driver, "return document.querySelectorAll('#hlpLog .hm.me, #hlpLog .hm.ai').length >= 60")
    driver.execute_script("document.getElementById('hlpOlder').click()")
    wait(driver, "return document.querySelectorAll('#hlpLog .hm.me, #hlpLog .hm.ai').length === 75 && !document.getElementById('hlpOlder')")
    texts = driver.execute_script("return Array.from(document.querySelectorAll('#hlpLog .hm.me, #hlpLog .hm.ai')).map(e => e.textContent)")
    assert texts == [f"message {i}" for i in range(75)]                                                                    # complete and in order


def test_chat_older_than_an_hour_is_not_reopened_but_can_be_picked(driver):
    _fresh(driver)
    driver.execute_script("""window.__chats = [{id: '11111111-2222-3333-4444-555555555555', title: 'yesterday chat', tool: 'home', created: 1, last: 1, n: 2}];
      window.__all = [{id: 1, role: 'user', text: 'hello old', meta: null, ts: 1}, {id: 2, role: 'assistant', text: 'hi old', meta: null, ts: 1}];""")
    driver.execute_script(STUB)
    driver.execute_script("document.getElementById('helperBtn').click()")
    wait(driver, "return document.getElementById('hlpLog').innerText.indexOf('New chat') >= 0")
    driver.execute_script("document.getElementById('hlpThreadsBtn').click()")
    wait(driver, "return !!document.querySelector('[data-thread]')")
    driver.execute_script("document.querySelector('[data-thread]').click()")
    wait(driver, "return document.getElementById('hlpLog').innerText.indexOf('hi old') >= 0")


def test_saved_event_refreshes_the_tool_you_are_looking_at(driver):
    _fresh(driver)
    driver.execute_script(STUB)
    name = driver.execute_script("return Array.from(document.querySelectorAll('#nav [data-open]')).map(a => a.dataset.open).filter(n => !['home','status','settings'].includes(n))[0]")
    driver.execute_script("location.hash = '#/tool/' + arguments[0]", name)
    wait(driver, "return !!document.querySelector('.pane.active iframe')")
    driver.execute_script("window.__loads = 0; document.querySelector('.pane.active iframe').addEventListener('load', () => window.__loads++)")
    driver.execute_script("document.getElementById('helperBtn').click()")
    ask(driver, "please SAVE it")
    wait(driver, "return window.__loads >= 1")                                                                              # the tool reloaded by itself
    assert "saved scratch.out" in driver.execute_script("return document.getElementById('hlpLog').innerText")
    assert driver.execute_script("return window.__asks[window.__asks.length - 1].tool") == name                              # the chat is tagged with the tool


def test_policy_editor_loads_saves_and_resets(driver):
    _fresh(driver)
    driver.execute_script(STUB)
    driver.execute_script("document.getElementById('helperBtn').click()")
    driver.execute_script("document.getElementById('hlpPolicyBtn').click()")
    wait(driver, "return document.getElementById('polText').value.indexOf('Be brief') >= 0")
    assert driver.execute_script("return document.getElementById('polScope').value") == ""                                        # on Home: the general policy
    driver.execute_script("document.getElementById('polText').value = '- Answer in French.'; document.getElementById('polSave').click()")
    wait(driver, "return window.__saved && window.__saved.policy === '- Answer in French.' && window.__saved.tool === ''")
    assert "Saved" in driver.execute_script("return document.getElementById('polMsg').textContent")
    driver.execute_script("window.confirm = () => true; document.getElementById('polReset').click()")
    wait(driver, "return window.__saved.reset === true")
    assert driver.execute_script("return document.getElementById('polText').value") == "# default policy"


def test_answers_render_bold_code_lists_and_tables_but_never_html(driver):
    driver.execute_script("try { localStorage.removeItem('toolbox_helper_cur'); } catch (e) {}")
    _fresh(driver)
    driver.execute_script("""window.__chats = [{id: '11111111-2222-3333-4444-555555555555', title: 't', tool: 'home', created: 1, last: Date.now() / 1000, n: 1}];
      window.__all = [{id: 1, role: 'assistant', meta: null, ts: 1, text: 'Done: **3 tables** in `scratch`\\n\\n- one\\n- two <img src=x onerror=window.__pwned=1>\\n\\n| a | b |\\n|---|---|\\n| 1 | **2** |'}];""")
    driver.execute_script(STUB)
    driver.execute_script("document.getElementById('helperBtn').click()")
    wait(driver, "return !!document.querySelector('#hlpLog .hm.ai table')")
    assert driver.execute_script("return document.querySelector('#hlpLog .hm.ai b').textContent") == "3 tables"
    assert driver.execute_script("return document.querySelector('#hlpLog .hm.ai code').textContent") == "scratch"
    assert driver.execute_script("return document.querySelectorAll('#hlpLog .hm.ai li').length") == 2
    assert driver.execute_script("return Array.from(document.querySelectorAll('#hlpLog .hm.ai td')).map(e => e.textContent).join('|')") == "1|2"
    time.sleep(0.5)
    assert driver.execute_script("return window.__pwned === undefined and document.querySelectorAll('#hlpLog img').length === 0".replace(" and ", " && ")) is True      # HTML in an answer stays text


def test_code_blocks_get_a_copy_button_and_stay_text(driver):
    driver.execute_script("try { localStorage.removeItem('toolbox_helper_cur'); } catch (e) {}")
    _fresh(driver)
    driver.execute_script("""window.__chats = [{id: '11111111-2222-3333-4444-555555555555', title: 't', tool: 'df-studio', created: 1, last: Date.now() / 1000, n: 1}];
      window.__all = [{id: 1, role: 'assistant', meta: null, ts: 1, text: 'Paste this:\\n\\n```python\\ndef transform(df):\\n    return df[df["a"] > 1] <b>x</b>\\n```'}];""")
    driver.execute_script(STUB)
    driver.execute_script("document.getElementById('helperBtn').click()")
    wait(driver, "return !!document.querySelector('#hlpLog pre code')")
    code = driver.execute_script("return document.querySelector('#hlpLog pre code').textContent")
    assert code.startswith("python") is False and "def transform(df):" in code and "<b>x</b>" in code and "\n    return" in code      # exact text, tags not interpreted
    assert driver.execute_script("return document.querySelectorAll('#hlpLog pre b').length") == 0
    assert driver.execute_script("return document.querySelector('#hlpLog pre .cpy').textContent") == "Copy"


def test_a_long_streamed_answer_does_not_freeze_the_browser(driver):
    _fresh(driver)
    driver.execute_script(STUB)
    driver.execute_script("""
      const prev = window.fetch;
      window.fetch = function (url, opt) {
        if (String(url).indexOf('/api/helper/ask') === 0) {
          const enc = new TextEncoder(); let text = 'Result:\\n\\n| a | b | c |\\n|---|---|---|\\n'; for (let i = 0; i < 60; i++) text += '| ' + i + ' | **x' + i + '** | `y` |\\n'; text += '\\n' + 'word '.repeat(1500);
          const ev = [{type: 'start', thread_id: '11111111-2222-3333-4444-555555555555'}]; for (let i = 0; i < text.length; i += 3) ev.push({type: 'text', text: text.slice(i, i + 3)}); ev.push({type: 'done', text: text});
          return Promise.resolve(new Response(new ReadableStream({start(c) { ev.forEach(e => c.enqueue(enc.encode('data: ' + JSON.stringify(e) + '\\n\\n'))); c.close(); }})));
        }
        return prev(url, opt);
      };
      window.__t0 = performance.now(); window.__long = 0; new PerformanceObserver(l => l.getEntries().forEach(e => window.__long += e.duration)).observe({entryTypes: ['longtask']});""")
    driver.execute_script("document.getElementById('helperBtn').click()")
    driver.execute_script("document.getElementById('hlpIn').value = 'go'; document.getElementById('hlpForm').requestSubmit();")
    wait(driver, "return !document.getElementById('hlpSend').disabled && document.querySelectorAll('#hlpLog .hm.ai tr').length >= 60", 20)
    took = driver.execute_script("return performance.now() - window.__t0")
    assert took < 6000, took                                                                                                   # it used to take minutes (re-drawing the table for every 3 characters)
    assert driver.execute_script("return window.__long") < 3000


def test_review_buttons_and_turning_a_note_into_a_tool_rule(driver):
    _fresh(driver)
    driver.execute_script(STUB)
    driver.execute_script("location.hash = '#/tool/df-studio'")
    wait(driver, "return !!document.querySelector('.pane.active iframe')")
    driver.execute_script("document.getElementById('helperBtn').click()")
    ask(driver, "hello")
    wait(driver, "return !!document.querySelector('#hlpLog .rate')")
    driver.execute_script("document.querySelectorAll('#hlpLog .rate button')[1].click()")                                       # 👎
    driver.execute_script("document.querySelector('#hlpLog .rate input').value = 'Do not paste rows, just the count'; document.querySelector('#hlpLog .rate .send').click()")
    wait(driver, "return window.__rated && window.__rated.rating === 'down' && window.__rated.tool === 'df-studio'")
    assert "Saved" in driver.execute_script("return document.querySelector('#hlpLog .rate').textContent")
    driver.execute_script("document.getElementById('hlpPolicyBtn').click()")
    wait(driver, "return document.getElementById('polScope').value === 'df-studio' && document.getElementById('polText').value.indexOf('tool policy df-studio') >= 0")      # opens on the tool you are in
    assert "3" in driver.execute_script("return document.getElementById('polSum').textContent")
    wait(driver, "return !!document.querySelector('[data-rev-rule]')")
    driver.execute_script("document.querySelector('[data-rev-rule]').click()")
    wait(driver, "return window.__saved && window.__saved.tool === 'df-studio' && window.__saved.policy.indexOf('- Do not paste rows, just the count') >= 0")
    assert "## Learned" in driver.execute_script("return window.__saved.policy")
    wait(driver, "return !document.querySelector('[data-rev-rule]')")                                                           # the used note leaves the list


def test_command_mode_is_the_default_and_the_switch_changes_what_claude_is_told(driver):
    driver.execute_script("try { localStorage.removeItem('toolbox_helper_mode'); } catch (e) {}")
    _fresh(driver)
    driver.execute_script(STUB)
    driver.execute_script("document.getElementById('helperBtn').click()")
    assert "command" in driver.execute_script("return document.getElementById('hlpMode').textContent").lower()
    ask(driver, "filter 2025")
    assert driver.execute_script("return window.__asks[window.__asks.length - 1].context").startswith("Mode: COMMAND.")
    driver.execute_script("document.getElementById('hlpMode').click()")
    assert "Run" in driver.execute_script("return document.getElementById('hlpMode').textContent")
    ask(driver, "filter 2025")
    assert driver.execute_script("return window.__asks[window.__asks.length - 1].context").startswith("Mode: RUN.")
    driver.execute_script("localStorage.removeItem('toolbox_helper_mode')")


def test_dataframe_studio_is_command_only_and_the_helper_sees_the_pipeline(driver):
    _fresh(driver)
    driver.execute_script("localStorage.setItem('toolbox_helper_mode', 'run')")                                                 # even if Run was chosen elsewhere
    driver.execute_script(STUB)
    driver.execute_script("location.hash = '#/tool/df-studio'")
    wait(driver, "return !!document.querySelector('.pane.active iframe') && document.querySelector('.pane.active iframe').contentWindow.document.readyState === 'complete'")
    wait(driver, "return typeof document.querySelector('.pane.active iframe').contentWindow.__helperContext === 'function'")
    driver.execute_script("document.getElementById('helperBtn').click()")
    assert driver.execute_script("return getComputedStyle(document.getElementById('hlpMode')).display") == "none"              # one mode here: no switch
    driver.execute_script("""document.querySelector('.pane.active iframe').contentWindow.__helperContext({table_ref: 'l3test.orders', row_count: 200000,
      columns: [{name: 'day', sql_type: 'date'}, {name: 'year', dtype: 'Int64'}], steps: [{label: 'Custom Python', code: "def transform(df):\\n    df['year'] = df['day'].dt.year\\n    return df", enabled: true}]})""")
    time.sleep(0.4)
    ask(driver, "add month name")
    ctx = driver.execute_script("return window.__asks[window.__asks.length - 1].context")
    assert ctx.startswith("Mode: COMMAND.") and "Table: l3test.orders" in ctx and "year (Int64)" in ctx and "1. Custom Python" in ctx and "new code runs AFTER these" in ctx
    assert "df['year'] = df['day'].dt.year" in ctx and len(ctx) < 4000
    driver.execute_script("localStorage.removeItem('toolbox_helper_mode')")
    driver.execute_script("location.hash = '#/tool/sql-studio'")
    wait(driver, "return getComputedStyle(document.getElementById('hlpMode')).display !== 'none'")                              # other tools keep the switch
