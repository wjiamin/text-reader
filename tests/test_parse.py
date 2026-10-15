import pytest

from ao3reader.clean import paragraphs
from ao3reader.parse import ParseError, parse_work

from conftest import fixture_html


def test_multi_chapter_work():
    work = parse_work(fixture_html("multi_chapter.html"))

    assert work.title == "The Lighthouse Keeper's Apprentice"
    assert work.authors == ["quietquill", "Second_Pen"]
    assert work.author == "quietquill and Second_Pen"
    assert work.work_id == 987654
    assert work.url == "https://archiveofourown.org/works/987654"
    assert work.fandoms == ["Original Work"]
    assert work.language == "English"
    assert work.words == 1234
    assert work.posted_chapters == 3
    assert [(c.number, c.title) for c in work.chapters] == [
        (1, "Chapter 1: The Storm"),
        (2, "Chapter 2"),
        (3, "Chapter 3: What the Light Saw"),
    ]


def test_summaries_and_notes_are_kept_apart():
    work = parse_work(fixture_html("multi_chapter.html"))
    first, second, third = work.chapters

    assert paragraphs(work.summary)[0][0].startswith("A storm, a lamp")
    assert paragraphs(work.notes)[0][0].startswith("Thank you to my beta!")
    assert paragraphs(work.end_notes) == [["That's all for now."]]
    assert paragraphs(first.notes) == [["This one was hard to write."]]
    assert paragraphs(first.end_notes) == [["Comments make my day."]]
    assert first.summary is None
    assert paragraphs(second.summary) == [["Wren climbs the stairs."]]
    assert second.notes is None and second.end_notes is None
    assert third.notes is None


def test_chapter_text_leaves_out_ao3_headings():
    work = parse_work(fixture_html("multi_chapter.html"))
    text = paragraphs(work.chapters[0].body)

    assert text[0] == ["The lamp went out at exactly the wrong moment."]
    assert all("Chapter Text" not in line for paragraph in text for line in paragraph)


def test_one_shot():
    work = parse_work(fixture_html("one_shot.html"))

    assert work.title == "Tea for Two"
    assert work.author == "Anonymous"
    assert len(work.chapters) == 1
    assert work.chapters[0].title == "Tea for Two"
    assert paragraphs(work.chapters[0].body) == [
        ["The kettle sang. Neither of them moved to get it."],
        ["“Your turn,” said Ash."],
    ]


def test_adult_content_warning_page_explains_what_to_do():
    page = """<html><body><div id="main"><p class="caution">This work could have adult
    content. If you continue, you have agreed that you are willing to see such
    content.</p></div></body></html>"""
    with pytest.raises(ParseError, match="adult-content warning"):
        parse_work(page)


def test_unrelated_page():
    with pytest.raises(ParseError, match="doesn't look like an AO3 work page"):
        parse_work("<html><body><p>Hello</p></body></html>")
