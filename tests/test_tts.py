import functools
import http.server
import threading

import pytest

from ao3reader import tts


@pytest.fixture
def release(tmp_path, monkeypatch):
    """A local stand-in for the model release page."""
    served = tmp_path / "served"
    served.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(served))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(tts, "RELEASE_URL", f"http://127.0.0.1:{server.server_port}/")
    yield served
    server.shutdown()


def test_model_files_download_once(tmp_path, release):
    (release / "voices-v1.0.bin").write_bytes(b"x" * 3000)
    folder = tmp_path / "models"

    path = tts._ensure_file(folder, "voices-v1.0.bin")
    assert path.read_bytes() == b"x" * 3000

    (release / "voices-v1.0.bin").unlink()
    assert tts._ensure_file(folder, "voices-v1.0.bin") == path
    assert not list(folder.glob("*.part"))


def test_failed_download_leaves_nothing_behind(tmp_path, release):
    folder = tmp_path / "models"
    with pytest.raises(RuntimeError, match="download it yourself"):
        tts._ensure_file(folder, "kokoro-v1.0.onnx")
    assert list(folder.iterdir()) == []


def test_voice_settings():
    voice = tts.KokoroVoice("bf_emma", speed=1.25, model="small")
    assert voice.lang == "en-gb"
    assert voice.key == "kokoro-v1.0-small/bf_emma/1.25"
    assert tts.KokoroVoice().lang == "en-us"


@pytest.mark.parametrize("kwargs", [{"speed": 3}, {"speed": 0.1}, {"model": "huge"}])
def test_bad_voice_settings(kwargs):
    with pytest.raises(ValueError):
        tts.KokoroVoice(**kwargs)
