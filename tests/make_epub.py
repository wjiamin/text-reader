"""Build small EPUBs shaped like AO3's downloads, for testing the phone reader.

AO3 makes its EPUBs from the work's HTML download: a preface with the tags,
summary and notes, the chapters with their notes, and an afterword. These
copy that shape with made-up stories.
"""

import zipfile
from pathlib import Path

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def _page(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head>'
        f"<body>{body}</body></html>"
    )


def _opf(title: str, author: str, description: str, pages: list[str], work_id: str | None) -> str:
    identifier = (
        f"<dc:identifier id=\"id\">https://archiveofourown.org/works/{work_id}</dc:identifier>"
        if work_id
        else '<dc:identifier id="id">urn:uuid:1234</dc:identifier>'
    )
    manifest = "".join(
        f'<item id="p{i}" href="{name}" media-type="application/xhtml+xml"/>'
        for i, name in enumerate(pages)
    )
    spine = "".join(f'<itemref idref="p{i}"/>' for i in range(len(pages)))
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>
    <dc:language>en</dc:language><dc:description>{description}</dc:description>{identifier}
  </metadata>
  <manifest>{manifest}<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>
  <spine toc="ncx">{spine}</spine>
</package>"""


def _write(path: Path, opf: str, pages: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        epub.writestr("META-INF/container.xml", CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        epub.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        epub.writestr("OEBPS/toc.ncx", "<ncx/>", compress_type=zipfile.ZIP_DEFLATED)
        for name, html in pages.items():
            epub.writestr(f"OEBPS/{name}", _page(html), compress_type=zipfile.ZIP_DEFLATED)
    return path


PREFACE_TAGS = """
<dl class="tags">
  <dt>Rating:</dt><dd><a href="https://archiveofourown.org/tags/General">General Audiences</a></dd>
  <dt>Archive Warning:</dt><dd>No Archive Warnings Apply</dd>
  <dt>Fandom:</dt><dd>Original Work</dd>
  <dt>Stats:</dt><dd>Published: 2024-03-01 Words: 1234 Chapters: 2/2</dd>
</dl>"""


def multi_chapter(path: Path) -> Path:
    """Two chapters, split over several files the way AO3's EPUBs are."""
    pages = {
        "split_000.xhtml": f"""
<div id="preface">
  <p class="message"><b>The Lighthouse Keeper's Apprentice</b><br/>Posted originally on the
  <a href="https://archiveofourown.org/">Archive of Our Own</a> at
  <a href="https://archiveofourown.org/works/987654">https://archiveofourown.org/works/987654</a>.</p>
  <div class="meta">{PREFACE_TAGS}
    <h1>The Lighthouse Keeper's Apprentice</h1>
    <div class="byline">by <a rel="author" href="https://archiveofourown.org/users/quietquill">quietquill</a></div>
    <p>Summary</p>
    <blockquote class="userstuff"><p>A storm, a lamp that won't stay lit.</p></blockquote>
    <p>Notes</p>
    <blockquote class="userstuff"><p>Thank you to my beta!</p></blockquote>
  </div>
</div>""",
        "split_001.xhtml": """
<div id="chapters" class="userstuff">
  <div class="meta group">
    <h2 class="heading">Chapter 1: The Storm</h2>
    <p>Chapter Notes</p>
    <blockquote class="userstuff"><p>This one was hard to write.</p></blockquote>
  </div>
  <div class="userstuff">
    <p>The lamp went out at <em>exactly</em> the wrong moment.</p>
    <p>“Nooo,” Wren groaned. “Not again!!!”</p>
    <p>* * *</p>
    <p>By morning the sea had calmed.<br/>The gulls were back.</p>
  </div>
  <div class="meta group">
    <p>Chapter End Notes</p>
    <blockquote class="userstuff"><p>Comments make my day.</p></blockquote>
  </div>
</div>""",
        "split_002.xhtml": """
<div class="meta group">
  <h2 class="heading">Chapter 2</h2>
  <p>Chapter Summary</p>
  <blockquote class="userstuff"><p>Wren climbs the stairs.</p></blockquote>
  <p>(See the end of the chapter for <a href="#n">more notes</a>.)</p>
</div>
<div class="userstuff">
  <p>There were one hundred and twelve steps.</p>
  <hr/>
  <p>Wren counted every one of them.</p>
</div>""",
        "split_003.xhtml": """
<div id="afterword">
  <div class="meta group">
    <p>Afterword</p>
    <p>End Notes</p>
    <blockquote class="userstuff"><p>That's all for now.</p></blockquote>
  </div>
  <div id="endnotes"><p>Please drop by the Archive and comment to let the creator know if you enjoyed their work!</p></div>
</div>""",
    }
    opf = _opf(
        "The Lighthouse Keeper's Apprentice", "quietquill",
        "&lt;p&gt;A storm, a lamp that won't stay lit.&lt;/p&gt;", list(pages), "987654",
    )
    return _write(path, opf, pages)


def one_shot(path: Path) -> Path:
    """A one-shot whose ids and classes were renamed, as ebook converters sometimes do."""
    pages = {
        "index_split_000.html": f"""
<div class="calibre">
  <p class="calibre1"><b>Tea for Two</b><br/>Posted originally on the Archive of Our Own at
  https://archiveofourown.org/works/555.</p>
  {PREFACE_TAGS}
  <h1 class="calibre2">Tea for Two</h1>
  <div class="calibre3">by Ash Grey</div>
  <p class="calibre1">Summary</p>
  <blockquote class="calibre4"><p class="calibre1">Two people, one kettle.</p></blockquote>
</div>
<div class="calibre5">
  <p class="calibre1">The kettle sang. Neither of them moved to get it.</p>
  <p class="calibre1">“Your turn,” said Ash.</p>
</div>
<div class="calibre6">
  <p class="calibre1">Please drop by the Archive and comment to let the creator know if you enjoyed their work!</p>
</div>""",
    }
    opf = _opf("Tea for Two", "Ash Grey", "Two people, one kettle.", list(pages), None)
    return _write(path, opf, pages)
