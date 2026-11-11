"""The steps behind the Google Colab notebook (colab/make_audiobook.ipynb).

Colab lends a free computer with a graphics chip, which makes the natural
voice dozens of times faster than a phone. The notebook uploads an EPUB,
calls make() and downloads the result.
"""

import sys
from pathlib import Path

from .audiobook import format_duration, make_audiobook
from .epub import parse_epub
from .script import Options, build_tracks, estimated_minutes
from .tts import KokoroVoice, TorchKokoroVoice


def graphics_chip() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return torch.cuda.is_available()


def pick_voice(voice: str, speed: float = 1.0):
    """Kokoro through PyTorch when it's installed, which uses the graphics chip if
    there is one and is quicker on a processor too; otherwise the ONNX version."""
    try:
        import kokoro  # noqa: F401
    except ImportError:
        return KokoroVoice(voice, speed)
    return TorchKokoroVoice(voice, speed)


def make(
    epub: str | Path,
    voice: str = "af_heart",
    speed: float = 1.0,
    notes: bool = False,
    summary: bool = True,
    out_dir: str | Path = ".",
    bitrate: str = "48k",
    voice_engine=None,
) -> Path:
    """Turn an EPUB downloaded from AO3 into an .m4b audiobook; returns its path."""
    work = parse_epub(Path(epub))
    tracks = build_tracks(work, Options(summary=summary, notes=notes))
    words = sum(track.words for track in tracks)
    engine = voice_engine or pick_voice(voice, speed)
    where = (
        "the graphics chip" if isinstance(engine, TorchKokoroVoice) and graphics_chip()
        else "the processor, which is much slower"
    )
    print(
        f"“{work.title}” by {work.author}: {len(tracks)} parts, {words:,} words, "
        f"about {format_duration(estimated_minutes(words, speed) * 60)} of listening. "
        f"Making it on {where}.",
        flush=True,
    )
    engine.load()
    out = make_audiobook(work, tracks, engine, Path(out_dir), "m4b", bitrate, stream=sys.stdout, live=True)
    size = out.stat().st_size / 2**20
    print(f"\nDone: {out.name} ({size:.0f} MB). Run the next step to download it.", flush=True)
    return out
