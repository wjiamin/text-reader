import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from ao3reader.fetch import FetchError
from ao3reader.web import App, _lan_address, make_handler

from conftest import FakeVoice, fixture_html

KEY = "k" * 24


class SlowVoice(FakeVoice):
    def speak(self, text):
        time.sleep(0.05)
        return super().speak(text)


@pytest.fixture
def app(tmp_path):
    return App(
        tmp_path / "library",
        store=tmp_path / "cache",
        voice_factory=lambda voice, speed: FakeVoice(),
        fetch=lambda work_id: fixture_html("multi_chapter.html"),
    )


def start(app, host="127.0.0.1"):
    server = ThreadingHTTPServer((host, 0), BaseHTTPRequestHandler)
    port = server.server_address[1]
    server.RequestHandlerClass = make_handler(app, KEY, {f"127.0.0.1:{port}", f"{host}:{port}"})
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://{host}:{port}"


@pytest.fixture
def site(app):
    server, base = start(app)
    with httpx.Client(base_url=base, timeout=10) as client:
        yield client
    server.shutdown()


def wait_for(client, job_id, states=("done", "failed", "stopped"), timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = next(j for j in client.get("/api/state").json()["jobs"] if j["id"] == job_id)
        if job["state"] in states:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job stuck in {job['state']}")


def post(client, path, data):
    return client.post(path, json=data)


def test_page_loads(site):
    response = site.get("/")
    assert response.status_code == 200
    assert "<title>AO3 Reader</title>" in response.text


def test_link_to_audiobook(site):
    response = post(site, "/api/jobs", {"link": "https://archiveofourown.org/works/987654"})
    assert response.status_code == 201
    job = wait_for(site, response.json()["id"])

    assert job["state"] == "done", job["error"]
    assert job["title"] == "The Lighthouse Keeper's Apprentice"
    assert job["url"] == "https://archiveofourown.org/works/987654"
    assert [t["title"] for t in job["tracks"]][:2] == ["Introduction", "Chapter 1: The Storm"]
    assert all(t["state"] == "ready" and t["seconds"] > 0 for t in job["tracks"])

    # Chapters play straight away, with the byte ranges phones ask for
    audio = site.get(job["tracks"][1]["audio"], headers={"Range": "bytes=0-99"})
    assert audio.status_code == 206
    assert audio.headers["Content-Type"] == "audio/mp4"
    assert len(audio.content) == 100
    assert audio.headers["Content-Range"].startswith("bytes 0-99/")

    book = site.get(job["download"] + "?download=1")
    assert book.status_code == 200
    assert "attachment" in book.headers["Content-Disposition"]
    assert book.content[4:8] == b"ftyp"

    library = site.get("/api/state").json()["library"]
    assert [b["name"] for b in library] == [
        "The Lighthouse Keeper's Apprentice - quietquill and Second_Pen"
    ]


def test_uploaded_page_and_chosen_chapters(site):
    data = {"html": fixture_html("one_shot.html"), "summary": False, "chapters": "1"}
    job = wait_for(site, post(site, "/api/jobs", data).json()["id"])

    assert job["state"] == "done", job["error"]
    assert job["download"].endswith("Tea%20for%20Two%20-%20Anonymous%20%28chapters%201%29.m4b")


def test_bad_requests_are_explained(site):
    assert post(site, "/api/jobs", {}).json()["error"] == "Paste a link to a work first."
    bad_link = post(site, "/api/jobs", {"link": "https://example.com/story"})
    assert bad_link.status_code == 400
    assert "Not an AO3 work link" in bad_link.json()["error"]
    assert post(site, "/api/jobs", {"link": "1", "speed": 9}).status_code == 400
    assert post(site, "/api/jobs", {"link": "1", "chapters": "five"}).status_code == 400


def test_failures_show_on_the_job(tmp_path):
    def blocked(work_id):
        raise FetchError("AO3's bot protection blocked the download. Save the page.")

    app = App(tmp_path, store=tmp_path / "c", voice_factory=lambda v, s: FakeVoice(), fetch=blocked)
    server, base = start(app)
    with httpx.Client(base_url=base) as client:
        job = wait_for(client, post(client, "/api/jobs", {"link": "5"}).json()["id"])
    server.shutdown()

    assert job["state"] == "failed"
    assert "bot protection" in job["error"]


def test_stopping_a_job(tmp_path):
    app = App(tmp_path, store=tmp_path / "c", voice_factory=lambda v, s: SlowVoice(),
              fetch=lambda work_id: fixture_html("multi_chapter.html"))
    server, base = start(app)
    with httpx.Client(base_url=base) as client:
        job_id = post(client, "/api/jobs", {"link": "5"}).json()["id"]
        wait_for(client, job_id, states=("reading",))
        post(client, f"/api/jobs/{job_id}/stop", {})
        job = wait_for(client, job_id)
    server.shutdown()

    assert job["state"] == "stopped"
    assert job["download"] is None


def test_other_websites_cant_post(site):
    as_form = site.post("/api/jobs", content="link=5", headers={"Content-Type": "text/plain"})
    assert as_form.status_code == 403
    cross_site = site.post("/api/jobs", json={"link": "5"}, headers={"Origin": "https://evil.example"})
    assert cross_site.status_code == 403


def test_unexpected_host_is_refused(site):
    assert site.get("/", headers={"Host": "attacker.example:80"}).status_code == 400


def test_files_outside_the_library_are_not_served(site):
    assert site.get("/files/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert site.get("/audio/notahash.m4a").status_code == 404


@pytest.mark.skipif(_lan_address() is None, reason="no network address to test from")
def test_phones_need_the_private_link(app):
    server, base = start(app, host=_lan_address())
    with httpx.Client(base_url=base) as phone:
        assert phone.get("/").status_code == 403
        assert phone.get("/?key=wrong").status_code == 403

        welcome = phone.get(f"/?key={KEY}")
        assert welcome.status_code == 303
        assert welcome.headers["Location"] == "/"
        assert phone.get("/").status_code == 200  # remembered by cookie
        assert phone.get("/api/state").json().get("phone") is None
    server.shutdown()
