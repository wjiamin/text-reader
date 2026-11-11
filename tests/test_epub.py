import pytest

from ao3reader.epub import parse_epub
from ao3reader.parse import ParseError
from ao3reader.script import Options, build_tracks

from make_epub import multi_chapter, one_shot


def texts(track):
    return [line.text for line in track.lines]


def test_multi_chapter_epub(tmp_path):
    work = parse_epub(multi_chapter(tmp_path / "work.epub"))

    assert work.title == "The Lighthouse Keeper's Apprentice"
    assert work.author == "quietquill"
    assert work.work_id == 987654
    assert [(c.number, c.title) for c in work.chapters] == [(1, "Chapter 1: The Storm"), (2, "Chapter 2")]

    intro, one, two = build_tracks(work)
    assert texts(intro) == [
        "The Lighthouse Keeper's Apprentice.", "By quietquill.", "Summary.", "A storm, a lamp that won't stay lit.",
    ]
    assert texts(one) == [
        "Chapter 1. The Storm.",
        "The lamp went out at exactly the wrong moment.",
        "“No,” Wren groaned. “Not again!”",
        "By morning the sea had calmed.",
        "The gulls were back.",
    ]
    assert texts(two) == [
        "Chapter 2.", "Chapter summary.", "Wren climbs the stairs.",
        "There were one hundred and twelve steps.", "Wren counted every one of them.",
    ]


def test_notes_come_through_when_asked_for(tmp_path):
    work = parse_epub(multi_chapter(tmp_path / "work.epub"))
    intro, one, two = build_tracks(work, Options(notes=True, summary=False))

    assert texts(intro)[-2:] == ["Author's note.", "Thank you to my beta!"]
    assert texts(one)[1:3] == ["Author's note.", "This one was hard to write."]
    assert texts(one)[-2:] == ["End note.", "Comments make my day."]
    assert texts(two)[-2:] == ["End note.", "That's all for now."]


def test_one_shot_epub_with_renamed_markup(tmp_path):
    work = parse_epub(one_shot(tmp_path / "tea.epub"))

    assert work.author == "Ash Grey"
    assert work.work_id == 555
    intro, story = build_tracks(work)
    assert texts(intro) == ["Tea for Two.", "By Ash Grey.", "Summary.", "Two people, one kettle."]
    assert texts(story) == ["The kettle sang. Neither of them moved to get it.", "“Your turn,” said Ash."]


def test_not_an_epub(tmp_path):
    with pytest.raises(ParseError, match="isn't an EPUB"):
        parse_epub(b"hello")


def test_colab_steps_make_an_audiobook_from_an_epub(tmp_path, voice, capsys, monkeypatch):
    from ao3reader import colab

    monkeypatch.setenv("AO3_READER_CACHE", str(tmp_path / "cache"))
    out = colab.make(multi_chapter(tmp_path / "work.epub"), out_dir=tmp_path, voice_engine=voice)

    assert out.name == "The Lighthouse Keeper's Apprentice - quietquill.m4b"
    assert out.stat().st_size > 0
    printed = capsys.readouterr().out
    assert "3 parts" in printed and "Making it on the processor" in printed
    assert "Run the next step to download it" in printed
