import pytest
from bs4 import BeautifulSoup

from ao3reader.clean import Pronunciations, is_scene_break, paragraphs, speakable


@pytest.mark.parametrize(
    "raw, spoken",
    [
        ("“Nooo,” she said.", "“No,” she said."),
        ("Pleeease, Wren.", "Please, Wren."),
        ("Hmmm. Ahhhh.", "Hmm. Ahh."),
        ("What?!?!", "What?"),
        ("Stop!!!", "Stop!"),
        ("Wait.... what", "Wait… what"),
        ("I was--I mean", "I was—I mean"),
        ("He was *very* sure.", "He was very sure."),
        ("She was _so_ done.", "She was so done."),
        ("~sparkles~", "sparkles"),
        ("Mr. Hale and Dr. Okafor", "Mister Hale and Doctor Okafor"),
        ("asdfghjkl I can't", "I can't"),
        ("Henry VIII and Louis XIII", "Henry VIII and Louis XIII"),
        ("It was 1000 years ago", "It was 1000 years ago"),
        ("love you <3 ✨😭", "love you"),
        ("see https://example.com/x for more", "see link for more"),
        ("#blessed", "blessed"),
        ("non breaking​space", "non breakingspace"),
        ("strengths and flashlights", "strengths and flashlights"),
    ],
)
def test_speakable(raw, spoken):
    assert speakable(raw) == spoken


@pytest.mark.parametrize("raw", ["", "   ", "***", "😭😭😭", "~*~"])
def test_nothing_to_say(raw):
    assert speakable(raw) == ""


@pytest.mark.parametrize(
    "line", ["***", "* * *", "~*~", "◇◇◇", "-----", "oOo", "xXx", "-x-", "OoOoO", "…"]
)
def test_scene_breaks(line):
    assert is_scene_break(line)


@pytest.mark.parametrize("line", ["Ooo", "Xxx", "OK", "Ox", "Oh.", "No!", "x marks the spot"])
def test_not_scene_breaks(line):
    assert not is_scene_break(line)


def html(markup: str):
    return BeautifulSoup(f"<div>{markup}</div>", "html.parser").div


def test_paragraphs_split_lines_at_br_and_mark_hr():
    root = html("<p>one<br>two</p><hr><p>three <em>four</em>five</p>")
    assert paragraphs(root) == [["one", "two"], ["***"], ["three fourfive"]]


def test_paragraphs_skip_images_comments_footnote_marks_and_ruby():
    root = html(
        "<p>Word<sup>1</sup> <!-- secret --> here<sup>[2]</sup>.</p>"
        "<p><img src='x.png' alt='art'></p>"
        "<p><ruby>漢<rt>kan</rt></ruby></p>"
    )
    assert paragraphs(root) == [["Word here."], ["漢"]]


def test_paragraphs_keep_nested_blocks_separate():
    root = html("<blockquote><p>Dear Wren,</p><p>Come home.</p></blockquote><ul><li>a</li><li>b</li></ul>")
    assert paragraphs(root) == [["Dear Wren,"], ["Come home."], ["a"], ["b"]]


def test_pronunciations(tmp_path):
    lexicon = tmp_path / "names.txt"
    lexicon.write_text(
        "# names\nHermione = Her my oh nee\nY/N = Sam   # reader insert\n", encoding="utf-8"
    )
    say = Pronunciations.from_files([lexicon])

    assert say("Hermione and Y/N.") == "Her my oh nee and Sam."
    assert say("HERMIONE!") == "Her my oh nee!"
    assert say("Hermiones") == "Hermiones"


def test_pronunciation_file_errors_name_the_line(tmp_path):
    lexicon = tmp_path / "names.txt"
    lexicon.write_text("Hermione Her my oh nee\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        Pronunciations.from_files([lexicon])
