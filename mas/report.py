"""What the work tells whoever is watching: the console (Console, below) or the window.

The work calls these from its own thread; a window passes them on to its own.
"""

import re

# Where a game is. The window shows these words on each game's row.
WAITING = "WAITING"
READING = "ASKING STEAM"         # for the game's file list (short: it sits beside the name)
DOWNLOADING = "DOWNLOADING"
PACKING = "PACKING"
INSTALLING = "INSTALLING"          # moving the packs into the game: not a moment to stop
CLOSE_GAME = "CLOSE MOMENTUM"      # the packs are ready; they go in once the game is closed
DONE = "DONE"
UP_TO_DATE = "UP TO DATE"
NOT_OWNED = "NOT IN YOUR LIBRARY"
NOT_PICKED = "NOT PICKED"
FAILED = "STOPPED"

def packs(n):
    """"1 pack", "26 packs"."""
    return f"{n} pack" + ("" if n == 1 else "s")


PERCENT = re.compile(r"\s*(\d+(?:\.\d+)?)%\s")   # DepotDownloader's per-file progress lines


class Reporter:
    """Does nothing; a watcher overrides what it wants."""

    def say(self, text):
        """A line, in plain words, about what's happening."""

    def steam(self, line):
        """A line of DepotDownloader's own output."""

    def stage(self, app, stage, detail=""):
        """Where one game is now: one of the words above, and a few more words if wanted."""

    def progress(self, app, fraction, total=None):
        """How far one game is, 0 to 1; `total`, if known, the bytes it downloads in all."""

    def signing_in(self, method, account):
        """About to sign in: by "qr" code, or by "password" in the sign-in box (as `account`)."""

    def qr(self, rows):
        """A sign-in QR code to show (rows of booleans, True = dark), or None once it's done."""

    def signed_in(self, account):
        """Signed in to Steam as `account`."""


class Logged(Reporter):
    """Passes everything on to `inner`, and keeps a copy in the log file (not the percent
    lines, nor QR codes)."""

    def __init__(self, inner, log):
        self.inner, self.log = inner, log

    def _write(self, text):
        self.log.write(text + "\n")
        self.log.flush()

    def say(self, text):
        self._write(text)
        self.inner.say(text)

    def steam(self, line):
        if not PERCENT.match(line):
            self._write(line)
        self.inner.steam(line)

    def stage(self, app, stage, detail=""):
        self._write(f"[{app}] {stage}" + (f": {detail}" if detail else ""))
        self.inner.stage(app, stage, detail)

    def progress(self, app, fraction, total=None):
        self.inner.progress(app, fraction, total)

    def signing_in(self, method, account):
        self._write(f"Signing in by {method}")
        self.inner.signing_in(method, account)

    def qr(self, rows):
        self.inner.qr(rows)

    def signed_in(self, account):
        self._write(f"Signed in as {account}")
        self.inner.signed_in(account)


class Console(Reporter):
    """The command line: everything printed as it comes."""

    def say(self, text):
        print(text, flush=True)

    def steam(self, line):
        print(line, flush=True)

    def stage(self, app, stage, detail=""):
        if stage not in (DOWNLOADING, PACKING, INSTALLING):      # those say their own lines
            from . import games
            print(f"{games.name(app)}: {stage.lower()}" + (f" - {detail}" if detail else ""),
                  flush=True)

    def qr(self, rows):
        if rows:
            print(qr_text(rows), flush=True)


def qr_text(rows):
    """A QR code as black on white, two module rows per text line. DepotDownloader's own drawing
    is light-on-dark in a dark console (an inverted code some phone scanners refuse) and too
    tall for a default window."""
    if len(rows) % 2:
        rows = rows + [[False] * len(rows[0])]
    out = ["\x1b[2J\x1b[H", "Scan this with the Steam app on your phone:", ""]
    for top, bottom in zip(rows[0::2], rows[1::2]):
        cells = []
        for t, b in zip(top, bottom):
            fg = "30" if t else "97"
            bg = "40" if b else "107"
            cells.append(f"\x1b[{fg};{bg}m▀▀")
        out.append("  " + "".join(cells) + "\x1b[0m")
    out += ["", "(It refreshes now and then; any current one works.)", ""]
    return "\n".join(out)
