"""The window with a pretend Steam: nothing is signed in to, downloaded or installed.

    py -m mas.demo              the window, as a player sees it; START plays a short run
    py -m mas.demo --shots DIR  a PNG of each page (start, sign-in, working, done), drawn
                                on screen for a moment, for the README and for checking the look

The QR code in it is only a picture of one: it doesn't sign anything in.
"""

import ctypes
import random
import struct
import sys
import time
import zlib
from ctypes import wintypes as w
from pathlib import Path

from . import depot, engine, games, report


def fake_qr(size=29, quiet=4, seed=7):
    """Something that looks like a QR code: the three finder squares, the timing lines, and
    random modules, with a quiet zone round it - as DepotDownloader's code arrives."""
    rnd = random.Random(seed)
    grid = [[rnd.random() < 0.5 for _ in range(size)] for _ in range(size)]

    def finder(top, left):
        for y in range(-1, 8):
            for x in range(-1, 8):
                yy, xx = top + y, left + x
                if 0 <= yy < size and 0 <= xx < size:
                    ring = max(abs(y - 3), abs(x - 3))
                    grid[yy][xx] = ring in (0, 1, 3) if 0 <= y <= 6 and 0 <= x <= 6 else False
    for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
        finder(top, left)
    for i in range(8, size - 8):
        grid[6][i] = grid[i][6] = i % 2 == 0
    full = size + 2 * quiet
    blank = [False] * full
    return ([blank[:] for _ in range(quiet)] + [[False] * quiet + row + [False] * quiet for row in grid]
            + [blank[:] for _ in range(quiet)])


def run(events, picked, account, speed=1.0):
    """A short pretend run: sign in, then each picked game in turn; CS:S isn't owned."""
    def wait(seconds):
        time.sleep(seconds / speed)
        if depot.STOP.is_set():
            events.queue.put(("stopped",))
            raise SystemExit

    try:
        order = [g for g in games.GAMES if g.short in picked]
        for g in order:
            events.stage(g.app, report.WAITING)
        if account:
            events.signing_in(depot.PASSWORD, account)
            wait(4)
        else:
            events.qr(fake_qr())
            wait(6)
            events.qr(None)
        events.signed_in(account or "player")
        result = engine.Outcome()
        for g in order:
            events.stage(g.app, report.READING)
            wait(0.8)
            if g.short == "css":
                events.stage(g.app, report.NOT_OWNED)
                result.not_owned.append(g.app)
                continue
            events.stage(g.app, report.DOWNLOADING)
            for step in range(41):
                events.progress(g.app, step / 40, g.about_download)
                wait(0.08)
            events.stage(g.app, report.PACKING)
            wait(0.8)
            events.stage(g.app, report.INSTALLING)
            wait(0.3)
            n = -(-g.about_keep // 1_900_000_000)
            events.stage(g.app, report.DONE, report.packs(n))
            result.built.append((g.app, n, g.about_keep, 1))
        result.packs_in_game = sum(n for _, n, _, _ in result.built)
        events.queue.put(("finished", result))
    except SystemExit:
        pass


# ---- pictures of the window ----

PW_RENDERFULLCONTENT = 0x00000002


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", w.WORD), ("biBitCount", w.WORD), ("biCompression", w.DWORD),
                ("biSizeImage", w.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", w.DWORD), ("biClrImportant", w.DWORD)]


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png(path, width, height, bgra):
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        row = bgra[y * stride:(y + 1) * stride]
        raw.append(0)
        for i in range(0, stride, 4):
            raw += bytes((row[i + 2], row[i + 1], row[i]))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        f.write(_chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        f.write(_chunk(b"IEND", b""))


def capture(root, path):
    """The whole window, title bar too, drawn by Windows into a bitmap."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    root.update_idletasks()
    root.update()
    hwnd = w.HWND(int(root.wm_frame(), 16))
    rect = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    window_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)
    user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)
    info = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mem_dc, bitmap, 0, height, buf, ctypes.byref(info), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, window_dc)
    write_png(path, width, height, buf.raw)
    return width, height


def shots(folder):
    """A picture of each page, made from the real window with pretend news fed to it."""
    from . import window
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    app = window.App(demo=True, settings_path=folder / "demo-settings.json")
    # on screen for a moment, on top: Windows only paints what's on a screen
    app.root.attributes("-topmost", True)
    app.show(at=(40, 40))
    saved = []

    def snap(name):
        app.root.update()
        time.sleep(0.15)                      # let Windows finish the frame
        app.root.update()
        path = folder / f"{name}.png"
        capture(app.root, path)
        saved.append(path)

    snap("1-start")

    # working: signing in with the QR code, TF2 next
    app.worker = None
    picked = [g for g in games.GAMES]
    app._show_page("working")
    window.hs.update(app.where["STEAM ACCOUNT"], text="SIGNING IN")
    window.hs.update(app.where["DATA FOLDER"], text=window.short_path(app.data, 36))
    app._set_status("WORKING", window.hs.CYAN)
    window.hs.update(app.main_action, text="STOP")
    for g in picked:
        app._handle(("stage", g.app, report.WAITING, ""))
    app._handle(("qr", fake_qr()))
    snap("2-sign-in")

    app._handle(("signed_in", "player"))
    news = [("stage", 440, report.DONE, "10 packs"), ("progress", 440, 1.0, games.BY_SHORT["tf2"].about_download),
            ("stage", 240, report.NOT_OWNED, ""),
            ("stage", 4465480, report.DOWNLOADING, ""),
            ("progress", 4465480, 0.43, games.BY_SHORT["csgo"].about_download)]
    for event in news:
        app._handle(event)
    snap("3-working")

    result = engine.Outcome(built=[(440, 10, games.BY_SHORT["tf2"].about_keep, 9),
                                   (4465480, 12, games.BY_SHORT["csgo"].about_keep, 17),
                                   (620, 4, games.BY_SHORT["portal2"].about_keep, 4)],
                            not_owned=[240], packs_in_game=26)
    app._handle(("finished", result))
    snap("4-done")
    app.root.destroy()
    return saved


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--shots" in argv:
        at = argv.index("--shots")
        folder = argv[at + 1] if len(argv) > at + 1 else "shots"
        for path in shots(folder):
            print(path)
        return 0
    from . import window
    window.main(demo=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
