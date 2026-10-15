from ao3reader.parse import parse_work
from ao3reader.script import (
    HEADING,
    LINE_BREAK,
    PARAGRAPH,
    SCENE_BREAK,
    TRACK_END,
    Options,
    build_tracks,
)

from conftest import fixture_html


def texts(track):
    return [line.text for line in track.lines]


def test_default_reading_has_intro_summaries_and_no_notes():
    work = parse_work(fixture_html("multi_chapter.html"))
    intro, one, two, three = build_tracks(work)

    assert intro.title == "Introduction"
    assert texts(intro) == [
        "The Lighthouse Keeper's Apprentice.",
        "By quietquill and Second Pen.",
        "Summary.",
        "A storm, a lamp that won't stay lit, and an apprentice who asks too many questions.",
    ]
    assert one.title == "Chapter 1: The Storm"
    assert texts(one) == [
        "Chapter 1. The Storm.",
        "The lamp went out at exactly the wrong moment.",
        "“No,” Wren groaned. “Not again!”",
        "Mister Hale didn't look up from his book.",
        "By morning the sea had calmed.",
        "The gulls were back.",
        "So was the lamp.",
        "she was so tired.",
    ]
    assert texts(two) == [
        "Chapter 2.",
        "Chapter summary.",
        "Wren climbs the stairs.",
        "There were one hundred and twelve steps.",
        "Wren counted every one of them.",
    ]
    assert texts(three) == ["Chapter 3. What the Light Saw.", "The light saw everything. It always had."]


def test_pauses():
    work = parse_work(fixture_html("multi_chapter.html"))
    one = build_tracks(work)[1]
    pauses = [line.pause for line in one.lines]

    assert pauses == [
        HEADING,
        PARAGRAPH,
        PARAGRAPH,
        SCENE_BREAK,  # "* * *" paragraph
        LINE_BREAK,
        LINE_BREAK,
        SCENE_BREAK,  # <hr>
        TRACK_END,
    ]


def test_notes_when_asked_for():
    work = parse_work(fixture_html("multi_chapter.html"))
    intro, one, _, three = build_tracks(work, Options(notes=True, summary=False))

    assert texts(intro) == [
        "The Lighthouse Keeper's Apprentice.",
        "By quietquill and Second Pen.",
        "Author's note.",
        "Thank you to my beta! Find me at link.",
    ]
    assert texts(one)[1:3] == ["Author's note.", "This one was hard to write."]
    assert texts(one)[-2:] == ["End note.", "Comments make my day."]
    assert texts(three)[-2:] == ["End of work note.", "That's all for now."]


def test_choosing_chapters_skips_the_intro_unless_chapter_one_is_in():
    work = parse_work(fixture_html("multi_chapter.html"))

    assert [t.title for t in build_tracks(work, Options(chapters={2, 3}))] == [
        "Chapter 2",
        "Chapter 3: What the Light Saw",
    ]
    assert [t.title for t in build_tracks(work, Options(chapters={1}))] == [
        "Introduction",
        "Chapter 1: The Storm",
    ]


def test_one_shot_has_no_chapter_heading():
    work = parse_work(fixture_html("one_shot.html"))
    intro, story = build_tracks(work)

    assert texts(intro) == ["Tea for Two.", "By Anonymous."]
    assert story.title == "Tea for Two"
    assert texts(story) == [
        "The kettle sang. Neither of them moved to get it.",
        "“Your turn,” said Ash.",
    ]
