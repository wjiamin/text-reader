# ao3-reader

Turn works on [Archive of Our Own](https://archiveofourown.org) into audiobooks
you can listen to on your phone. The voice is [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M),
a small open model that sounds natural and runs on an ordinary computer: no
GPU, no account, nothing sent to anyone.

Type `ao3-reader` and a page opens in your browser. Paste a link to a work and
press **Read it**. Each chapter is ready to play as soon as it's read, so you
can start listening within a minute or two while the rest is read. At the end
you get one audiobook file with a chapter marker for every chapter, to keep
on your phone.

Your phone can use the page too: scan the QR code it shows, and paste links
and listen right on your phone while it's on the same Wi-Fi as the computer.

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

## The web page

```
ao3-reader
```

opens the page at http://127.0.0.1:8000. Keep the window that started it open
while it reads; press Ctrl+C there to quit.

- **Paste a link, press Read it.** The parts appear as a list with play buttons
  that light up as each one is read. Playback carries on to the next part by
  itself and remembers where you stopped.
- **On your phone:** scan the QR code shown on the computer's page (or open the
  link printed in the window). The link carries a private key, so other people
  on your Wi-Fi can't use it. Your phone remembers the key after the first
  scan. The computer has to stay on and awake while you listen this way.
- **To keep it:** when it's finished, press **Download the audiobook**. Finished
  audiobooks are also saved in an `AO3 Audiobooks` folder in your home folder,
  and listed on the page under "Your audiobooks".
- **Voice and options** on the page lets you pick a voice, read faster or slower,
  read only some chapters, include author's notes, or upload a saved page for
  locked works.

To change how it starts, use `ao3-reader web` with options: `--port 8080` for
another port, `--no-phone` to allow only this computer, `-o FOLDER` to save
audiobooks somewhere else, and `--no-browser` to not open the page
automatically. For example: `ao3-reader web --port 8080`.

## Fic Listener: reading on your phone, no computer

`phone/index.html` is a page that runs entirely on your phone. Download a work
from AO3 with **Download → EPUB**, save it to Files, and open it in the page.
It cleans the text up the same way, reads it with your phone's own voices,
and remembers your place down to the paragraph. Tap any paragraph to read from
there. Stories stay on the phone.

For the most natural sound on an iPhone, download an *Enhanced* or *Premium*
voice in Settings → Accessibility → Spoken Content → Voices, then pick it
under "Voice and settings".

The catch: iPhones stop web pages from talking when the screen locks, so it
keeps the screen on while it reads. There's an experimental setting that tries
to keep going with the screen locked; whether it works depends on the phone.
To listen with the phone in your pocket, use the audiobook made on a computer.

## Making an audiobook from the command line

If you'd rather not use the web page:

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
4. On the web page, choose the saved file under **Voice and options** and press
   **Read it**. From the command line: `ao3-reader make "The Saved Page.html"`.

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
`audiobook.py` caches chapters and packages the file, and `web.py` with
`static/index.html` is the web page.

The phone reader is the single file `phone/index.html`. Its tests drive it in
a browser with a stand-in voice; they run when Playwright and Chromium are
installed (`uv pip install playwright`) and are skipped otherwise.
