"""Reading AO3's EPUB downloads into a Work, the same shape as a work page.

AO3 builds its EPUBs from the work's HTML download, and ebook converters may
rename its classes and ids along the way. So, like the phone reader, this
goes by what's on the page: AO3's plain labels ("Summary", "Chapter Notes")
before each notes box, "Chapter N" headings, and its fixed bits of text.
"""

import copy
import io
import posixpath
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag

from .parse import Chapter, ParseError, Work

_SKIP = {"script", "style", "img", "svg", "audio", "video", "nav", "head", "title", "noscript"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCKS = {
    "address", "article", "aside", "blockquote", "caption", "center", "dd", "details", "div",
    "dl", "dt", "figcaption", "figure", "footer", "header", "li", "main", "ol", "p", "pre",
    "section", "summary", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}
# The plain label AO3 puts before each summary or notes box
_LABELS = {
    "summary": "summary", "chapter summary": "summary",
    "notes": "notes", "chapter notes": "notes", "author's note": "notes", "author's notes": "notes",
    "end notes": "end_notes", "chapter end notes": "end_notes",
}
_BOILERPLATE = [
    re.compile(r"^Posted originally on the Archive of Our Own\b", re.I),
    re.compile(r"^Please drop by the Archive and comment", re.I),
    re.compile(r"^\(?See the end of the (chapter|work) for (more )?notes\.?\)?$", re.I),
    re.compile(r"^Afterword$", re.I),
]
_CHAPTER = re.compile(r"^chapter\s+(\d+)", re.I)
_TAGS_LIST = re.compile(r"\b(Rating|Fandom|Archive Warnings?):")
_WORK_ID = re.compile(r"archiveofourown\.org/works/(\d+)")
_DC = "{http://purl.org/dc/elements/1.1/}"


def parse_epub(source: bytes | str | Path) -> Work:
    data = Path(source).read_bytes() if isinstance(source, (str, Path)) else source
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ParseError("That file isn't an EPUB. On AO3, use Download, then EPUB.") from error
    with archive:
        try:
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            rootfile = container.find(".//{*}rootfile").get("full-path")
            package = ElementTree.fromstring(archive.read(rootfile))
        except (KeyError, AttributeError, ElementTree.ParseError) as error:
            raise ParseError("That EPUB is missing its table of contents.") from error
        base = posixpath.dirname(rootfile)
        items = {item.get("id"): item for item in package.findall(".//{*}item")}
        pages = []
        for ref in package.findall(".//{*}itemref"):
            item = items.get(ref.get("idref"))
            if item is None or "html" not in (item.get("media-type") or ""):
                continue
            path = posixpath.normpath(posixpath.join(base, unquote(item.get("href").split("#")[0])))
            try:
                pages.append(BeautifulSoup(archive.read(path), "html.parser"))
            except KeyError:
                continue

    def meta(name: str) -> list[str]:
        return [" ".join(el.text.split()) for el in package.iter(_DC + name) if el.text and el.text.strip()]

    found: dict = {}
    pieces = [piece for page in pages for piece in _pieces(page.body or page, found)]
    identifiers = " ".join(meta("identifier") + meta("source"))
    work_id = _WORK_ID.search(identifiers) or found.get("work_id")
    return _arrange(
        pieces,
        title=(meta("title") or ["Untitled"])[0],
        authors=meta("creator"),
        description=(meta("description") or [""])[0],
        language=(meta("language") or [None])[0],
        work_id=int(work_id.group(1)) if work_id else None,
    )


def _pieces(root: Tag, found: dict) -> list[tuple[str, object]]:
    """The page as (kind, element or text): headings, breaks, notes and paragraphs."""
    out: list[tuple[str, object]] = []
    labelled: dict[int, str] = {}

    def walk(node: Tag, kind: str | None) -> None:
        for child in node.children:
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            if name in _SKIP:
                continue
            if name == "hr":
                out.append(("break", None))
                continue
            if name in _HEADINGS:
                if text := _tidy(child.get_text()):
                    out.append(("heading", text))
                continue
            if name == "dl" and _TAGS_LIST.search(child.get_text()):
                continue  # the work's tags
            if name not in _BLOCKS:
                continue
            label = _LABELS.get(_tidy(child.get_text()).rstrip(":").lower())
            following = child.find_next_sibling()
            if label and name != "blockquote" and following is not None and following.name == "blockquote":
                labelled[id(following)] = label
                continue
            this_kind = labelled.get(id(child), kind)
            if _has_blocks(child):
                walk(child, this_kind)
                continue
            # The whole paragraph, and each piece of it: AO3's title page puts the
            # title and "Posted originally on..." in one paragraph
            lines = [_tidy(child.get_text()), *(_tidy(line) for line in child.get_text("\n").split("\n"))]
            if any(pattern.search(line) for line in lines for pattern in _BOILERPLATE):
                if match := _WORK_ID.search(child.get_text()):
                    found["work_id"] = match
                continue
            if any(lines):
                out.append((this_kind or "text", child))

    walk(root, None)
    return out


def _arrange(pieces, title, authors, description, language, work_id) -> Work:
    holder = BeautifulSoup("", "html.parser")

    def box() -> Tag:
        return holder.new_tag("div")

    def is_byline(element) -> bool:
        text = _tidy(element.get_text()).lower()
        return text.startswith("by ") and any(name.lower() in text for name in authors)

    has_chapters = any(kind == "heading" and _CHAPTER.match(value) for kind, value in pieces)
    work_notes = {"summary": box(), "notes": box()}
    chapters: list[dict] = []
    current = None if has_chapters else {"number": 1, "title": title}

    def part(name: str) -> Tag:
        return current.setdefault(name, box())

    for kind, value in pieces:
        if kind == "heading":
            if match := _CHAPTER.match(value):
                current = {"number": int(match.group(1)), "title": value}
                chapters.append(current)
            elif current is not None and value.lower() != title.lower():
                heading = holder.new_tag("p")
                heading.string = value
                part("body").append(heading)
        elif current is None:
            if kind in work_notes:
                work_notes[kind].append(copy.copy(value))
        elif kind == "break":
            part("body").append(holder.new_tag("hr"))
        elif kind in ("summary", "notes") and "body" not in current and not chapters:
            work_notes[kind].append(copy.copy(value))  # a one-shot's notes
        elif kind in ("summary", "notes", "end_notes"):
            target = "end_notes" if kind == "end_notes" or "body" in current else kind
            part(target).append(copy.copy(value))
        elif not is_byline(value):
            part("body").append(copy.copy(value))

    if not has_chapters and current.get("body"):
        chapters = [current]
    chapters = [c for c in chapters if c.get("body") is not None]
    if not chapters:
        raise ParseError("Couldn't find the story text in that EPUB.")

    summary = work_notes["summary"] if work_notes["summary"].contents else None
    if summary is None and description:
        text = _tidy(BeautifulSoup(description, "html.parser").get_text())
        if text:
            summary = box()
            paragraph = holder.new_tag("p")
            paragraph.string = text
            summary.append(paragraph)

    return Work(
        title=title,
        authors=authors,
        chapters=[
            Chapter(
                number=c["number"], title=c["title"], body=c["body"],
                summary=c.get("summary"), notes=c.get("notes"), end_notes=c.get("end_notes"),
            )
            for c in chapters
        ],
        work_id=work_id,
        summary=summary,
        notes=work_notes["notes"] if work_notes["notes"].contents else None,
        language=language,
    )


def _has_blocks(element: Tag) -> bool:
    return any(
        isinstance(d, Tag) and (d.name in _BLOCKS or d.name in _HEADINGS or d.name == "hr")
        for d in element.descendants
    )


def _tidy(text: str) -> str:
    return " ".join(text.split())
