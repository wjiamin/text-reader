"""Speaking tracks, keeping each finished chapter, and packaging the audiobook.

Each chapter's audio is cached under a key made from its exact text and the
voice settings. Running the same work again only speaks chapters that are new
or changed, which is what makes following a work in progress cheap.
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import numpy as np

from .parse import Work
from .paths import cache_dir
from .script import Track
from .tts import Voice

FORMATS = ("m4b", "mp3")


@dataclass
class Rendered:
    track: Track
    path: Path
    duration_ms: int
    cached: bool


def make_audiobook(
    work: Work,
    tracks: list[Track],
    voice: Voice,
    out_dir: Path,
    fmt: str = "m4b",
    bitrate: str = "64k",
    name_suffix: str = "",
    store: Path | None = None,
    stream: TextIO = sys.stderr,
) -> Path:
    """Speak every track and write the finished audiobook; returns its path."""
    if fmt not in FORMATS:
        raise ValueError(f"Format must be one of: {', '.join(FORMATS)}")
    store = store or cache_dir() / "audio"
    status = _Status(stream)
    rendered = []
    for number, track in enumerate(tracks, 1):
        label = f"[{number:>{len(str(len(tracks)))}}/{len(tracks)}] {track.title}"
        started = time.monotonic()
        result = render(
            track, voice, fmt, bitrate, store, lambda done: status.update(f"{label}  {done:.0%}")
        )
        if result.cached:
            status.done(f"{label}  (already made)")
        else:
            took = time.monotonic() - started
            speedup = result.duration_ms / 1000 / took if took else 0
            status.done(
                f"{label}  {track.words:,} words, {format_duration(result.duration_ms / 1000)} of audio "
                f"in {format_duration(took)} ({speedup:.1f}x real time)"
            )
        rendered.append(result)

    name = safe_filename(f"{work.title} - {work.author}{name_suffix}")
    tags = {
        "title": work.title,
        "album": work.title,
        "artist": work.author,
        "album_artist": work.author,
        "genre": "Audiobook",
        "comment": work.url or "",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt == "m4b":
        out = out_dir / f"{name}.m4b"
        write_m4b(rendered, out, tags)
    else:
        out = out_dir / name
        write_mp3s(rendered, out, tags)
    return out


def render(
    track: Track,
    voice: Voice,
    fmt: str,
    bitrate: str,
    store: Path,
    on_progress: Callable[[float], None] | None = None,
) -> Rendered:
    """One track's audio, from the cache when this exact text was spoken before."""
    key = track_key(track, voice, fmt, bitrate)
    audio = store / f"{key}.{_extension(fmt)}"
    info = store / f"{key}.json"
    if audio.exists() and info.exists():
        return Rendered(track, audio, json.loads(info.read_text())["duration_ms"], cached=True)

    store.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=store) as tmp:
        wav = Path(tmp) / "track.wav"
        frames = speak_to_wav(track, voice, wav, on_progress)
        encoded = Path(tmp) / audio.name
        _ffmpeg("-i", wav, "-ac", "1", *_codec(fmt), "-b:a", bitrate, encoded)
        encoded.replace(audio)
    duration_ms = round(frames * 1000 / voice.sample_rate)
    info.write_text(json.dumps({"title": track.title, "duration_ms": duration_ms}))
    return Rendered(track, audio, duration_ms, cached=False)


def track_key(track: Track, voice: Voice, fmt: str, bitrate: str) -> str:
    payload = {
        "voice": voice.key,
        "format": fmt,
        "bitrate": bitrate,
        "lines": [[line.text, line.pause] for line in track.lines],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:32]


def speak_to_wav(
    track: Track,
    voice: Voice,
    path: Path,
    on_progress: Callable[[float], None] | None = None,
) -> int:
    """Write the track as mono 16-bit audio; returns the number of samples written."""
    total_words = max(track.words, 1)
    words = frames = 0
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(voice.sample_rate)
        for line in track.lines:
            speech = np.clip(np.asarray(voice.speak(line.text), dtype=np.float32).ravel(), -1, 1)
            pcm = (speech * 32767).astype(np.int16)
            silence = np.zeros(round(line.pause * voice.sample_rate), dtype=np.int16)
            out.writeframes(pcm.tobytes() + silence.tobytes())
            frames += len(pcm) + len(silence)
            words += len(line.text.split())
            if on_progress:
                on_progress(words / total_words)
    return frames


def write_m4b(rendered: list[Rendered], out: Path, tags: dict[str, str]) -> None:
    """Join the chapters into one audiobook file with a chapter marker for each."""
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "files.txt"
        listing.write_text(
            "".join(f"file '{_concat_quote(r.path)}'\n" for r in rendered), encoding="utf-8"
        )
        chapters = Path(tmp) / "chapters.txt"
        chapters.write_text(ffmetadata(rendered, tags), encoding="utf-8")
        partial = out.with_name(out.name + ".part")
        _ffmpeg(
            "-f", "concat", "-safe", "0", "-i", listing, "-i", chapters,
            "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
            "-c", "copy", "-movflags", "+faststart", "-f", "ipod", partial,
        )
        partial.replace(out)


def write_mp3s(rendered: list[Rendered], folder: Path, tags: dict[str, str]) -> None:
    """One numbered, tagged MP3 per chapter, for players that don't do audiobooks."""
    folder.mkdir(parents=True, exist_ok=True)
    width = max(2, len(str(len(rendered))))
    for number, r in enumerate(rendered, 1):
        out = folder / f"{number:0{width}d} {safe_filename(r.track.title)}.mp3"
        partial = out.with_name(out.name + ".part")
        metadata = {**tags, "title": r.track.title, "track": f"{number}/{len(rendered)}"}
        _ffmpeg(
            "-i", r.path, "-map", "0:a", "-c", "copy", "-id3v2_version", "3",
            *[arg for key, value in metadata.items() for arg in ("-metadata", f"{key}={value}")],
            "-f", "mp3", partial,
        )
        partial.replace(out)


def ffmetadata(rendered: list[Rendered], tags: dict[str, str]) -> str:
    lines = [";FFMETADATA1", *(f"{key}={_meta_escape(value)}" for key, value in tags.items())]
    start = 0
    for r in rendered:
        end = start + r.duration_ms
        lines += [
            "[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}",
            f"title={_meta_escape(r.track.title)}",
        ]
        start = end
    return "\n".join(lines) + "\n"


def safe_filename(name: str, limit: int = 120) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name)
    name = " ".join(name.split()).strip(" .")
    return name[:limit].rstrip(" .") or "Untitled"


def ffmpeg_path() -> str:
    if found := shutil.which("ffmpeg"):
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _ffmpeg(*args) -> None:
    command = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[-2000:]}")


def _codec(fmt: str) -> list[str]:
    return ["-c:a", "aac", "-f", "ipod"] if fmt == "m4b" else ["-c:a", "libmp3lame", "-f", "mp3"]


def _extension(fmt: str) -> str:
    return "m4a" if fmt == "m4b" else "mp3"


def _concat_quote(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "'\\''")


def _meta_escape(value: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", value)


def format_duration(seconds: float) -> str:
    seconds = round(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m {seconds:02d}s"


class _Status:
    """One line per finished chapter, with a live percentage on a terminal."""

    def __init__(self, stream: TextIO):
        self.stream = stream
        self.live = stream.isatty()
        self.width = 0

    def update(self, text: str) -> None:
        if self.live:
            self.stream.write("\r" + text.ljust(self.width))
            self.stream.flush()
            self.width = len(text)

    def done(self, text: str) -> None:
        prefix = "\r" if self.live else ""
        self.stream.write(prefix + text.ljust(self.width) + "\n")
        self.stream.flush()
        self.width = 0
