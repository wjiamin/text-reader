# ao3-reader

Turn works on [Archive of Our Own](https://archiveofourown.org) into audiobooks
you can listen to on your phone. The voice is [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M),
a small open model that sounds natural and runs on an ordinary computer: no
GPU, no account, nothing sent to anyone.

```
ao3-reader make https://archiveofourown.org/works/12345678
```

gives you `Title - Author.m4b`: one audiobook file with a chapter marker for
every chapter, ready for your phone's audiobook app.

## What it does for you

- **Downloads the whole work in one request**, skipping AO3's adult-content prompt.
- **Cleans the text up for listening.** Scene breaks (`***`, `~~~`, `oOo`, dividers)
  become pauses instead of "asterisk asterisk asterisk". Drawn-out words like
  "Nooo" and "Pleeease" are read as "No" and "Please". Keysmashes, emoji,
  footnote numbers, links and AO3's hidden "Chapter Text" headings are dropped.
  "Mr." and "Dr." are read as "Mister" and "Doctor".
- **Reads the title, author and summaries**, and skips author's notes unless you
  ask for them with `--notes`.
- **Remembers finished chapters.** When a work in progress updates, run the same
  command again and only the new chapters are read. If you stop it partway
  (Ctrl+C), it picks up from the last finished chapter.

## Setting it up (once)

You need Python 3.10 to 3.13. The easiest way to install is with
[uv](https://docs.astral.sh/uv/getting-started/installation/):

```
uv tool install git+https://github.com/wjiamin/text-reader
```

(or `pipx install git+https://github.com/wjiamin/text-reader`).

The first time you make an audiobook it downloads the voice model, about
340 MB. It's kept for next time.

## Making an audiobook

```
ao3-reader make https://archiveofourown.org/works/12345678
```

How long it takes depends a lot on your computer, and on a laptop it can be
close to real time: a 100,000-word work is about 10 hours of audio. Each
chapter prints how long it took and how that compares to real time, so you'll
know after the first one. `--model small` is quicker. Start a long work
before bed, or do a few chapters at a time:

```
ao3-reader make <link> --chapters 1-5
ao3-reader make <link> --chapters 6-
```

Useful options:

| Option | What it does |
|---|---|
| `--voice bm_george` | Pick a voice. `ao3-reader voices` lists them. |
| `--speed 1.1` | Read faster (0.5 to 2.0). Your phone's player can also change speed. |
| `--notes` | Also read the author's notes. |
| `--no-summary` | Skip the summaries. |
| `--chapters 3-5` | Only some chapters. |
| `--format mp3` | A folder of MP3s, one per chapter, instead of one `.m4b`. |
| `--model small` | A smaller, quicker model that sounds slightly worse. |
| `-o ~/Audiobooks` | Where to save it. |

To check what will be read before spending time on audio:

```
ao3-reader preview <link> | less
```

To compare voices, this saves a short clip in each one:

```
ao3-reader sample --voice af_heart --voice af_bella --voice bm_george
```

## Getting it onto your phone

**iPhone:** AirDrop the `.m4b` to your phone, or save it to iCloud Drive. Open it
from the Files app with **Books**, or with the free **BookPlayer** app, which
remembers your place and handles chapters well.

**Android:** copy the `.m4b` over (Google Drive, a USB cable, or anything else) and
open it with an audiobook app such as **Voice** (free, open source) or
**Smart AudioBook Player**.

If your player doesn't like `.m4b`, use `--format mp3`.

## Names the voice gets wrong

Make a text file of respellings, one per line:

```
# my-fandom.txt
Daenerys = Duh nair iss
Saoirse = Ser sha
Y/N = Sam
OC = O C
```

and pass it with `--pronounce my-fandom.txt` (you can pass several). Matching
ignores capitals, and only whole words are replaced. The `Y/N` line is handy
for reader-insert fics.

## Locked works, and when AO3 blocks the download

Some works are only visible when logged in, and sometimes AO3's bot protection
turns automated downloads away. Either way:

1. Open the work in your browser (logged in if needed).
2. Click **Entire Work** so every chapter is on one page.
3. Save the page (Ctrl+S, or Cmd+S on a Mac).
4. Run `ao3-reader make "The Saved Page.html"`.

## Being a good guest

This is for your own listening. Please:

- **Don't share the audio you make.** Sharing a recording of someone's work is
  podfic, and that needs the author's permission. Many AO3 authors don't want
  AI voices used on their work at all.
- **Don't use it to bulk-download.** It makes one request per work, and AO3 asks
  that automated tools go easy on its servers.

## For developers

```
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest
```

The code is in `src/ao3reader/`: `fetch.py` downloads, `parse.py` reads the AO3
page, `clean.py` and `script.py` decide what gets said, `tts.py` is the voice,
and `audiobook.py` caches chapters and packages the file.
