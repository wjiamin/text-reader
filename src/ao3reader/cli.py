"""The ao3-reader command."""

import argparse
import re
import sys
from pathlib import Path

from . import __version__
from .audiobook import FORMATS, format_duration, make_audiobook, speak_to_wav
from .clean import Pronunciations
from .fetch import FetchError, fetch_work, parse_work_id
from .parse import ParseError, Work, parse_work
from .script import PARAGRAPH, SCENE_BREAK, Line, Options, Track, build_tracks, estimated_minutes
from .tts import DEFAULT_VOICE, LANGUAGES, MODELS, RECOMMENDED_VOICES, KokoroVoice

SAMPLE_TEXT = (
    "The castle was quiet in the way it only got after midnight. "
    "“You're still awake,” she said. It wasn't quite a question."
)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.run(args) or 0
    except KeyboardInterrupt:
        print(
            "\nStopped. Finished chapters are kept, so running the same command "
            "again carries on from there.",
            file=sys.stderr,
        )
        return 130
    except (FetchError, ParseError, ValueError, RuntimeError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _make(args: argparse.Namespace) -> None:
    work = _load(args.work)
    tracks = build_tracks(work, _options(args, work))
    if not tracks:
        raise ValueError("There's nothing to read in the chosen chapters.")
    if work.language and work.language != "English" and args.voice[:1] in "ab":
        _note(
            f"This work is in {work.language} but {args.voice} speaks English. "
            "Pick another voice with --voice (see 'ao3-reader voices')."
        )

    words = sum(track.words for track in tracks)
    minutes = estimated_minutes(words, args.speed)
    _note(f"{len(tracks)} tracks, {words:,} words, roughly {format_duration(minutes * 60)} of audio.")
    voice = KokoroVoice(args.voice, args.speed, args.model)
    voice.load()
    suffix = f" (chapters {args.chapters})" if args.chapters else ""
    out = make_audiobook(work, tracks, voice, args.out, args.format, args.bitrate, suffix)
    print(f"Done: {out}")


def _preview(args: argparse.Namespace) -> None:
    work = _load(args.work)
    for track in build_tracks(work, _options(args, work)):
        print(f"=== {track.title} ({track.words:,} words) ===\n")
        for line in track.lines:
            print(line.text)
            if line is track.lines[-1]:
                print()
            elif line.pause >= SCENE_BREAK:
                print("\n        * * *\n")
            elif line.pause >= PARAGRAPH:
                print()


def _voices(args: argparse.Namespace) -> None:
    print("English voices to try first:\n")
    for name, description in RECOMMENDED_VOICES.items():
        default = "  (default)" if name == DEFAULT_VOICE else ""
        print(f"  {name:<12} {description}{default}")
    languages = ", ".join(f"{code}_ = {lang}" for code, lang in LANGUAGES.items() if code not in "ab")
    print(
        f"\nThere are more, including other languages ({languages}).\n"
        "Hear some side by side with:  ao3-reader sample --voice af_heart --voice bm_george"
    )


def _sample(args: argparse.Namespace) -> None:
    args.out.mkdir(parents=True, exist_ok=True)
    track = Track("Sample", [Line(args.text or SAMPLE_TEXT, 0.5)])
    for name in args.voice or ["af_heart", "af_bella", "am_michael", "bf_emma", "bm_george"]:
        voice = KokoroVoice(name, args.speed, args.model)
        path = args.out / f"sample-{name}.wav"
        speak_to_wav(track, voice, path)
        print(path)


def _load(ref: str) -> Work:
    path = Path(ref).expanduser()
    if path.is_file():
        work = parse_work(path.read_text(encoding="utf-8", errors="replace"))
    else:
        work_id = parse_work_id(ref)
        _note(f"Fetching work {work_id} from AO3...")
        work = parse_work(fetch_work(work_id), work_id=work_id)

    chapters = len(work.chapters)
    _note(f"“{work.title}” by {work.author}: {chapters} chapter{'s' * (chapters != 1)}")
    if work.posted_chapters and chapters < work.posted_chapters:
        _note(
            f"This page only has {chapters} of the {work.posted_chapters} chapters. "
            "Save the page again after clicking 'Entire Work' to get them all."
        )
    return work


def _options(args: argparse.Namespace, work: Work) -> Options:
    return Options(
        summary=args.summary,
        notes=args.notes,
        chapters=parse_chapters(args.chapters, work.chapters[-1].number) if args.chapters else None,
        pronunciations=Pronunciations.from_files(args.pronounce),
    )


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


def _note(message: str) -> None:
    print(message, file=sys.stderr)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ao3-reader",
        description="Turn AO3 works into audiobooks read by a voice running on your computer.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(title="commands", required=True, metavar="COMMAND")

    reading = argparse.ArgumentParser(add_help=False)
    reading.add_argument("work", help="an AO3 link or work ID, or a saved AO3 work page (.html)")
    reading.add_argument("--chapters", metavar="LIST", help="only these chapters, such as 1-3,5 or 8-")
    reading.add_argument(
        "--no-summary", dest="summary", action="store_false", help="skip the work and chapter summaries"
    )
    reading.add_argument("--notes", action="store_true", help="also read the author's notes")
    reading.add_argument(
        "--pronounce", metavar="FILE", action="append", default=[], type=Path,
        help="a file of 'word = how to say it' lines, for names the voice gets wrong",
    )

    speaking = argparse.ArgumentParser(add_help=False)
    speaking.add_argument("--speed", type=float, default=1.0, help="0.5 to 2.0 (default 1.0)")
    speaking.add_argument(
        "--model", choices=MODELS, default="full",
        help="'small' is quicker to download and run, and sounds slightly worse",
    )

    make = commands.add_parser(
        "make", parents=[reading, speaking], help="make an audiobook from a work",
        description="Make an audiobook from a work. Chapters already made are reused, "
        "so after a work in progress updates only the new chapters are read.",
    )
    make.add_argument("--voice", default=DEFAULT_VOICE, help=f"see 'ao3-reader voices' (default {DEFAULT_VOICE})")
    make.add_argument("-o", "--out", type=Path, default=Path("."), help="folder to save in (default: here)")
    make.add_argument(
        "--format", choices=FORMATS, default="m4b",
        help="m4b: one audiobook file with chapters (default); mp3: a folder with one file per chapter",
    )
    make.add_argument("--bitrate", default="64k", help="audio quality (default 64k, plenty for speech)")
    make.set_defaults(run=_make)

    preview = commands.add_parser(
        "preview", parents=[reading], help="print exactly what would be read, without making audio"
    )
    preview.set_defaults(run=_preview)

    voices = commands.add_parser("voices", help="list voices")
    voices.set_defaults(run=_voices)

    sample = commands.add_parser(
        "sample", parents=[speaking], help="save a short clip in each voice to compare them"
    )
    sample.add_argument("text", nargs="?", help="what to say (default: a short passage)")
    sample.add_argument("--voice", action="append", help="a voice to try; repeat for more")
    sample.add_argument("-o", "--out", type=Path, default=Path("."), help="folder to save in (default: here)")
    sample.set_defaults(run=_sample)
    return parser
