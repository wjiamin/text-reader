from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeVoice:
    """Stands in for Kokoro: a short tone per line, and a record of what was said."""

    sample_rate = 24000
    key = "fake"

    def __init__(self):
        self.spoken: list[str] = []

    def load(self) -> None:
        pass

    def speak(self, text: str) -> np.ndarray:
        self.spoken.append(text)
        seconds = 0.05 * len(text.split())
        t = np.arange(round(seconds * self.sample_rate)) / self.sample_rate
        return (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


@pytest.fixture
def voice() -> FakeVoice:
    return FakeVoice()
