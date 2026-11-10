"""Build docs/index.html, the GitHub Pages copy of the phone reader.

phone/index.html is written for claude.ai, which adds the document's head
itself. GitHub Pages serves files as they are, so this copy gets its own head.
Run it after changing phone/index.html:  python tools/build_pages.py
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "phone" / "index.html"
OUTPUT = ROOT / "docs" / "index.html"

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Fic Listener">
<meta name="theme-color" content="#f2f4f1" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#11171a" media="(prefers-color-scheme: dark)">
<style>
  :root { padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px); }
  body { margin: 0; }
</style>
</head>
<body>
"""


def render() -> str:
    return HEAD + SOURCE.read_text(encoding="utf-8").rstrip() + "\n</body>\n</html>\n"


if __name__ == "__main__":
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
