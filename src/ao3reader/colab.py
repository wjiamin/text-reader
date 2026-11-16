"""The steps behind the Google Colab notebook (colab/make_audiobook.ipynb).

Colab lends a free computer with a graphics chip, which makes the natural
voice dozens of times faster than a phone. The notebook uploads an EPUB,
calls make() and downloads the result.
"""

import importlib
import logging
import os
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


def has_torch_kokoro() -> bool:
    importlib.invalidate_caches()
    try:
        import kokoro  # noqa: F401
    except Exception:
        return False
    return True


def onnx_on_graphics_chip() -> bool:
    try:
        import onnxruntime
    except ImportError:
        return False
    return "CUDAExecutionProvider" in onnxruntime.get_available_providers()


# The pronunciation step warns about harmless word-count mismatches, often
# enough to bury the progress lines
logging.getLogger("phonemizer").setLevel(logging.ERROR)


def _prefer_graphics_chip() -> None:
    # Ask the voice's engine for the graphics chip alone, skipping TensorRT; if
    # the chip can't be used it quietly falls back to the processor
    if onnx_on_graphics_chip():
        import onnxruntime

        os.environ.setdefault("ONNX_PROVIDER", "CUDAExecutionProvider")
        onnxruntime.set_default_logger_severity(4)


def get_ready(voice: str = "af_heart") -> None:
    """Step 1: load the voice once (downloading it) and say where it will run."""
    _prefer_graphics_chip()
    engine = pick_voice(voice)
    engine.load()
    if on_graphics_chip(engine):
        print("Ready, with a graphics chip ✓")
    elif not graphics_chip() and not onnx_on_graphics_chip():
        print("Ready, but this computer has no graphics chip, so it will be much slower.\n"
              "To fix it: Runtime → Change runtime type → T4 GPU → Save, then run this step again.")
    else:
        print("Ready, but the graphics chip couldn't be used, so it will be much slower.")


def on_graphics_chip(engine) -> bool:
    """Whether a loaded voice is really running on the graphics chip."""
    if isinstance(engine, KokoroVoice):
        return "CUDAExecutionProvider" in engine._kokoro.sess.get_providers()
    return isinstance(engine, TorchKokoroVoice) and graphics_chip()


def pick_voice(voice: str, speed: float = 1.0):
    """Kokoro through PyTorch when it's installed, which uses the graphics chip if
    there is one and is quicker on a processor too; otherwise the ONNX version."""
    return TorchKokoroVoice(voice, speed) if has_torch_kokoro() else KokoroVoice(voice, speed)


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
    _prefer_graphics_chip()
    engine = voice_engine or pick_voice(voice, speed)
    engine.load()
    where = "the graphics chip" if on_graphics_chip(engine) else "the processor, which is much slower"
    print(
        f"“{work.title}” by {work.author}: {len(tracks)} parts, {words:,} words, "
        f"about {format_duration(estimated_minutes(words, speed) * 60)} of listening. "
        f"Making it on {where}.",
        flush=True,
    )
    out = make_audiobook(work, tracks, engine, Path(out_dir), "m4b", bitrate, stream=sys.stdout, live=True)
    size = out.stat().st_size / 2**20
    print(f"\nDone: {out.name} ({size:.0f} MB). Run the next step to download it.", flush=True)
    return out
