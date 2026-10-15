import pytest

from ao3reader import cli

from conftest import FIXTURES, FakeVoice


@pytest.mark.parametrize(
    "spec, chosen",
    [
        ("3", {3}),
        ("1-3,5", {1, 2, 3, 5}),
        ("8-", {8, 9, 10}),
        (" 2 - 4 , 9 ", {2, 3, 4, 9}),
    ],
)
def test_parse_chapters(spec, chosen):
    assert cli.parse_chapters(spec, last=10) == chosen


@pytest.mark.parametrize("spec", ["", "0", "5-2", "a-b", "1;2"])
def test_parse_chapters_rejects_nonsense(spec):
    with pytest.raises(ValueError):
        cli.parse_chapters(spec, last=10)


def test_preview_prints_what_will_be_read(capsys):
    assert cli.main(["preview", str(FIXTURES / "multi_chapter.html"), "--chapters", "2"]) == 0
    out = capsys.readouterr().out

    assert out.startswith("=== Chapter 2 (")
    assert "Wren climbs the stairs." in out
    assert "* * *" in out
    assert "Introduction" not in out


def test_make_from_a_saved_page(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AO3_READER_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(cli, "KokoroVoice", lambda *args: FakeVoice())

    page = FIXTURES / "one_shot.html"
    assert cli.main(["make", str(page), "-o", str(tmp_path), "--chapters", "1"]) == 0

    assert (tmp_path / "Tea for Two - Anonymous (chapters 1).m4b").is_file()
    captured = capsys.readouterr()
    assert captured.out.strip().endswith("Tea for Two - Anonymous (chapters 1).m4b")
    assert "“Tea for Two” by Anonymous: 1 chapter" in captured.err


def test_errors_are_short_messages_not_tracebacks(capsys):
    assert cli.main(["preview", "https://archiveofourown.org/users/someone"]) == 1
    assert capsys.readouterr().err.startswith("error: Not an AO3 work link")
