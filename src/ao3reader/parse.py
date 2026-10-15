"""Pulling the title, author, notes and chapters out of an AO3 work page.

Works with the page AO3 serves for "Entire Work", whether fetched by this tool
or saved from a browser.
"""

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from .fetch import SAVE_PAGE_TIP, work_url


class ParseError(Exception):
    pass


@dataclass
class Chapter:
    number: int
    title: str
    body: Tag
    summary: Tag | None = None
    notes: Tag | None = None
    end_notes: Tag | None = None


@dataclass
class Work:
    title: str
    authors: list[str]
    chapters: list[Chapter]
    work_id: int | None = None
    summary: Tag | None = None
    notes: Tag | None = None
    end_notes: Tag | None = None
    fandoms: list[str] = field(default_factory=list)
    language: str | None = None
    words: int | None = None
    # AO3's "Chapters:" stat, such as "3/10" or "3/?"
    chapter_stat: str | None = None

    @property
    def author(self) -> str:
        if not self.authors:
            return "Anonymous"
        if len(self.authors) == 1:
            return self.authors[0]
        return ", ".join(self.authors[:-1]) + " and " + self.authors[-1]

    @property
    def url(self) -> str | None:
        return work_url(self.work_id) if self.work_id else None

    @property
    def posted_chapters(self) -> int | None:
        if self.chapter_stat and (match := re.match(r"\s*(\d+)", self.chapter_stat)):
            return int(match.group(1))
        return None


def parse_work(html: str, work_id: int | None = None) -> Work:
    soup = BeautifulSoup(html, "html.parser")
    skin = soup.find(id="workskin")
    if skin is None:
        raise ParseError(_why_no_work(soup))

    preface = skin.find("div", class_="preface", recursive=False)
    title = _text(preface.find(class_="title")) if preface else ""
    byline = preface.find(class_="byline") if preface else None
    authors = [_text(a) for a in byline.find_all("a", rel="author")] if byline else []
    if not authors and byline and _text(byline):
        authors = [_text(byline)]

    container = skin.find(id="chapters")
    if container is None:
        raise ParseError(f"Found the work's details but not its text. {SAVE_PAGE_TIP}")
    chapters = _chapters(container, title)
    if not chapters:
        raise ParseError(f"Couldn't find any chapter text on the page. {SAVE_PAGE_TIP}")

    afterword = skin.find("div", class_="afterword")
    return Work(
        title=title or "Untitled",
        authors=authors,
        chapters=chapters,
        work_id=work_id or _find_work_id(soup),
        summary=_module(preface, "summary"),
        notes=_module(preface, "notes"),
        end_notes=_module(afterword, "notes", end=True) or _module(afterword, "notes"),
        fandoms=[_text(a) for a in soup.select("dd.fandom a.tag")],
        language=_text(soup.select_one("dd.language")) or None,
        words=_number(soup.select_one("dl.stats dd.words")),
        chapter_stat=_text(soup.select_one("dl.stats dd.chapters")) or None,
    )


def _chapters(container: Tag, work_title: str) -> list[Chapter]:
    divs = [
        div
        for div in container.find_all("div", recursive=False)
        if "chapter" in div.get("class", [])
    ]
    if not divs:
        # A one-shot has no chapter wrappers, only the text itself
        body = container.find("div", class_="userstuff")
        return [Chapter(1, work_title, body)] if body else []

    chapters = []
    for position, div in enumerate(divs, 1):
        body = div.find("div", class_="userstuff", recursive=False)
        if body is None:
            continue
        number = _chapter_number(div.get("id", ""), position)
        prefaces = div.find_all("div", class_="preface", recursive=False)
        heading = next((p.find(class_="title") for p in prefaces if p.find(class_="title")), None)
        chapters.append(
            Chapter(
                number=number,
                title=_text(heading) or f"Chapter {number}",
                body=body,
                summary=_first(_module(p, "summary") for p in prefaces),
                notes=_first(_module(p, "notes") for p in prefaces),
                end_notes=_first(_module(p, "notes", end=True) for p in prefaces),
            )
        )
    return chapters


def _module(container: Tag | None, kind: str, end: bool = False) -> Tag | None:
    """The author's text inside a summary or notes box, if the box has any."""
    if container is None:
        return None
    for div in container.find_all("div", class_=kind):
        if ("end" in div.get("class", [])) == end:
            if text := div.find("blockquote", class_="userstuff"):
                return text
    return None


def _first(items):
    return next((item for item in items if item is not None), None)


def _chapter_number(element_id: str, fallback: int) -> int:
    match = re.fullmatch(r"chapter-(\d+)", element_id)
    return int(match.group(1)) if match else fallback


def _find_work_id(soup: BeautifulSoup) -> int | None:
    kudos = soup.find("input", attrs={"name": "kudo[commentable_id]"})
    if kudos and str(kudos.get("value", "")).isdigit():
        return int(kudos["value"])
    for link in soup.select("#chapters a[href], #workskin .preface a[href]"):
        if match := re.search(r"/works/(\d+)", link["href"]):
            return int(match.group(1))
    return None


def _why_no_work(soup: BeautifulSoup) -> str:
    text = " ".join(soup.get_text(" ").split())
    if "adult content" in text:
        return (
            "This page is AO3's adult-content warning, not the story. Click "
            "'Proceed', then save the page again."
        )
    if "registered users" in text:
        return f"This work is only visible to logged-in AO3 users. {SAVE_PAGE_TIP}"
    return f"This doesn't look like an AO3 work page. {SAVE_PAGE_TIP}"


def _text(tag: Tag | None) -> str:
    return " ".join(tag.get_text().split()) if tag else ""


def _number(tag: Tag | None) -> int | None:
    digits = re.sub(r"\D", "", _text(tag))
    return int(digits) if digits else None
