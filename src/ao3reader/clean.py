"""Cleaning up story text so the voice reads it the way a person would.

Fic formatting that looks fine on the page often sounds wrong read aloud: a
voice says "asterisk asterisk asterisk" for a scene break, "tilde" for a
flourish and "N O O O O" for a drawn-out "Nooo". Everything here turns the
page's HTML into plain lines of speakable text.
"""

import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from bs4 import NavigableString, Tag
from bs4.element import PreformattedString

_SKIP_TAGS = {
    "audio", "button", "embed", "form", "iframe", "img", "input", "noscript",
    "object", "rp", "rt", "script", "select", "style", "svg", "textarea", "video",
}
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "caption", "center", "dd",
    "details", "div", "dl", "dt", "figcaption", "figure", "footer", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "li", "main", "nav", "ol", "p", "pre",
    "section", "summary", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}
_FOOTNOTE_MARK = re.compile(r"\[?(?:\d{1,3}|[*†‡§]+)\]?")


def paragraphs(root: Tag | None) -> list[list[str]]:
    """The text of a piece of HTML as paragraphs, each a list of lines split at <br>."""
    out: list[list[str]] = []
    paragraph: list[str] = []
    line: list[str] = []

    def end_line() -> None:
        text = " ".join("".join(line).split())
        line.clear()
        if text:
            paragraph.append(text)

    def end_paragraph() -> None:
        end_line()
        if paragraph:
            out.append(paragraph.copy())
            paragraph.clear()

    def walk(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, PreformattedString):  # comments, doctypes, CDATA
                continue
            if isinstance(child, NavigableString):
                line.append(str(child))
                continue
            if not isinstance(child, Tag) or child.name in _SKIP_TAGS:
                continue
            if "landmark" in child.get("class", []):  # AO3's hidden "Chapter Text" heading
                continue
            if child.name == "br":
                end_line()
            elif child.name == "hr":
                end_paragraph()
                out.append(["***"])
            elif child.name == "sup" and _FOOTNOTE_MARK.fullmatch(child.get_text(strip=True)):
                continue
            elif child.name in _BLOCK_TAGS:
                end_paragraph()
                walk(child)
                end_paragraph()
            else:
                walk(child)

    if root is not None:
        walk(root)
        end_paragraph()
    return out


def is_scene_break(line: str) -> bool:
    """True for divider lines such as ***, ~~~, ◇◇◇, -x- or oOo."""
    compact = "".join(line.split())
    if not compact:
        return False
    letters = "".join(ch for ch in compact if ch.isalnum())
    if not letters:
        return True
    if len(compact) > 20 or not set(letters) <= set("oOxX0"):
        return False
    # "Xxx" or "Ooo" on its own could be a word; "oOo", "xXx" and "-x-" are dividers
    return letters != compact or (len(letters) >= 3 and letters != letters.capitalize())


_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍⁠﻿"))
_ODD_SPACES = re.compile(r"[  -   　]")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
# Emoji, arrows, dingbats and shapes, which the voice reads as names ("heart suit")
_SYMBOLS = re.compile(
    "[←-⇿⌀-⏿■-➿⬀-⯿⃣︎️"
    "\U0001f000-\U0001faff\U000e0020-\U000e007f]"
)
_HEART = re.compile(r"<3+")
_EMPHASIS = re.compile(r"(?<!\w)([*_~]+)(?=\S)(.+?)(?<=\S)\1(?!\w)")
# Read aloud by name ("asterisk", "tilde", "hash") if left in
_STRAY = re.compile(r"[*_~#^|<>\[\]{}\\]")
_TITLES = {"Mr": "Mister", "Mrs": "Missus", "Ms": "Miz", "Mx": "Mix", "Dr": "Doctor", "Prof": "Professor"}
_TITLE = re.compile(r"\b(Mrs|Mr|Ms|Mx|Dr|Prof)\.(?=\s)")
_WORD = re.compile(r"[^\W\d_]+")
_ROMAN = re.compile(r"[IVXLCDM]+")
_STRETCH = re.compile(r"([^\W\d_])\1{2,}")
_HOME_ROW = set("asdfghjkl")


def speakable(text: str) -> str:
    """Text as it should be spoken, or "" when nothing in it can be said."""
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    text = _ODD_SPACES.sub(" ", text)
    text = _URL.sub("link", text)
    text = _HEART.sub("", text)
    text = _SYMBOLS.sub("", text)
    text = _EMPHASIS.sub(r"\2", text)
    text = _STRAY.sub(" ", text)
    text = _TITLE.sub(lambda m: _TITLES[m.group(1)], text)
    text = _WORD.sub(_fix_word, text)
    text = re.sub(r"[!?]{2,}", lambda m: "?" if "?" in m.group() else "!", text)
    text = re.sub(r"\.(?:\s?\.){2,}|…+", "…", text)
    text = re.sub(r"--+|—+", "—", text)
    text = " ".join(text.split())
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text if any(ch.isalnum() for ch in text) else ""


def _fix_word(match: re.Match) -> str:
    word = match.group()
    if _ROMAN.fullmatch(word):
        return word
    if _is_keysmash(word):
        return ""
    # "Nooo" -> "No", "Pleeease" -> "Please"; "Hmmm" and "Ahhh" keep two letters
    return _STRETCH.sub(lambda m: m.group(1) * (2 if m.group(1).lower() in "hmz" else 1), word)


def _is_keysmash(word: str) -> bool:
    word = word.lower()
    if len(word) < 7:
        return False
    home_row = sum(ch in _HOME_ROW for ch in word) / len(word)
    vowels = sum(ch in "aeiouy" for ch in word) / len(word)
    return home_row >= 0.85 and vowels <= 0.25


class Pronunciations:
    """Respellings for words the voice gets wrong, such as character names."""

    def __init__(self, entries: dict[str, str] | None = None):
        self.entries = dict(entries or {})
        self._spoken = {word.lower(): spoken for word, spoken in self.entries.items()}
        words = sorted(self.entries, key=len, reverse=True)
        self._pattern = (
            re.compile(r"(?<!\w)(" + "|".join(map(re.escape, words)) + r")(?!\w)", re.IGNORECASE)
            if words
            else None
        )

    @classmethod
    def from_files(cls, paths: Iterable[Path | str]) -> "Pronunciations":
        entries: dict[str, str] = {}
        for path in paths:
            for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                word, sep, spoken = line.partition("=")
                if not sep or not word.strip():
                    raise ValueError(f"{path}, line {number}: expected 'word = how to say it'")
                entries[word.strip()] = spoken.strip()
        return cls(entries)

    def __call__(self, text: str) -> str:
        if self._pattern is None:
            return text
        return self._pattern.sub(lambda m: self._spoken[m.group(1).lower()], text)
