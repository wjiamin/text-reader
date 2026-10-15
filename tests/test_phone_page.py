"""The phone reader (phone/index.html), driven in a real browser with a stand-in voice.

Needs Playwright and a Chromium it can launch. JSZip loads from the CDN unless
JSZIP_PATH points at a local copy of jszip.min.js 3.10.1.
"""

import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

from make_epub import multi_chapter, one_shot

sync_api = pytest.importorskip("playwright.sync_api")

PAGE = Path(__file__).parents[1] / "phone" / "index.html"
JSZIP_URL = "https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"

# Records what would be said instead of saying it, and finishes each line quickly
FAKE_SPEECH = """
window.__spoken = [];
window.__speakMs = 5;
window.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; this.rate = 1; } };
const voices = [
  { name: "Samantha", voiceURI: "com.apple.voice.compact.en-US.Samantha", lang: "en-US", localService: true },
  { name: "Ava (Premium)", voiceURI: "com.apple.voice.premium.en-US.Ava", lang: "en-US", localService: true },
  { name: "Zarvox", voiceURI: "com.apple.speech.synthesis.voice.Zarvox", lang: "en-US", localService: true },
];
const fake = {
  speaking: false, pending: false, current: null,
  getVoices() { return voices; },
  speak(u) {
    window.__spoken.push({ text: u.text, voice: u.voice ? u.voice.name : null });
    this.speaking = true;
    this.current = u;
    setTimeout(() => {
      if (this.current !== u) return;
      this.speaking = false;
      this.current = null;
      u.onend && u.onend({});
    }, window.__speakMs);
  },
  cancel() {
    const u = this.current;
    this.current = null;
    this.speaking = false;
    if (u && u.onerror) u.onerror({ error: "interrupted" });
  },
  pause() {}, resume() {}, addEventListener() {},
};
Object.defineProperty(window, "speechSynthesis", { value: fake, configurable: true });
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves the page inside the same skeleton the artifact host wraps it in."""

    def do_GET(self):
        if self.path.split("?")[0] != "/":
            return super().do_GET()
        body = (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            "</head><body>" + PAGE.read_text(encoding="utf-8") + "</body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory="."))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        executable = os.environ.get("CHROMIUM_PATH")
        try:
            launched = p.chromium.launch(executable_path=executable) if executable else p.chromium.launch()
        except Exception as error:  # no browser installed
            pytest.skip(f"Chromium isn't available: {error}")
        yield launched
        launched.close()


@pytest.fixture
def page(browser, site):
    context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    context.add_init_script(FAKE_SPEECH)
    if os.environ.get("JSZIP_PATH"):
        context.route(JSZIP_URL, lambda route: route.fulfill(
            path=os.environ["JSZIP_PATH"], content_type="application/javascript"))
    context.route("https://fonts.googleapis.com/**", lambda route: route.abort())
    errors = []
    tab = context.new_page()
    tab.on("pageerror", lambda error: errors.append(str(error)))
    tab.goto(site)
    tab.errors = errors
    yield tab
    assert errors == []
    context.close()


def spoken(page):
    return [line["text"] for line in page.evaluate("window.__spoken")]


def open_epub(page, path):
    page.set_input_files("#epub", str(path))
    page.wait_for_selector("#reader-view:not([hidden])")


def read_to_end(page):
    page.click("#play")
    page.wait_for_function("document.querySelector('#where').textContent.includes('end of the story')")


def test_reads_an_ao3_epub_in_order_skipping_notes(page, tmp_path):
    open_epub(page, multi_chapter(tmp_path / "work.epub"))
    assert page.inner_text("#heading") == "The Lighthouse Keeper's Apprentice"
    assert page.eval_on_selector_all("#chapter option", "els => els.map(e => e.textContent)") == [
        "1. Chapter 1: The Storm",
        "2. Chapter 2",
    ]
    text = page.inner_text("#text")
    assert "Posted originally" not in text and "Rating:" not in text
    assert "AUTHOR'S NOTE · NOT READ ALOUD" in text.upper()

    read_to_end(page)
    assert spoken(page) == [
        "The Lighthouse Keeper's Apprentice.",
        "By quietquill.",
        "Summary.",
        "A storm, a lamp that won't stay lit.",
        "Chapter 1. The Storm.",
        "The lamp went out at exactly the wrong moment.",
        "“No,” Wren groaned. “Not again!”",
        "By morning the sea had calmed.",
        "The gulls were back.",
        "Chapter 2.",
        "Summary.",
        "Wren climbs the stairs.",
        "There were one hundred and twelve steps.",
        "Wren counted every one of them.",
    ]
    # The best installed voice is chosen, and novelty voices are left out
    assert {line["voice"] for line in page.evaluate("window.__spoken")} == {"Ava (Premium)"}
    voices = page.eval_on_selector_all("#voice option", "els => els.map(e => e.textContent)")
    assert not any("Zarvox" in v for v in voices)


def test_authors_notes_when_asked_for(page, tmp_path):
    open_epub(page, multi_chapter(tmp_path / "work.epub"))
    page.click("#settings summary")
    page.check("#opt-notes")
    read_to_end(page)
    said = spoken(page)
    assert said[said.index("Author's note.") + 1] == "Thank you to my beta!"
    assert "This one was hard to write." in said
    assert said[-2:] == ["End note.", "That's all for now."]


def test_place_is_saved_and_resumed(page, tmp_path):
    open_epub(page, multi_chapter(tmp_path / "work.epub"))
    page.evaluate("window.__speakMs = 300")
    page.click("#play")
    page.wait_for_function("window.__spoken.length >= 7")
    page.click("#play")  # pause
    stopped_on = spoken(page)[-1]
    assert stopped_on == "“No,” Wren groaned. “Not again!”"

    page.reload()
    page.wait_for_selector(".book")
    assert "Chapter 1 of 2" in page.inner_text(".book-progress")
    page.click("[data-open]")
    page.wait_for_selector("#reader-view:not([hidden])")
    assert page.inner_text("#text .current") == "“Nooo,” Wren groaned. “Not again!!!”"

    page.evaluate("window.__speakMs = 5; window.__spoken = []")
    page.click("#play")
    page.wait_for_function("window.__spoken.length >= 2")
    assert spoken(page)[0] == stopped_on


def test_tap_a_paragraph_to_read_from_there(page, tmp_path):
    open_epub(page, multi_chapter(tmp_path / "work.epub"))
    page.evaluate("window.__speakMs = 200")
    page.click("text=By morning the sea had calmed.")
    page.wait_for_function("window.__spoken.length >= 1")
    assert spoken(page)[0] == "By morning the sea had calmed."
    page.click("#play")


def test_one_shot_with_renamed_markup(page, tmp_path):
    open_epub(page, one_shot(tmp_path / "tea.epub"))
    assert page.is_hidden("#chapter-pick")
    read_to_end(page)
    assert spoken(page) == [
        "Tea for Two.",
        "By Ash Grey.",
        "Summary.",
        "Two people, one kettle.",
        "The kettle sang. Neither of them moved to get it.",
        "“Your turn,” said Ash.",
    ]


def test_shelf_remembers_stories_and_removes_them(page, tmp_path):
    open_epub(page, one_shot(tmp_path / "tea.epub"))
    page.click("#back")
    page.reload()
    page.wait_for_selector(".book")
    assert page.inner_text(".book-title") == "Tea for Two"
    page.click("[data-remove]")
    page.click("[data-remove]")
    page.wait_for_selector("#empty:not([hidden])")


def test_sample_story_and_bad_files(page, tmp_path):
    bad = tmp_path / "not.epub"
    bad.write_text("hello")
    page.set_input_files("#epub", str(bad))
    page.wait_for_selector("#open-error:not([hidden])")
    assert "isn't an EPUB" in page.inner_text("#open-error")

    page.click("#sample")
    page.wait_for_selector("#reader-view:not([hidden])")
    assert page.eval_on_selector_all("#chapter option", "els => els.length") == 2
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
