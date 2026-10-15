"""A web page for making audiobooks: paste a link, listen as each chapter is ready.

It runs on your own computer. A phone on the same Wi-Fi can use it too, through
a link with a private key (shown as a QR code), so nobody else on the network
can.
"""

import hmac
import json
import queue
import re
import secrets
import socket
import threading
import time
import traceback
import uuid
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

import segno

from .audiobook import Rendered, format_duration, render, write_audiobook
from .fetch import FetchError, fetch_work, parse_work_id
from .parse import ParseError, parse_work
from .paths import cache_dir
from .script import Options, build_tracks, estimated_minutes, notices, parse_chapters
from .tts import DEFAULT_VOICE, RECOMMENDED_VOICES, KokoroVoice, Voice

BITRATE = "64k"
KEY_COOKIE = "ao3reader_key"
MAX_UPLOAD = 50 * 1024 * 1024
FINISHED = ("done", "failed", "stopped")


def default_library() -> Path:
    return Path.home() / "AO3 Audiobooks"


class Stopped(Exception):
    pass


@dataclass
class TrackState:
    title: str
    words: int
    state: str = "waiting"  # waiting, reading, ready
    progress: float = 0.0
    audio: str | None = None
    seconds: float | None = None


@dataclass
class Job:
    link: str | None
    html: str | None
    voice: str = DEFAULT_VOICE
    speed: float = 1.0
    summary: bool = True
    notes: bool = False
    chapters: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    # queued, fetching, preparing, reading, packaging, done, failed, stopped
    state: str = "queued"
    message: str = "Waiting for the reading before it to finish"
    title: str | None = None
    author: str | None = None
    url: str | None = None
    warnings: list[str] = field(default_factory=list)
    tracks: list[TrackState] = field(default_factory=list)
    download: str | None = None
    error: str | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    # How fast this computer reads, for the time-left estimate
    measured_words: float = 0.0
    measured_seconds: float = 0.0
    current: int | None = None
    current_started: float = 0.0

    def to_json(self) -> dict:
        total = sum(t.words for t in self.tracks)
        done = sum(t.words * (1 if t.state == "ready" else t.progress) for t in self.tracks)
        return {
            "id": self.id,
            "state": self.state,
            "message": self.message,
            "title": self.title,
            "author": self.author,
            "url": self.url,
            "voice": self.voice,
            "words": total,
            "length": format_duration(estimated_minutes(total, self.speed) * 60) if total else None,
            "progress": done / total if total else 0,
            "left": self._time_left(total - done),
            "warnings": self.warnings,
            "tracks": [vars(t) for t in self.tracks],
            "download": self.download,
            "error": self.error,
        }

    def _time_left(self, words_left: float) -> str | None:
        if self.state != "reading":
            return None
        words, seconds = self.measured_words, self.measured_seconds
        if self.current is not None:
            track = self.tracks[self.current]
            words += track.words * track.progress
            seconds += time.monotonic() - self.current_started
        if seconds < 20 or words <= 0:
            return None
        return format_duration(words_left / (words / seconds))


class App:
    """The jobs, and the one worker that reads them in turn."""

    def __init__(
        self,
        library: Path,
        store: Path | None = None,
        voice_factory: Callable[[str, float], Voice] = KokoroVoice,
        fetch: Callable[[int], str] = fetch_work,
    ):
        self.library = library
        self.store = store or cache_dir() / "audio"
        self.voice_factory = voice_factory
        self.fetch = fetch
        self.phone_url: str | None = None
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.queue: queue.Queue[Job] = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, data: dict) -> Job:
        link = str(data.get("link") or "").strip() or None
        html = data.get("html") or None
        if not link and not html:
            raise ValueError("Paste a link to a work first.")
        if link and not html:
            parse_work_id(link)  # a bad link is an error now, not after queueing
        voice = str(data.get("voice") or DEFAULT_VOICE)
        if not re.fullmatch(r"[a-z]{2}_[a-z]+", voice):
            raise ValueError(f"There's no voice called {voice!r}.")
        try:
            speed = float(data.get("speed", 1.0))
        except (TypeError, ValueError):
            raise ValueError("Speed must be a number.") from None
        if not 0.5 <= speed <= 2.0:
            raise ValueError("Speed must be between 0.5 and 2.0.")
        chapters = str(data.get("chapters") or "").strip()
        if chapters:
            parse_chapters(chapters, last=10_000)
        job = Job(
            link=link,
            html=str(html) if html else None,
            voice=voice,
            speed=speed,
            summary=bool(data.get("summary", True)),
            notes=bool(data.get("notes", False)),
            chapters=chapters,
        )
        with self.lock:
            self.jobs[job.id] = job
        self.queue.put(job)
        return job

    def stop(self, job_id: str) -> None:
        with self.lock:
            if job := self.jobs.get(job_id):
                job.stop.set()
                if job.state == "queued":
                    job.state, job.message = "stopped", "Stopped"

    def snapshot(self, for_computer: bool = False) -> dict:
        with self.lock:
            jobs = [job.to_json() for job in reversed(self.jobs.values())]
        state = {
            "jobs": jobs,
            "library": self.library_files(),
            "voices": [{"id": k, "label": v} for k, v in RECOMMENDED_VOICES.items()],
            "default_voice": DEFAULT_VOICE,
        }
        if for_computer and self.phone_url:
            state["phone"] = {"url": self.phone_url, "qr": _qr_svg(self.phone_url)}
        return state

    def library_files(self) -> list[dict]:
        if not self.library.is_dir():
            return []
        books = sorted(self.library.glob("*.m4b"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [
            {"name": p.stem, "size_mb": round(p.stat().st_size / 2**20, 1), "url": f"/files/{quote(p.name)}"}
            for p in books
        ]

    def library_file(self, name: str) -> Path | None:
        path = self.library / name
        if Path(name).name != name or path.suffix != ".m4b" or not path.is_file():
            return None
        return path

    def _worker(self) -> None:
        while True:
            job = self.queue.get()
            if job.stop.is_set():
                continue
            try:
                self._read(job)
            except Stopped:
                self._set(job, state="stopped", message="Stopped. The chapters already read are kept.")
            except (FetchError, ParseError, ValueError, RuntimeError, OSError) as error:
                self._set(job, state="failed", message="Couldn't make this one", error=str(error))
            except Exception as error:  # keep the worker alive for the next job
                traceback.print_exc()
                self._set(job, state="failed", message="Something went wrong", error=repr(error))
            finally:
                job.html = None  # saved pages can be large
                job.current = None

    def _read(self, job: Job) -> None:
        if job.html:
            self._set(job, state="fetching", message="Reading the saved page")
            work = parse_work(job.html)
        else:
            work_id = parse_work_id(job.link)
            self._set(job, state="fetching", message="Getting the work from AO3")
            work = parse_work(self.fetch(work_id), work_id=work_id)

        chosen = parse_chapters(job.chapters, work.chapters[-1].number) if job.chapters else None
        tracks = build_tracks(work, Options(summary=job.summary, notes=job.notes, chapters=chosen))
        if not tracks:
            raise ValueError("There's nothing to read in the chosen chapters.")
        self._set(
            job,
            state="preparing",
            message="Getting the voice ready (the very first time, this downloads about 340 MB)",
            title=work.title,
            author=work.author,
            url=work.url,
            warnings=notices(work, job.voice),
            tracks=[TrackState(t.title, t.words) for t in tracks],
        )
        voice = self.voice_factory(job.voice, job.speed)
        voice.load()

        rendered: list[Rendered] = []
        for index, track in enumerate(tracks):
            if job.stop.is_set():
                raise Stopped
            state = job.tracks[index]
            started = time.monotonic()
            self._set(job, state="reading", message=f"Reading {track.title}", current=index,
                      current_started=started)
            with self.lock:
                state.state = "reading"

            def progress(done: float, state: TrackState = state) -> None:
                if job.stop.is_set():
                    raise Stopped
                with self.lock:
                    state.progress = done

            result = render(track, voice, "m4b", BITRATE, self.store, progress)
            with self.lock:
                state.state, state.progress = "ready", 1.0
                state.audio = f"/audio/{result.path.name}"
                state.seconds = result.duration_ms / 1000
                job.current = None
                if not result.cached:
                    job.measured_words += track.words
                    job.measured_seconds += time.monotonic() - started
            rendered.append(result)

        self._set(job, state="packaging", message="Putting the audiobook together")
        suffix = f" (chapters {job.chapters})" if job.chapters else ""
        out = write_audiobook(work, rendered, self.library, "m4b", suffix)
        self._set(job, state="done", message="Finished", download=f"/files/{quote(out.name)}")

    def _set(self, job: Job, **changes) -> None:
        with self.lock:
            for name, value in changes.items():
                setattr(job, name, value)


def make_handler(app: App, key: str, hosts: set[str]) -> type[BaseHTTPRequestHandler]:
    page = (files("ao3reader") / "static" / "index.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ao3-reader"

        def log_message(self, format, *args) -> None:
            pass

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if not self._allowed(url):
                return
            if url.path == "/":
                self._send(200, page, "text/html; charset=utf-8")
            elif url.path == "/api/state":
                self._json(app.snapshot(for_computer=self._from_this_computer()))
            elif match := re.fullmatch(r"/audio/([0-9a-f]{32}\.m4a)", url.path):
                self._file(app.store / match.group(1))
            elif url.path.startswith("/files/") and (
                book := app.library_file(unquote(url.path[len("/files/"):]))
            ):
                self._file(book, download="download" in parse_qs(url.query))
            else:
                self._send(404, b"Not found", "text/plain")

        def do_POST(self) -> None:
            url = urlsplit(self.path)
            if not self._allowed(url):
                return
            # Only this page may post: a JSON body can't be sent cross-site without permission
            origin = self.headers.get("Origin")
            if self.headers.get_content_type() != "application/json" or (
                origin and urlsplit(origin).netloc != self.headers.get("Host")
            ):
                return self._json({"error": "Not allowed"}, 403)
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD:
                return self._json({"error": "That file is too big."}, 413)
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"error": "Couldn't read the request."}, 400)

            if url.path == "/api/jobs":
                try:
                    job = app.submit(data)
                except ValueError as error:
                    return self._json({"error": str(error)}, 400)
                self._json({"id": job.id}, 201)
            elif match := re.fullmatch(r"/api/jobs/(\w+)/stop", url.path):
                app.stop(match.group(1))
                self._json({"ok": True})
            else:
                self._json({"error": "Not found"}, 404)

        def _from_this_computer(self) -> bool:
            return self.client_address[0] in ("127.0.0.1", "::1")

        def _allowed(self, url) -> bool:
            if self._from_this_computer():
                # Another website can't reach this page through a made-up address
                if self.headers.get("Host") in hosts:
                    return True
                self._send(400, b"Unexpected host", "text/plain")
                return False
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            if KEY_COOKIE in cookie and hmac.compare_digest(cookie[KEY_COOKIE].value, key):
                return True
            given = parse_qs(url.query).get("key", [""])[0]
            if given and hmac.compare_digest(given, key):
                # Remember this phone, and drop the key from the address bar
                self.send_response(303)
                self.send_header("Location", url.path or "/")
                self.send_header(
                    "Set-Cookie",
                    f"{KEY_COOKIE}={key}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax",
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False
            self._send(
                403,
                b"This page needs its private link. Scan the QR code on the computer "
                b"running ao3-reader, or open the link it printed.",
                "text/plain; charset=utf-8",
            )
            return False

        def _json(self, data: dict, status: int = 200) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path, download: bool = False) -> None:
            """Send audio with support for byte ranges, which phones need to play and seek."""
            if not path.is_file():
                return self._send(404, b"Not found", "text/plain")
            size = path.stat().st_size
            start, end, status = 0, size - 1, 200
            if match := re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip()):
                first, last = match.groups()
                if first:
                    start, end = int(first), min(int(last), size - 1) if last else size - 1
                elif last:
                    start = max(size - int(last), 0)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
            self.send_response(status)
            self.send_header("Content-Type", "audio/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if download:
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename=\"audiobook.m4b\"; filename*=UTF-8''{quote(path.name)}",
                )
            self.end_headers()
            try:
                with path.open("rb") as source:
                    source.seek(start)
                    remaining = end - start + 1
                    while remaining > 0 and (chunk := source.read(min(1 << 16, remaining))):
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # players often hang up early, after reading what they need

    return Handler


def serve(
    port: int = 8000,
    phone: bool = True,
    library: Path | None = None,
    open_browser: bool = True,
    voice_factory: Callable[[str, float], Voice] = KokoroVoice,
) -> None:
    app = App(library or default_library(), voice_factory=voice_factory)
    server = _bind("0.0.0.0" if phone else "127.0.0.1", port)
    port = server.server_address[1]
    key = _access_key()
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    lan = _lan_address() if phone else None
    if lan:
        hosts.add(f"{lan}:{port}")
        app.phone_url = f"http://{lan}:{port}/?key={key}"
    server.RequestHandlerClass = make_handler(app, key, hosts)

    local = f"http://127.0.0.1:{port}/"
    print(f"AO3 Reader is open at {local}")
    print(f"Finished audiobooks are saved in {app.library}")
    if app.phone_url:
        print("\nTo use it from your phone (on the same Wi-Fi), scan this or open the link:")
        segno.make(app.phone_url).terminal(compact=True)
        print(app.phone_url)
    print("\nKeep this window open while it reads. Press Ctrl+C to quit.")
    if open_browser:
        webbrowser.open(local)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


def _bind(host: str, port: int) -> ThreadingHTTPServer:
    for candidate in range(port, port + 10):
        try:
            return ThreadingHTTPServer((host, candidate), BaseHTTPRequestHandler)
        except OSError:
            continue
    raise OSError(f"Ports {port} to {port + 9} are all in use; try --port with another number.")


def _access_key() -> str:
    """A private key for phones, kept between runs so a phone only scans once."""
    path = cache_dir() / "web-key"
    try:
        key = path.read_text().strip()
        if len(key) >= 16:
            return key
    except OSError:
        pass
    key = secrets.token_urlsafe(18)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key)
    return key


def _lan_address() -> str | None:
    """This computer's address on the local network, if it has one."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))  # no packet is sent; this only picks a route
            address = probe.getsockname()[0]
        except OSError:
            return None
    return None if address.startswith("127.") else address


def _qr_svg(text: str) -> str:
    return segno.make(text, error="m").svg_inline(dark="#111", light="#fff", omitsize=True)
