import io
import json
import re
import subprocess
import wave

import pytest

from ao3reader.audiobook import (
    Rendered,
    ffmetadata,
    ffmpeg_path,
    format_duration,
    make_audiobook,
    safe_filename,
    speak_to_wav,
)
from ao3reader.parse import parse_work
from ao3reader.script import Line, Track, build_tracks

from conftest import fixture_html


def test_speak_to_wav_adds_each_pause(tmp_path, voice):
    track = Track("t", [Line("one two", 0.5), Line("three", 1.0)])
    path = tmp_path / "t.wav"
    frames = speak_to_wav(track, voice, path)

    expected = round(0.1 * 24000) + round(0.5 * 24000) + round(0.05 * 24000) + 24000
    assert frames == expected
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 24000)
        assert w.getnframes() == expected
    assert voice.spoken == ["one two", "three"]


def test_ffmetadata_escapes_and_times_chapters(tmp_path):
    rendered = [
        Rendered(Track("Introduction", []), tmp_path / "a", 1500, False),
        Rendered(Track("Chapter 1: A=B; #1", []), tmp_path / "b", 2500, False),
    ]
    text = ffmetadata(rendered, {"title": "Semi;colon", "artist": "x"})

    assert text.splitlines() == [
        ";FFMETADATA1",
        "title=Semi\\;colon",
        "artist=x",
        "[CHAPTER]", "TIMEBASE=1/1000", "START=0", "END=1500", "title=Introduction",
        "[CHAPTER]", "TIMEBASE=1/1000", "START=1500", "END=4000", "title=Chapter 1: A\\=B\\; \\#1",
    ]


def test_safe_filename():
    assert safe_filename('What "if"? / A: B') == "What if A B"
    assert safe_filename("...") == "Untitled"
    assert len(safe_filename("x" * 500)) == 120


def test_format_duration():
    assert format_duration(65) == "1m 05s"
    assert format_duration(3 * 3600 + 7 * 60 + 20) == "3h 07m"


def probe(path):
    """Chapter titles and the metadata ffmpeg reads back from a file."""
    result = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", str(path), "-f", "ffmetadata", "-"],
        capture_output=True, text=True,
    )
    return result.stdout


def test_m4b_has_a_chapter_per_track_and_reuses_finished_chapters(tmp_path, voice):
    work = parse_work(fixture_html("multi_chapter.html"))
    tracks = build_tracks(work)
    store = tmp_path / "cache"

    out = make_audiobook(work, tracks, voice, tmp_path / "out", store=store, stream=io.StringIO())

    assert out.name == "The Lighthouse Keeper's Apprentice - quietquill and Second_Pen.m4b"
    meta = probe(out)
    assert re.findall(r"^title=(.*)$", meta, re.M) == [
        "The Lighthouse Keeper's Apprentice",
        "Introduction",
        "Chapter 1: The Storm",
        "Chapter 2",
        "Chapter 3: What the Light Saw",
    ]
    assert "artist=quietquill and Second_Pen" in meta
    assert "comment=https://archiveofourown.org/works/987654" in meta

    # A second run speaks nothing new; a changed chapter is the only one redone
    first_run = len(voice.spoken)
    log = io.StringIO()
    make_audiobook(work, tracks, voice, tmp_path / "out", store=store, stream=log)
    assert len(voice.spoken) == first_run
    assert log.getvalue().count("(already made)") == 4

    tracks[-1].lines.append(Line("A new paragraph.", 0.6))
    make_audiobook(work, tracks, voice, tmp_path / "out", store=store, stream=io.StringIO())
    assert len(voice.spoken) == first_run + len(tracks[-1].lines)


def test_mp3_folder_has_numbered_tagged_files(tmp_path, voice):
    work = parse_work(fixture_html("one_shot.html"))
    out = make_audiobook(
        work, build_tracks(work), voice, tmp_path, fmt="mp3",
        store=tmp_path / "cache", stream=io.StringIO(),
    )

    assert out.is_dir()
    files = sorted(p.name for p in out.iterdir())
    assert files == ["01 Introduction.mp3", "02 Tea for Two.mp3"]
    meta = probe(out / files[1])
    assert "track=2/2" in meta and "album=Tea for Two" in meta


def test_cache_entries_record_duration(tmp_path, voice):
    work = parse_work(fixture_html("one_shot.html"))
    store = tmp_path / "cache"
    make_audiobook(work, build_tracks(work), voice, tmp_path, store=store, stream=io.StringIO())

    infos = [json.loads(p.read_text()) for p in store.glob("*.json")]
    assert sorted(i["title"] for i in infos) == ["Introduction", "Tea for Two"]
    assert all(i["duration_ms"] > 0 for i in infos)


def test_unknown_format(tmp_path, voice):
    work = parse_work(fixture_html("one_shot.html"))
    with pytest.raises(ValueError, match="Format"):
        make_audiobook(work, build_tracks(work), voice, tmp_path, fmt="flac")
