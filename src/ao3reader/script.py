"""What gets read aloud: a work turned into tracks of speakable lines with pauses."""

import re
from dataclasses import dataclass, field, replace

from bs4 import Tag

from .clean import Pronunciations, is_scene_break, paragraphs, speakable
from .parse import Work

# Seconds of silence after each kind of line
LINE_BREAK = 0.3
PARAGRAPH = 0.6
HEADING = 1.0
SECTION = 1.2
SCENE_BREAK = 1.6
TRACK_END = 2.0

WORDS_PER_MINUTE = 160


@dataclass(frozen=True)
class Line:
    text: str
    pause: float


@dataclass
class Track:
    """One chapter of the audiobook."""

    title: str
    lines: list[Line]

    @property
    def words(self) -> int:
        return sum(len(line.text.split()) for line in self.lines)


@dataclass
class Options:
    summary: bool = True
    notes: bool = False
    # Chapter numbers to include; None means all of them
    chapters: set[int] | None = None
    pronunciations: Pronunciations = field(default_factory=Pronunciations)


def build_tracks(work: Work, options: Options | None = None) -> list[Track]:
    options = options or Options()
    reader = _Reader(options.pronunciations)
    chapters = [
        c for c in work.chapters if options.chapters is None or c.number in options.chapters
    ]
    one_shot = len(work.chapters) == 1
    last = work.chapters[-1]
    tracks = []

    if options.chapters is None or work.chapters[0].number in options.chapters:
        intro = reader.lines([work.title, f"By {work.author}"], pause=HEADING)
        if options.summary:
            intro += reader.section("Summary", work.summary)
        if options.notes:
            intro += reader.section("Author's note", work.notes)
        tracks.append(Track("Introduction", intro))

    for chapter in chapters:
        lines = [] if one_shot else reader.lines([_spoken_heading(chapter.title)], pause=HEADING)
        if options.summary:
            lines += reader.section("Chapter summary", chapter.summary)
        if options.notes:
            lines += reader.section("Author's note", chapter.notes)
        lines += reader.html(chapter.body)
        if options.notes:
            lines += reader.section("End note", chapter.end_notes)
            if chapter is last:
                lines += reader.section("End of work note", work.end_notes)
        tracks.append(Track(chapter.title, lines))

    for track in tracks:
        if track.lines:
            track.lines[-1] = replace(track.lines[-1], pause=TRACK_END)
    return [track for track in tracks if track.lines]


def estimated_minutes(words: int, speed: float = 1.0) -> float:
    return words / (WORDS_PER_MINUTE * speed)


def notices(work: Work, voice: str | None = None) -> list[str]:
    """Things worth telling the listener before the reading starts."""
    found = []
    have = len(work.chapters)
    if work.posted_chapters and have < work.posted_chapters:
        found.append(
            f"This page only has {have} of the {work.posted_chapters} chapters. "
            "Save the page again after clicking 'Entire Work' to get them all."
        )
    if voice and voice[:1] in "ab" and work.language and work.language != "English":
        found.append(
            f"This work is in {work.language} but the voice {voice} speaks English, "
            "so pick a voice for that language."
        )
    return found


def parse_chapters(spec: str, last: int) -> set[int]:
    """'1-3,5,8-' -> {1, 2, 3, 5, 8, ..., last}"""
    chosen: set[int] = set()
    for part in spec.split(","):
        match = re.fullmatch(r"\s*(\d+)\s*(?:(-)\s*(\d+)?)?\s*", part)
        if not match:
            raise ValueError(f"Can't read chapters {spec!r}; use something like 1-3,5,8-")
        start = int(match.group(1))
        end = int(match.group(3)) if match.group(3) else (last if match.group(2) else start)
        if start < 1 or end < start:
            raise ValueError(f"Can't read chapters {spec!r}; use something like 1-3,5,8-")
        chosen.update(range(start, end + 1))
    return chosen


def _spoken_heading(title: str) -> str:
    # "Chapter 3: The Return" reads better with a full stop than a colon
    return re.sub(r"^(Chapter \d+)\s*:\s*", r"\1. ", title)


class _Reader:
    def __init__(self, pronunciations: Pronunciations):
        self.pronunciations = pronunciations

    def say(self, text: str) -> str:
        spoken = speakable(text)
        if spoken and spoken[-1] not in ".!?…—\"”’'":
            spoken = spoken.rstrip(",;:") + "."
        return self.pronunciations(spoken) if spoken else ""

    def lines(self, texts: list[str], pause: float) -> list[Line]:
        return [Line(spoken, pause) for text in texts if (spoken := self.say(text))]

    def section(self, label: str, html: Tag | None) -> list[Line]:
        body = self.html(html)
        if not body:
            return []
        body[-1] = replace(body[-1], pause=SECTION)
        return [Line(f"{label}.", PARAGRAPH), *body]

    def html(self, root: Tag | None) -> list[Line]:
        out: list[Line] = []
        for paragraph in paragraphs(root):
            for i, text in enumerate(paragraph):
                if is_scene_break(text):
                    if out:
                        out[-1] = replace(out[-1], pause=max(out[-1].pause, SCENE_BREAK))
                    continue
                if spoken := self.say(text):
                    out.append(Line(spoken, LINE_BREAK if i < len(paragraph) - 1 else PARAGRAPH))
        return out
