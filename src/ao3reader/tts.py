"""The voice: Kokoro, a small open model that sounds natural and runs fine on a CPU.

The model files (about 340 MB, or 115 MB for the smaller one) download once
on first use and are kept in the cache folder.
"""

import functools
import os
import sys
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np

from .paths import cache_dir

RELEASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODELS = {
    "full": "kokoro-v1.0.onnx",
    "small": "kokoro-v1.0.int8.onnx",
}
VOICES_FILE = "voices-v1.0.bin"
DEFAULT_VOICE = "af_heart"

# The first letter of a voice name says which language it speaks
LANGUAGES = {
    "a": "en-us", "b": "en-gb", "e": "es", "f": "fr-fr", "h": "hi",
    "i": "it", "j": "ja", "p": "pt-br", "z": "cmn",
}

# The English voices worth trying first, best-rated first
RECOMMENDED_VOICES = {
    "af_heart": "American, female (highest rated)",
    "af_bella": "American, female (highest rated)",
    "af_nicole": "American, female, soft",
    "af_aoede": "American, female",
    "af_kore": "American, female",
    "af_sarah": "American, female",
    "am_michael": "American, male",
    "am_fenrir": "American, male",
    "am_puck": "American, male",
    "bf_emma": "British, female",
    "bf_isabella": "British, female",
    "bm_george": "British, male",
    "bm_fable": "British, male",
}


class Voice(Protocol):
    sample_rate: int
    # Changes whenever the same text would come out sounding different
    key: str

    def speak(self, text: str) -> np.ndarray: ...


class KokoroVoice:
    sample_rate = 24000

    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        speed: float = 1.0,
        model: str = "full",
        model_dir: Path | None = None,
    ):
        if model not in MODELS:
            raise ValueError(f"Model must be one of: {', '.join(MODELS)}")
        if not 0.5 <= speed <= 2.0:
            raise ValueError("Speed must be between 0.5 and 2.0")
        self.voice = voice
        self.speed = speed
        self.model = model
        self.lang = LANGUAGES.get(voice[:1], "en-us")
        self.model_dir = model_dir or Path(
            os.environ.get("AO3_READER_MODELS") or cache_dir() / "models"
        )
        self.key = f"kokoro-v1.0-{model}/{voice}/{speed:g}"
        self._kokoro = None

    def load(self) -> None:
        if self._kokoro is not None:
            return
        model_path = _ensure_file(self.model_dir, MODELS[self.model])
        voices_path = _ensure_file(self.model_dir, VOICES_FILE)
        self._kokoro = _engine(str(model_path), str(voices_path))
        if self.voice not in self._kokoro.get_voices():
            raise ValueError(
                f"There's no voice called {self.voice!r}. Run 'ao3-reader voices' to see them."
            )

    def speak(self, text: str) -> np.ndarray:
        self.load()
        try:
            samples, _ = self._kokoro.create(
                text, voice=self.voice, speed=self.speed, lang=self.lang
            )
        except ValueError:
            # Text the voice has no sounds for, such as another alphabet; skipping
            # one line beats losing hours of reading
            return np.zeros(0, dtype=np.float32)
        return samples


@functools.cache
def _engine(model_path: str, voices_path: str):
    # Loading takes a few seconds, so voices that share a model share one engine
    from kokoro_onnx import Kokoro

    return Kokoro(model_path, voices_path)


def _ensure_file(folder: Path, name: str) -> Path:
    path = folder / name
    if path.exists():
        return path
    folder.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(name + ".part")
    url = RELEASE_URL + name
    print(f"Downloading voice model {name} (one time only)...", file=sys.stderr)
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", 0))
            done = 0
            with partial.open("wb") as out:
                for chunk in response.iter_bytes(1 << 20):
                    out.write(chunk)
                    done += len(chunk)
                    if total and sys.stderr.isatty():
                        print(f"\r  {done * 100 // total}% of {total >> 20} MB", end="", file=sys.stderr)
        if sys.stderr.isatty():
            print(file=sys.stderr)
    except httpx.HTTPError as error:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"Couldn't download {url}: {error}\n"
            f"You can download it yourself and put it in {folder}"
        ) from error
    partial.replace(path)
    return path
