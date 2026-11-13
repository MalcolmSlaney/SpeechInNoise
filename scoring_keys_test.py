"""Browser tests for static/scoring_keys.js (keyboard shortcuts for scoring).

They load the real azbio_mandarin.html test page in headless Chrome, build the
word buttons with the page's own code, and press keys. They are skipped when
Playwright or a browser is not installed, so the normal pytest run (and the
GitHub workflow) is unaffected.

    pip install playwright && playwright install chromium
    pytest scoring_keys_test.py
"""
import functools
import http.server
import threading

import pytest

from storage import relpath

playwright_api = pytest.importorskip("playwright.sync_api")

SENTENCE = "我 知道 一家 很棒的 小店 一起 去吧"


@pytest.fixture(scope="module")
def static_server():
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=relpath("static"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        launched = None
        for kwargs in ({}, {"channel": "chrome"}):
            try:
                launched = p.chromium.launch(**kwargs)
                break
            except Exception:  # browser not installed
                continue
        if launched is None:
            pytest.skip("no Chromium or Chrome available for Playwright")
        yield launched
        launched.close()


@pytest.fixture
def page(browser, static_server):
    page = browser.new_page()
    # The page calls the experiment API on load; there is no server here.
    page.route("**/api/**", lambda route: route.abort())
    page.route("**/fonts.*/**", lambda route: route.abort())
    page.goto(f"{static_server}/azbio_mandarin.html")
    page.wait_for_function("window.ScoringKeys !== undefined")
    page.evaluate("s => audio.options(s)", SENTENCE)
    yield page
    page.close()


def scores(page):
    """Per word: True (correct), False (wrong) or None (not scored yet)."""
    return page.evaluate("""() =>
        Array.from(document.querySelectorAll('.options-case > div')).map(g => {
          const on = g.querySelector('.annotation-on');
          const off = g.querySelector('.annotation-off');
          return on.checked ? true : (off.checked ? false : null);
        })""")


def test_words_are_labelled_with_their_keys(page):
    keys = page.eval_on_selector_all(
        ".option-on", "els => els.map(e => e.dataset.shortcut)")
    assert keys == ["1", "2", "3", "4", "5", "6", "7"]


def test_number_key_flips_one_word(page):
    page.keyboard.press("2")
    assert scores(page) == [None, True, None, None, None, None, None]
    page.keyboard.press("2")
    assert scores(page)[1] is False
    page.keyboard.press("2")
    assert scores(page)[1] is True


def test_all_and_none(page):
    page.keyboard.press("a")
    assert scores(page) == [True] * 7
    page.keyboard.press("n")
    assert scores(page) == [False] * 7


def test_key_past_last_word_does_nothing(page):
    page.keyboard.press("9")
    assert scores(page) == [None] * 7


def test_held_key_does_not_flip_back_and_forth(page):
    page.keyboard.down("1")
    page.keyboard.down("1")  # a repeat event
    page.keyboard.up("1")
    assert scores(page)[0] is True


def test_enter_waits_until_every_word_is_scored(page):
    page.evaluate("""() => {
        window.nextClicks = 0;
        const next = document.getElementById('next-audio');
        next.disabled = false;
        next.addEventListener('click', () => { window.nextClicks += 1; });
    }""")
    page.keyboard.press("1")
    page.keyboard.press("Enter")
    assert page.evaluate("window.nextClicks") == 0
    page.keyboard.press("a")
    page.keyboard.press("Enter")
    assert page.evaluate("window.nextClicks") == 1


def test_space_presses_play(page):
    page.evaluate("""() => {
        window.playClicks = 0;
        document.getElementById('playback').addEventListener(
            'click', () => { window.playClicks += 1; });
    }""")
    page.keyboard.press(" ")
    assert page.evaluate("window.playClicks") == 1


def test_question_mark_hides_help(page):
    assert page.is_visible("#shortcut-help")
    page.keyboard.press("?")
    assert not page.is_visible("#shortcut-help")


def test_keys_ignored_while_typing(page):
    page.evaluate("""() => {
        const box = document.createElement('input');
        box.id = 'typing'; document.body.appendChild(box);
    }""")
    page.focus("#typing")
    page.keyboard.type("1a")
    assert scores(page) == [None] * 7
