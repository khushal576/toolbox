"""Open every page in headless Chromium and fail on JavaScript errors (console SEVERE)."""

import shutil
import time

import pytest

from conftest import BASE_URL, mounted_tools

pytestmark = pytest.mark.browser

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
DRIVER = shutil.which("chromedriver")
IGNORE = ("favicon.ico",)  # browsers request it automatically; not a page bug


@pytest.fixture(scope="module")
def driver():
    if not (CHROMIUM and DRIVER):
        pytest.skip("headless browser checks need chromium + chromedriver")
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    o = Options()
    o.binary_location = CHROMIUM
    for arg in ("--headless=new", "--no-sandbox", "--disable-gpu", "--window-size=1400,900"):
        o.add_argument(arg)
    o.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    d = webdriver.Chrome(options=o, service=Service(DRIVER))
    yield d
    d.quit()


@pytest.mark.parametrize("path", ["/"] + [f"/tools/{t}/" for t in mounted_tools()])
def test_page_has_no_js_errors(driver, path):
    driver.get_log("browser")  # clear logs from the previous page
    driver.get(BASE_URL + path)
    end = time.time() + 10
    while driver.execute_script("return document.readyState") != "complete" and time.time() < end:
        time.sleep(0.1)
    time.sleep(0.5)  # let on-load fetches finish
    errors = [e["message"] for e in driver.get_log("browser")
              if e["level"] == "SEVERE" and not any(i in e["message"] for i in IGNORE)]
    assert not errors, f"JavaScript errors on {path}:\n" + "\n".join(errors)


def _wait(driver, js, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if driver.execute_script(js):
            return True
        time.sleep(0.1)
    return False


def test_workspace_opens_tool_in_tab_and_lists_settings(driver):
    """Workspace UI (roadmap A4): sidebar → tab with the tool in an iframe; settings table; search filter."""
    driver.execute_script("try { localStorage.clear(); } catch (e) {}")
    driver.get(BASE_URL + "/")
    assert _wait(driver, "return document.querySelectorAll('#nav [data-open]').length > 5")
    # the sidebar re-renders when the status refresh lands, so click the CURRENT element via JS
    driver.execute_script("document.querySelector('#nav [data-open=\"encode-decode\"]').click()")
    assert _wait(driver, "return !!document.querySelector('#pane-tool-encode-decode.active iframe')")
    assert driver.execute_script("return location.hash") == "#/tool/encode-decode"
    assert driver.find_elements("css selector", '#tabList [data-tab="encode-decode"]')
    src = driver.execute_script("return document.querySelector('#pane-tool-encode-decode iframe').getAttribute('src')")
    assert src == "/tools/encode-decode/"

    driver.execute_script("document.querySelector('#nav [data-open=\"settings\"]').click()")
    assert _wait(driver, "return document.querySelectorAll('#rows [data-toggle]').length >= 20")

    q = driver.find_element("id", "q")
    q.send_keys("latex")
    names = driver.execute_script("return [...document.querySelectorAll('#nav [data-open]')].map(e => e.dataset.open)")
    assert "latex-pdf" in names and "encode-decode" not in names
    errors = [e["message"] for e in driver.get_log("browser") if e["level"] == "SEVERE" and "favicon" not in e["message"]]
    assert not errors, errors


def test_datadiff_large_input_runs_as_a_background_job(driver):
    """Roadmap D2: > 2 MB of input → the page submits a job, polls it, renders the stored result."""
    driver.get(f"{BASE_URL}/tools/datadiff-pro/")
    driver.execute_script("""
        const rows = n => Array.from({length: n}, (_, i) => ({id: i, name: 'name-' + i, amount: i * 1.5, note: 'x'.repeat(30)}));
        const left = rows(25000), right = rows(25000);
        for (const i of [3, 777, 24999]) right[i].amount += 1;
        document.getElementById('left-data').value = JSON.stringify(left);
        document.getElementById('right-data').value = JSON.stringify(right);
        document.getElementById('left-format').value = 'json';
        document.getElementById('right-format').value = 'json';
        window.__sawBackground = false;
        new MutationObserver(() => { if (document.getElementById('bg-status').textContent) window.__sawBackground = true; })
          .observe(document.getElementById('bg-status'), {childList: true, characterData: true, subtree: true});
        document.getElementById('btn-compare').click();
    """)
    deadline = time.time() + 120
    while time.time() < deadline:
        if driver.find_element("id", "count-mismatch").text == "3":
            break
        time.sleep(0.5)
    assert driver.find_element("id", "count-mismatch").text == "3", "background compare result not rendered"
    assert driver.execute_script("return window.__sawBackground"), "the background status never showed"


def test_status_tab_renders(driver):
    """Roadmap E1: the Status tab fills its tables without JavaScript errors."""
    driver.get(f"{BASE_URL}/#/status")
    deadline = time.time() + 30
    while time.time() < deadline and "Updated" not in driver.find_element("id", "stUpdated").text:
        time.sleep(0.5)
    assert len(driver.find_elements("css selector", "#stContainers tr")) >= 5
    severe = [l for l in driver.get_log("browser") if l["level"] == "SEVERE" and not any(i in l["message"] for i in IGNORE)]
    assert not severe, severe
