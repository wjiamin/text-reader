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
  getVoices() { return window.__voiceList || voices; },
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
window.__allVoices = voices;
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


# A stand-in for the natural voice: a little silence per word, and a record of what was made
FAKE_NATURAL = """
window.__made = [];
window.FIC_LISTENER_CONFIG = {
  make: async (text) => {
    window.__made.push(text);
    await new Promise((resolve) => setTimeout(resolve, 250));
    const words = text.split(/\\s+/).length;
    return { pcm: new Float32Array(words * 1200), rate: 24000 };
  },
};
"""


def new_page(browser, site, *scripts):
    context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    for script in scripts:
        context.add_init_script(script)
    if os.environ.get("JSZIP_PATH"):
        context.route(JSZIP_URL, lambda route: route.fulfill(
            path=os.environ["JSZIP_PATH"], content_type="application/javascript"))
    context.route("https://fonts.googleapis.com/**", lambda route: route.abort())
    errors = []
    tab = context.new_page()
    tab.on("pageerror", lambda error: errors.append(str(error)))
    tab.goto(site)
    tab.errors = errors
    return tab


@pytest.fixture
def page(browser, site):
    # The phone's own voices, as in a claude.ai page where the natural voice can't load
    tab = new_page(browser, site, FAKE_SPEECH, "window.FIC_LISTENER_CONFIG = { enabled: false };")
    yield tab
    assert tab.errors == []
    tab.context.close()


@pytest.fixture
def natural_page(browser, site):
    tab = new_page(browser, site, FAKE_SPEECH, FAKE_NATURAL)
    yield tab
    assert tab.errors == []
    tab.context.close()


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


def test_voices_that_arrive_late_are_picked_up(page, tmp_path):
    # Phones often list only the basic voice at first and add the rest a moment later
    page.evaluate("window.__voiceList = [window.__allVoices[0]]")
    open_epub(page, one_shot(tmp_path / "tea.epub"))
    page.click("#settings summary")
    assert page.eval_on_selector_all("#voice option", "els => els.map(e => e.textContent)") == [
        "Phone's default voice",
        "Samantha (en-US)",
    ]

    page.evaluate("window.__voiceList = null")
    page.wait_for_function("document.querySelector('#voice').selectedOptions[0].textContent.includes('Ava')")
    assert "2 voices" in page.inner_text("#voice-count")

    page.click("#list-voices")
    listed = page.inner_text("#all-voices")
    assert "Zarvox" in listed and "com.apple.voice.premium.en-US.Ava" in listed


EXPECTED_STORY = [
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


def test_natural_voice_reads_the_story_as_real_audio(natural_page, tmp_path):
    page = natural_page
    open_epub(page, multi_chapter(tmp_path / "work.epub"))
    assert page.input_value("#voice") == "kokoro:af_heart"
    page.click("#settings summary")
    assert page.is_visible("#natural-settings")
    assert page.is_hidden("#natural-elsewhere")

    read_to_end(page)
    assert page.evaluate("window.__made") == EXPECTED_STORY
    assert spoken(page) == []  # nothing went to the phone's own voice
    assert "listening speed" in page.inner_text("#natural-status")


def test_prepared_audio_is_kept_and_reused(natural_page, tmp_path):
    page = natural_page
    open_epub(page, multi_chapter(tmp_path / "work.epub"))
    page.click("#play")
    page.wait_for_function("window.__made.length >= 8")
    page.click("#play")  # pause
    made = page.evaluate("window.__made.length")

    page.reload()
    page.wait_for_selector(".book")
    page.click("[data-open]")
    page.wait_for_selector("#reader-view:not([hidden])")
    page.wait_for_function("document.querySelector('#natural-status').textContent.includes('ahead')")
    page.evaluate("window.__made = []")
    read_to_end(page)
    # Only what wasn't prepared before the reload had to be made again
    assert len(page.evaluate("window.__made")) <= len(EXPECTED_STORY) - made + 2
    assert page.evaluate("window.__made")[-1] == EXPECTED_STORY[-1]


def test_switching_to_a_phone_voice(natural_page, tmp_path):
    page = natural_page
    open_epub(page, one_shot(tmp_path / "tea.epub"))
    page.click("#settings summary")
    page.select_option("#voice", "com.apple.voice.premium.en-US.Ava")
    assert page.is_hidden("#natural-settings")
    read_to_end(page)
    assert spoken(page)[0] == "Tea for Two."
    assert page.evaluate("window.__made") == []


def test_inside_claude_the_natural_voice_points_elsewhere(page, tmp_path):
    open_epub(page, one_shot(tmp_path / "tea.epub"))
    page.click("#settings summary")
    values = page.eval_on_selector_all("#voice option", "els => els.map(e => e.value)")
    assert not any(v.startswith("kokoro:") for v in values)
    assert "wjiamin.github.io/text-reader" in page.inner_text("#natural-elsewhere")


def test_github_pages_copy_is_up_to_date():
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_pages", PAGE.parents[1] / "tools" / "build_pages.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    assert build.OUTPUT.read_text(encoding="utf-8") == build.render(), "run: python tools/build_pages.py"


def voice_page(browser, site, library, extra=""):
    """The page with a stand-in for the voice library, loaded the real way."""
    config = f"window.FIC_LISTENER_CONFIG = {{ library: location.origin + '/tests/fixtures/{library}', {extra} }};"
    return new_page(browser, site, FAKE_SPEECH, config)


@pytest.mark.parametrize("extra, mode", [("", "worker"), ("worker: false", "page"), ("startMs: 0", "page")])
def test_natural_voice_runs_in_a_worker_or_on_the_page(browser, site, tmp_path, extra, mode):
    page = voice_page(browser, site, "fake-kokoro.js", extra)
    open_epub(page, one_shot(tmp_path / "tea.epub"))
    read_to_end(page)
    assert page.evaluate("natural.mode") == mode
    assert spoken(page) == []
    assert page.errors == []
    page.context.close()


def test_a_stuck_voice_says_so_instead_of_waiting_forever(browser, site, tmp_path):
    page = voice_page(browser, site, "stuck-kokoro.js", "stallMs: 3000")
    open_epub(page, one_shot(tmp_path / "tea.epub"))
    page.click("#play")
    page.wait_for_function("document.querySelector('#natural-status').textContent.includes('stopped responding')")
    status = page.inner_text("#natural-status")
    assert "couldn't start on this phone" in status and "pick a phone voice" in status
    assert page.get_attribute("#play", "aria-label") == "Read aloud"
    page.context.close()


def test_a_failing_voice_says_why(browser, site, tmp_path):
    page = voice_page(browser, site, "failing-kokoro.js")
    open_epub(page, one_shot(tmp_path / "tea.epub"))
    page.click("#play")
    page.wait_for_function("document.querySelector('#natural-status').textContent.includes('Out of memory')")
    assert page.evaluate("natural.mode") == ""
    page.context.close()


def test_status_counts_while_the_voice_gets_ready(browser, site, tmp_path):
    page = voice_page(browser, site, "stuck-kokoro.js", "stallMs: 60000")
    open_epub(page, one_shot(tmp_path / "tea.epub"))
    page.click("#play")
    page.wait_for_function("/Setting up the voice.* [2-9] s/.test(document.querySelector('#natural-status').textContent)")
    page.click("#play")
    page.context.close()


SAFARI_STREAMS = "delete ReadableStream.prototype[Symbol.asyncIterator]; delete ReadableStream.prototype.values;"


def test_natural_voice_works_without_stream_looping_like_safari(browser, site, tmp_path):
    # Safari can't loop over streams with "for await"; on an iPhone the real voice
    # failed with "undefined is not a function (near '...e of A...')"
    config = "window.FIC_LISTENER_CONFIG = { library: location.origin + '/tests/fixtures/stream-kokoro.js', worker: false };"
    page = new_page(browser, site, FAKE_SPEECH, SAFARI_STREAMS, config)
    open_epub(page, one_shot(tmp_path / "tea.epub"))
    read_to_end(page)
    assert page.evaluate("natural.mode") == "page"
    assert page.errors == []
    page.context.close()


def test_prepare_the_rest_of_the_story_with_progress(natural_page, tmp_path):
    page = natural_page
    open_epub(page, multi_chapter(tmp_path / "work.epub"))
    page.wait_for_selector("#offline-card:not([hidden])")
    assert page.inner_text("#prepare-start") == "Prepare the rest"

    page.click("#prepare-start")
    page.wait_for_selector("#prepare:not([hidden])")
    page.wait_for_function("document.querySelector('#prepare-detail').textContent.includes('of 14 parts')")
    page.wait_for_function("document.querySelector('#offline-title').textContent === 'Ready to listen offline'",
                           timeout=60000)
    assert page.is_hidden("#prepare")
    assert page.evaluate("window.__made") == EXPECTED_STORY

    # Everything plays from what was prepared, with nothing more to make
    read_to_end(page)
    assert len(page.evaluate("window.__made")) == len(EXPECTED_STORY)


def test_stopping_and_carrying_on(natural_page, tmp_path):
    page = natural_page
    open_epub(page, multi_chapter(tmp_path / "work.epub"))
    page.wait_for_selector("#offline-card:not([hidden])")
    page.click("#prepare-start")
    page.wait_for_function("window.__made.length >= 3")
    page.click("#prepare-stop")
    page.wait_for_selector("#offline-card:not([hidden])")
    assert page.inner_text("#prepare-start") == "Carry on"
    assert "% of the rest is prepared" in page.inner_text("#offline-text")

    page.reload()
    page.wait_for_selector(".book")
    page.click("[data-open]")
    page.wait_for_function("document.querySelector('#prepare-start').textContent === 'Carry on'")
    page.click("#prepare-start")
    page.wait_for_function("document.querySelector('#offline-title').textContent === 'Ready to listen offline'",
                           timeout=60000)
    # Parts made before stopping weren't made again
    assert 0 < len(page.evaluate("window.__made")) < len(EXPECTED_STORY)
