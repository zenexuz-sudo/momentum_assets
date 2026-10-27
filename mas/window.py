"""The window: pick the games and the data folder, sign in, and watch each game come in.

In the look of its companion tools (hudstyle.py, the style file they share): borderless, with
their title bar - the mode strip, the name and [X]. Unlike their overlays it's an ordinary app:
not on top of everything, not see-through, and it has a taskbar button, so it can be found
behind other windows and minimised from there. Three pages of one height, so the window never
jumps: START
(what to get, and where), WORKING (a bar per game, and the sign-in when Steam asks for it) and
DONE.

The work runs in a thread of its own (engine.run); what it reports comes back through a queue
that the window reads ten times a second.
"""

import ctypes
import os
import queue
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog

from . import build, depot, engine, games, hudstyle as hs, momentum, report, settings

TITLE = "MomentumAssets"        # one word, as the companion tools write their names
WIDTH = 400
hs.WIDTH = WIDTH        # notes and messages wrap to this window's width
POLL_MS = 100
QR_PIXELS = 4           # per module of the QR code
QR_BOX = 172            # the white square it's drawn in: room for a 41-module code

STAGE_COLOURS = {
    report.WAITING: hs.LABEL, report.READING: hs.CYAN, report.DOWNLOADING: hs.CYAN,
    report.PACKING: hs.CYAN, report.INSTALLING: hs.CYAN, report.CLOSE_GAME: hs.RED,
    report.DONE: hs.GREEN, report.UP_TO_DATE: hs.GREEN, report.NOT_OWNED: hs.LABEL,
    report.NOT_PICKED: hs.FAINT, report.FAILED: hs.BAD,
}

DISCLAIMER = ("NOT MADE BY VALVE OR MOMENTUM. IT USES ONLY YOUR OWN STEAM ACCOUNT, AT YOUR OWN "
              "RISK. NEVER SHARE THE PACKS.")

DONE_NOTE = ("START MOMENTUM AND PLAY: THE PACKS ARE IN ITS CUSTOM FOLDER. AFTER A GAME UPDATE, "
             "RUN THIS AGAIN TO BRING THEM UP TO DATE.")

METHOD_NOTES = {
    depot.QR: "YOU'LL SCAN A CODE WITH THE STEAM APP ON YOUR PHONE.",
    depot.PASSWORD: "A STEAM SIGN-IN BOX OPENS: TYPE YOUR PASSWORD AND STEAM GUARD CODE THERE. "
                    "THIS WINDOW NEVER SEES THEM.",
}


class Events(report.Reporter):
    """Hands what the work reports to the window's thread."""

    def __init__(self):
        self.queue = queue.Queue()

    def stage(self, app, stage, detail=""):
        self.queue.put(("stage", app, stage, detail))

    def progress(self, app, fraction, total=None):
        self.queue.put(("progress", app, fraction, total))

    def signing_in(self, method, account):
        self.queue.put(("signing_in", method, account))

    def qr(self, rows):
        self.queue.put(("qr", rows))

    def signed_in(self, account):
        self.queue.put(("signed_in", account))


def gb(n):
    return engine.gb(n).upper()


def short_path(path, letters=50):
    text = str(path)
    if len(text) <= letters:
        return text
    keep = letters - 3
    return text[:keep // 3] + "..." + text[-(keep - keep // 3):]


GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_MINIMIZEBOX, WS_SYSMENU = 0x00020000, 0x00080000
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = 0x00000080, 0x00040000


def frame_hwnd(root):
    """The window Windows sees (Tk's widget sits inside it)."""
    return int(root.wm_frame(), 16)


def taskbar_button(root):
    """A borderless Tk window has no taskbar button. Ask Windows for one: an app window, with a
    minimise box (so a click on the button minimises it and brings it back, as for any app) and
    a window menu (the button's right-click), none of which draw anything without a caption.
    Then hide and show it, so the taskbar picks it up."""
    try:
        user32 = ctypes.windll.user32
        hwnd = frame_hwnd(root)
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (ex & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_MINIMIZEBOX | WS_SYSMENU)
    except (AttributeError, OSError):
        return
    root.withdraw()
    root.deiconify()


def icon(root):
    """For the taskbar button only (the title bar has none, as the tools have none): a lit lamp,
    as on the tools' bars - a cyan box filled in, on the window's black."""
    size = 32
    img = tk.PhotoImage(width=size, height=size)
    img.put(hs.BG, to=(0, 0, size, size))
    img.put(hs.CYAN, to=(3, 3, size - 3, size - 3))
    img.put(hs.BG, to=(6, 6, size - 6, size - 6))
    img.put(hs.CYAN, to=(10, 10, size - 10, size - 10))
    root.iconphoto(True, img)
    root._icon = img
    try:
        # its own taskbar button and icon, not Python's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MomentumAssets")
    except (AttributeError, OSError):
        pass


class GameRow:
    """On the START page: a tick box with the game's name, and its size on the right."""

    def __init__(self, page, game, ticked, on_change):
        self.game = game
        row = tk.Frame(page, bg=hs.BG)
        row.pack(fill="x", padx=hs.PAD)
        self.box = hs.Checkbox(row, game.name.upper(), ticked, lambda _on: on_change(), side="left")
        self.size = tk.Label(row, text=gb(game.about_keep), bg=hs.BG, font=hs.VALUE)
        self.size.pack(side="right", pady=(3, 1))
        self.show()

    def show(self):
        hs.update(self.size, fg=hs.TEXT if self.box.ticked else hs.LABEL)


class GameBar:
    """On the WORKING page: the game's name and where it is, a bar, and how far in numbers."""

    def __init__(self, page, game):
        self.game = game
        row = tk.Frame(page, bg=hs.BG)
        row.pack(fill="x", padx=hs.PAD, pady=(4, 0))
        self.name = tk.Label(row, text=game.name.upper(), fg=hs.TEXT, bg=hs.BG, font=hs.BODY)
        self.name.pack(side="left")
        self.stage_label = tk.Label(row, text="", bg=hs.BG, font=hs.VALUE)
        self.stage_label.pack(side="right")
        self.bar = hs.Progress(page)
        self.bar.track.config(bg=hs.LINE)
        self.bar.track.pack_configure(pady=(3, 0))
        self.detail = tk.Label(page, text="", fg=hs.KEY_ACTION, bg=hs.BG, font=hs.SMALL, anchor="w")
        self.detail.pack(fill="x", padx=hs.PAD, pady=(1, 2))
        self.reset()

    def reset(self):
        self.stage, self.fraction, self.total, self.packs = report.WAITING, 0.0, None, ""
        self.show()

    def download(self):
        """(downloaded, to download) in bytes: Steam's figure once it's in, the measured one
        until then; nothing for a game that's skipped or already up to date."""
        if self.stage in (report.NOT_OWNED, report.NOT_PICKED, report.UP_TO_DATE):
            return 0, 0
        total = self.total or self.game.about_download
        done = self.stage in (report.PACKING, report.INSTALLING, report.CLOSE_GAME, report.DONE)
        return (total if done else self.fraction * total), total

    def show(self):
        word = self.stage
        if self.stage == report.DOWNLOADING:
            word = f"DOWNLOADING {self.fraction * 100:.0f}%"
        hs.update(self.stage_label, text=word, fg=STAGE_COLOURS.get(self.stage, hs.TEXT))
        hs.update(self.name, fg=hs.LABEL if self.stage in (report.NOT_OWNED, report.NOT_PICKED) else hs.TEXT)
        done = self.stage in (report.DONE, report.UP_TO_DATE)
        if done or self.stage in (report.DOWNLOADING, report.PACKING, report.INSTALLING, report.CLOSE_GAME):
            self.bar.set(1.0 if done else self.fraction,
                         hs.GREEN if done else (hs.RED if self.stage == report.CLOSE_GAME else hs.CYAN))
        else:
            self.bar.set(None)
        if self.stage == report.DOWNLOADING and self.total:
            text = f"{gb(self.fraction * self.total)} OF {gb(self.total)}"
        elif self.stage == report.PACKING:
            text = "CHECKING AND FINISHING THE PACKS"
        elif self.stage == report.CLOSE_GAME:
            text = "READY: THE PACKS GO IN WHEN MOMENTUM CLOSES"
        elif self.stage == report.NOT_OWNED:
            text = "SKIPPED: THIS STEAM ACCOUNT DOESN'T OWN IT"
        elif self.stage == report.NOT_PICKED:
            text = "NOT TICKED"
        elif self.stage == report.DONE:
            text = f"{self.packs.upper()} IN MOMENTUM" if self.packs else "IN MOMENTUM"
        elif self.stage == report.UP_TO_DATE:
            text = "NOTHING NEW TO DOWNLOAD"
        elif self.stage == report.READING:
            text = "ASKING STEAM WHICH FILES IT HAS"
        else:
            text = ""
        hs.update(self.detail, text=text)


class App:
    def __init__(self, demo=False, settings_path=None):
        self.demo = demo
        self.settings_path = settings_path
        self.saved = settings.load(settings_path)
        self.events = Events()
        self.worker = None
        self.state = "setup"          # setup, working, done
        self.closing_asked = None
        self.signin_method = None

        try:
            self.game_dir = momentum.find_game()
            self.game_problem = None
        except RuntimeError:
            self.game_dir = None
            self.game_problem = "MOMENTUM MOD ISN'T INSTALLED THROUGH STEAM ON THIS PC."
        if self.saved.get("data"):
            self.data = Path(self.saved["data"])
        elif self.game_dir:
            self.data = settings.default_data(self.game_dir)
        else:
            self.data = Path(r"C:\MomentumAssets")

        root = self.root = tk.Tk()
        root.withdraw()
        root.title(TITLE)
        root.configure(bg=hs.BG)
        root.overrideredirect(True)
        icon(root)

        self.strip = hs.title_bar(root, TITLE, self._close)
        top = tk.Frame(root, bg=hs.BG)
        top.pack(fill="x", padx=hs.PAD, pady=(8, 0))
        self.status = tk.Label(top, text="", bg=hs.BG, font=hs.STATUS, anchor="w")
        self.status.pack(side="left")
        self.status_side = tk.Label(top, text="", fg=hs.TEXT, bg=hs.BG, font=hs.VALUE)
        self.status_side.pack(side="right", pady=(3, 0))
        hs.divider(root, above=4)

        self.holder = tk.Frame(root, bg=hs.BG)
        self.holder.pack(fill="x")
        self.pages = {name: tk.Frame(self.holder, bg=hs.BG) for name in ("setup", "working", "done")}
        self._setup_page(self.pages["setup"])
        self._working_page(self.pages["working"])
        self._done_page(self.pages["done"])

        hs.divider(root, above=4, below=4)
        self.message = hs.message(root, lines=2)
        self.message.pack(fill="x", padx=hs.PAD)
        actions = tk.Frame(root, bg=hs.BG)
        actions.pack(fill="x", padx=hs.PAD, pady=(2, 10))
        self.main_action = hs.button(actions, "START", self._main_action, rest=hs.TEXT,
                                     hover=hs.CYAN, font=hs.STATUS, brackets=False)
        self.main_action.pack(side="right")
        self.remove = hs.Confirm(actions, "REMOVE THE PACKS", self._remove)
        self.remove.label.pack(side="left", anchor="s", pady=(0, 2))

        # every page as tall as the tallest, so nothing jumps
        root.update_idletasks()
        tallest = max(p.winfo_reqheight() for p in self.pages.values())
        self.holder.pack_propagate(False)
        self.holder.config(height=tallest, width=WIDTH)
        root.update_idletasks()
        root.geometry(f"{WIDTH}x{root.winfo_reqheight()}")

        root.protocol("WM_DELETE_WINDOW", self._close)
        root.report_callback_exception = self._callback_error
        self._show_page("setup")
        self.refresh_setup()
        root.after(POLL_MS, self._poll)

    # ---- the pages ----

    def _group_label(self, page, text, right=None):
        """A dim name over a group, and maybe a bright value or a word on the right."""
        row = tk.Frame(page, bg=hs.BG)
        row.pack(fill="x", padx=hs.PAD, pady=(4, 0))
        tk.Label(row, text=text, fg=hs.LABEL, bg=hs.BG, font=hs.BODY).pack(side="left")
        return row

    def _setup_page(self, page):
        ticked = set(self.saved.get("games", [g.short for g in games.GAMES]))
        row = self._group_label(page, "GAMES")
        self.total_label = tk.Label(row, text="", fg=hs.TEXT, bg=hs.BG, font=hs.VALUE)
        self.total_label.pack(side="right")
        self.game_rows = [GameRow(page, g, g.short in ticked, self.refresh_setup) for g in games.GAMES]
        hs.note(page, "TF2 AND CS:GO ARE FREE: STEAM ADDS THEM TO YOUR LIBRARY. CS:S AND PORTAL 2 "
                      "HAVE TO BE BOUGHT; ONE YOU DON'T OWN IS SKIPPED.", lines=2)

        hs.divider(page, above=4)
        row = self._group_label(page, "DATA FOLDER")
        hs.word(row, "CHANGE", self._pick_folder).pack(side="right")
        self.folder_label = tk.Label(page, text="", fg=hs.TEXT, bg=hs.BG, font=hs.VALUE, anchor="w")
        self.folder_label.pack(fill="x", padx=hs.PAD, pady=(3, 0))
        self.space_note = hs.note(page, "", lines=2)

        hs.divider(page, above=4)
        row = self._group_label(page, "SIGN IN")
        self.signed_label = tk.Label(row, text="", fg=hs.TEXT, bg=hs.BG, font=hs.VALUE)
        self.signed_label.pack(side="right")
        method = self.saved.get("method", depot.QR)
        self.method = hs.Choice(page, [(depot.QR, "STEAM APP (QR CODE)"), (depot.PASSWORD, "PASSWORD")],
                                method, lambda _m: self.refresh_setup())
        self.method.frame.pack(fill="x", padx=hs.PAD)
        row = tk.Frame(page, bg=hs.BG)
        row.pack(fill="x", padx=hs.PAD, pady=(4, 0))
        self.account_name = tk.Label(row, text="STEAM ACCOUNT NAME", bg=hs.BG, font=hs.BODY)
        self.account_name.pack(side="left")
        self.account = hs.entry(row, width=20)
        self.account.insert(0, self.saved.get("account", ""))
        self.account.pack(side="right")
        self.account.bind("<KeyRelease>", lambda _e: self.refresh_setup())
        self.method_note = hs.note(page, "", lines=2)
        tk.Frame(page, bg=hs.BG, height=4).pack(fill="x")

    def _working_page(self, page):
        self.body = tk.Frame(page, bg=hs.BG)
        self.body.pack(fill="x")
        self.bars_frame = tk.Frame(self.body, bg=hs.BG)
        self.bars = {g.app: GameBar(self.bars_frame, g) for g in games.GAMES}

        self.signin_frame = tk.Frame(self.body, bg=hs.BG)
        self._group_label(self.signin_frame, "SIGN IN TO STEAM")
        inner = tk.Frame(self.signin_frame, bg=hs.BG)
        inner.pack(fill="x", padx=hs.PAD, pady=(7, 0))
        self.qr_canvas = tk.Canvas(inner, width=QR_BOX, height=QR_BOX, bg="#ffffff",
                                   highlightthickness=0)
        self.qr_canvas.pack(side="left", anchor="n")
        self.signin_steps = tk.Frame(inner, bg=hs.BG)
        self.signin_steps.pack(side="left", anchor="n", padx=(14, 0), fill="x")
        self.bars_frame.pack(fill="x")

        hs.divider(page, above=4)
        self.where = {}
        for word in ("STEAM ACCOUNT", "DATA FOLDER"):
            row = tk.Frame(page, bg=hs.BG)
            row.pack(fill="x", padx=hs.PAD, pady=(4, 0))
            tk.Label(row, text=word, fg=hs.LABEL, bg=hs.BG, font=hs.BODY).pack(side="left")
            self.where[word] = tk.Label(row, text="", fg=hs.TEXT, bg=hs.BG, font=hs.VALUE)
            self.where[word].pack(side="right")
        tk.Frame(page, bg=hs.BG, height=4).pack(fill="x")

    def _done_page(self, page):
        self.done_rows = {}
        self._group_label(page, "WHAT CAME IN")
        for g in games.GAMES:
            row = tk.Frame(page, bg=hs.BG)
            row.pack(fill="x", padx=hs.PAD, pady=(4, 0))
            name = tk.Label(row, text=g.name.upper(), fg=hs.TEXT, bg=hs.BG, font=hs.BODY)
            name.pack(side="left")
            value = tk.Label(row, text="", bg=hs.BG, font=hs.VALUE)
            value.pack(side="right")
            self.done_rows[g.app] = (name, value)
        hs.divider(page, above=8)
        self.done_note = hs.note(page, "", lines=3)

    def _show_page(self, name):
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.state = name

    # ---- START ----

    def picked(self):
        return [r.game for r in self.game_rows if r.box.ticked]

    def refresh_setup(self):
        """The START page as things are now: sizes, space, the sign-in, and whether START can go."""
        for r in self.game_rows:
            r.show()
        picked = self.picked()
        total = sum(g.about_keep for g in picked)
        hs.update(self.total_label, text=f"ABOUT {gb(total)}" if picked else "")
        hs.update(self.folder_label, text=short_path(self.data))

        problem = self.game_problem or settings.folder_problem(self.data, self.game_dir)
        space_text, short = "", False
        if not problem and picked:
            # Steam hasn't been asked yet, so a game whose packs are already in is counted as
            # up to date. If it has been updated since, the exact check after Steam's lists
            # (engine.space_problem) still stops it before anything downloads.
            already = self._already_in()
            to_get = [g for g in picked if g.short not in already]
            needs = engine.space_needed([g.about_keep for g in to_get], self.data, self.game_dir)
            parts = []
            for drive, need in needs.items():
                free = settings.free_bytes(drive)
                short = short or free < need
                parts.append(f"{drive.rstrip(chr(92))} {gb(free)} FREE, NEEDS ABOUT {gb(need)}")
            if not parts:                           # nothing to get: still say what's free
                drive = Path(self.game_dir).anchor
                parts.append(f"{drive.rstrip(chr(92))} {gb(settings.free_bytes(drive))} FREE")
            space_text = "; ".join(parts) + "."
            if len(to_get) < len(picked):
                space_text += (" GAMES ALREADY IN COUNT AS UP TO DATE; STEAM IS ASKED AFTER START."
                               if to_get else
                               "ALL OF THESE ARE ALREADY IN: START CHECKS STEAM FOR UPDATES.")
            if not settings.same_drive(self.data, self.game_dir):
                space_text += " THE PACKS END UP ON MOMENTUM'S DRIVE."
            space_text = space_text.strip()
        hs.update(self.space_note, text=problem.upper() if problem else space_text,
                  fg=hs.BAD if problem or short else hs.KEY_ACTION)

        account = self._state_account()
        method = self.method.value
        typed = self.account.get().strip()
        hs.update(self.signed_label, text=f"SIGNED IN AS {account.upper()}" if account else "")
        password = method == depot.PASSWORD
        self.account.config(state="normal" if password else "disabled",
                            disabledbackground=hs.BG, disabledforeground=hs.LABEL)
        hs.update(self.account_name, fg=hs.TEXT if password else hs.LABEL)
        note = METHOD_NOTES[method]
        if account and (not password or typed.lower() == account.lower()):
            note = "THE SAVED SIGN-IN IS USED: NO NEED TO SIGN IN AGAIN."
        hs.update(self.method_note, text=note)

        ready = bool(picked) and not problem and not short and (not password or typed)
        if self.state == "setup":
            self._set_status("READY" if ready else "NOT READY", hs.GREEN if ready else hs.FAINT)
            hs.update(self.status_side, text="")
            hs.update(self.main_action, text="START")
            hs.enable(self.main_action, ready)
            if short:
                self._say("NOT ENOUGH SPACE: FREE SOME UP, PICK A FOLDER ON ANOTHER DRIVE, OR "
                          "UNTICK A GAME.", hs.BAD)
            elif not picked:
                self._say("TICK AT LEAST ONE GAME.", hs.KEY_ACTION)
            elif password and not typed:
                self._say("TYPE YOUR STEAM ACCOUNT NAME (THE ONE YOU SIGN IN WITH).", hs.KEY_ACTION)
            else:
                self._say(DISCLAIMER, hs.LABEL)
        if self.state != "done":
            self.remove.label.pack_forget()

    def _already_in(self):
        """Short names of the games with packs of ours in Momentum already."""
        if not self.game_dir:
            return set()
        custom = self.game_dir / "momentum" / "custom"
        return {g.short for g in games.GAMES if build.ours_for(custom, g.app)}

    def _state_account(self):
        """The Steam account a saved sign-in in the data folder is for, if there is one."""
        try:
            import json
            return json.loads((self.data / "state.json").read_text()).get("account")
        except (OSError, ValueError):
            return None

    def _pick_folder(self):
        if self.state != "setup":
            return
        picked = filedialog.askdirectory(parent=self.root, title="Where should Momentum Assets keep its downloads?",
                                         initialdir=str(self.data.parent if self.data.parent.exists() else Path.home()))
        if picked:
            self.data = settings.settle(Path(picked))
            self.refresh_setup()

    def _main_action(self):
        if self.state == "setup":
            self.start()
        elif self.state in ("working", "failed"):
            self._stop()
        else:
            self.root.destroy()

    def start(self):
        picked = self.picked()
        method = self.method.value
        account = self.account.get().strip() if method == depot.PASSWORD else None
        settings.save({**self.saved, "data": str(self.data), "games": [g.short for g in picked],
                       "method": method, "account": account or self.saved.get("account", "")},
                      self.settings_path)
        for bar in self.bars.values():
            bar.reset()
            if bar.game not in picked:
                bar.stage = report.NOT_PICKED
                bar.show()
        self._show_signin(False)
        hs.update(self.where["STEAM ACCOUNT"], text=(account or self._state_account() or "SIGNING IN").upper())
        hs.update(self.where["DATA FOLDER"], text=short_path(self.data, 36))
        self._show_page("working")
        self._set_status("WORKING", hs.CYAN)
        hs.update(self.main_action, text="STOP")
        hs.enable(self.main_action, True)
        self._say("GETTING READY.", hs.CYAN)
        depot.STOP.clear()
        target = self._demo_run if self.demo else self._run
        self.worker = threading.Thread(target=target, args=({g.short for g in picked}, account),
                                       daemon=True)
        self.worker.start()

    def _run(self, picked, account):
        try:
            result = engine.run(self.data, picked, self.events, account, self.game_dir)
            self.events.queue.put(("finished", result))
        except depot.Stopped:
            self.events.queue.put(("stopped",))
        except engine.Problem as e:
            self.events.queue.put(("failed", str(e)))
        except depot.LoginFailed as e:
            self.events.queue.put(("failed", f"Steam sign-in didn't work: {e}"))
        except (depot.SteamError, build.BuildError) as e:
            self.events.queue.put(("failed", str(e)))
        except Exception:
            self.events.queue.put(("failed", self._crash_note(traceback.format_exc())))

    def _crash_note(self, text):
        path = self.data / "logs" / f"crash_{time.strftime('%Y-%m-%d_%H%M%S')}.txt"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError:
            pass
        return f"Something went wrong. The details are in {path}."

    # ---- WORKING ----

    def _poll(self):
        try:
            while True:
                self._handle(self.events.queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll)

    def _handle(self, event):
        kind = event[0]
        if kind == "stage":
            _, app, stage, detail = event
            bar = self.bars.get(app)
            if bar:
                bar.stage = stage
                if stage == report.DONE:
                    bar.packs = detail
                bar.show()
            self._show_overall()
            if stage == report.CLOSE_GAME:
                self._say("CLOSE MOMENTUM: THE PACKS GO IN AS SOON AS IT'S CLOSED.", hs.RED)
            elif stage == report.DOWNLOADING:
                self._say("DOWNLOADING. YOU CAN USE THE PC MEANWHILE; IF YOU STOP, IT PICKS UP "
                          "WHERE IT LEFT OFF NEXT TIME.", hs.CYAN)
        elif kind == "progress":
            _, app, fraction, total = event
            bar = self.bars.get(app)
            if bar:
                bar.fraction = fraction
                bar.total = total or bar.total
                bar.show()
            self._show_overall()
        elif kind == "signing_in":
            _, method, account = event
            self._signing_in(method, account)
        elif kind == "qr":
            _, rows = event
            if rows:
                self._signing_in(depot.QR, None)
                self._draw_qr(rows)
            elif self.signin_method == depot.QR:
                self._waiting_for_code()
        elif kind == "signed_in":
            self._show_signin(False)
            hs.update(self.where["STEAM ACCOUNT"], text=event[1].upper())
            self._say(f"SIGNED IN AS {event[1].upper()}.", hs.CYAN)
        elif kind == "finished":
            self._finished(event[1])
        elif kind == "stopped":
            self._back_to_setup("STOPPED. START AGAIN TO PICK UP WHERE IT LEFT OFF.", hs.KEY_ACTION)
        elif kind == "failed":
            self._failed(event[1])

    def _show_overall(self):
        got, total = (sum(x) for x in zip(*(b.download() for b in self.bars.values())))
        hs.update(self.status_side, text=f"{gb(got)} OF {gb(total)}" if got else "")

    def _signing_in(self, method, account):
        self.signin_method = method
        self._set_status("SIGN IN", hs.CYAN)
        self.qr_canvas.pack_forget()
        self.signin_steps.pack_forget()
        if method == depot.QR:
            self.qr_canvas.pack(side="left", anchor="n")
            if not self.qr_canvas.find_withtag("module"):
                self._waiting_for_code()
            self._steps(["OPEN THE STEAM APP ON YOUR PHONE",
                         "TAP THE SHIELD (STEAM GUARD)",
                         "TAP SCAN A QR CODE, AND POINT IT AT THIS CODE",
                         "APPROVE THE SIGN-IN"], width=WIDTH - 2 * hs.PAD - QR_BOX - 14)
            self.signin_steps.pack(side="left", anchor="n", padx=(14, 0), fill="x")
            self._say("THE CODE CHANGES NOW AND THEN; ANY CODE SHOWING WORKS.", hs.CYAN)
        else:
            self.qr_canvas.delete("all")
            self._steps(["TYPE YOUR PASSWORD THERE AND PRESS ENTER",
                         "APPROVE THE SIGN-IN ON YOUR PHONE, OR TYPE THE STEAM GUARD CODE "
                         "STEAM SENDS YOU"], width=WIDTH - 2 * hs.PAD,
                        before=f"A STEAM SIGN-IN BOX HAS OPENED FOR {account.upper()}.",
                        after="THE BOX IS STEAM'S SIGN-IN: THIS WINDOW NEVER SEES YOUR PASSWORD.")
            self.signin_steps.pack(side="left", anchor="n", fill="x")
            self._say("WAITING FOR THE STEAM SIGN-IN BOX.", hs.CYAN)
        self._show_signin(True)

    def _steps(self, steps, width, before=None, after=None):
        """Numbered steps: the numbers in a column of their own, in cyan, and each step's words
        hanging beside its number, in white. `before` and `after` are lines across the top and
        the foot."""
        frame = self.signin_steps
        for child in frame.winfo_children():
            child.destroy()
        number_width = 18
        row = 0
        if before:
            tk.Label(frame, text=before, fg=hs.TEXT, bg=hs.BG, font=hs.BODY, justify="left",
                     anchor="w", wraplength=width).grid(row=row, column=0, columnspan=2,
                                                        sticky="w", pady=(0, 10))
            row += 1
        for n, text in enumerate(steps, 1):
            tk.Label(frame, text=str(n), fg=hs.CYAN, bg=hs.BG, font=hs.VALUE, anchor="nw").grid(
                row=row, column=0, sticky="nw", pady=(0, 10))
            tk.Label(frame, text=text, fg=hs.TEXT, bg=hs.BG, font=hs.BODY, justify="left",
                     anchor="nw", wraplength=width - number_width).grid(
                row=row, column=1, sticky="nw", pady=(0, 10))
            row += 1
        if after:
            tk.Label(frame, text=after, fg=hs.KEY_ACTION, bg=hs.BG, font=hs.SMALL, justify="left",
                     anchor="w", wraplength=width).grid(row=row, column=0, columnspan=2, sticky="w")
        frame.grid_columnconfigure(0, minsize=number_width)

    def _show_signin(self, on):
        if on:
            self.bars_frame.pack_forget()
            self.signin_frame.pack(fill="x")
        else:
            self.signin_frame.pack_forget()
            self.bars_frame.pack(fill="x")
            if self.state == "working":
                self._set_status("WORKING", hs.CYAN)

    def _waiting_for_code(self):
        """The white box with no code in it: one's on its way (at the start, or after Steam let
        the last one lapse - a code that's run out mustn't stay up to be scanned)."""
        c = self.qr_canvas
        c.delete("all")
        c.create_text(QR_BOX // 2, QR_BOX // 2, text="GETTING\nA CODE ...", fill=hs.LABEL,
                      font=hs.SMALL_BOLD, justify="center", tags="waiting")

    def _draw_qr(self, rows):
        """Black on white, each module QR_PIXELS square, in the middle of the white box."""
        c = self.qr_canvas
        c.delete("all")
        n = len(rows)
        px = max(1, min(QR_PIXELS, QR_BOX // max(n, 1)))
        start = (QR_BOX - n * px) // 2
        for y, row in enumerate(rows):
            for x, dark in enumerate(row):
                if dark:
                    c.create_rectangle(start + x * px, start + y * px, start + (x + 1) * px - 1,
                                       start + (y + 1) * px - 1, fill="#000000", outline="#000000",
                                       tags="module")

    def _finished(self, result):
        self._show_signin(False)
        self._show_page("done")
        got_any = bool(result.built or result.up_to_date)
        if got_any:
            self._set_status(f"DONE: {report.packs(result.packs_in_game).upper()} INSTALLED", hs.GREEN)
        else:
            self._set_status("NOTHING INSTALLED", hs.FAINT)
        hs.update(self.status_side, text="")
        built = {app: (n, size) for app, n, size, _ in result.built}
        fresh = dict(result.up_to_date)
        for g in games.GAMES:
            name, value = self.done_rows[g.app]
            if g.app in built:
                n, size = built[g.app]
                text, colour = f"{report.packs(n).upper()}, {gb(size)}", hs.TEXT
            elif g.app in fresh:
                text, colour = f"UP TO DATE, {report.packs(fresh[g.app]).upper()}", hs.TEXT
            elif g.app in result.not_owned:
                text, colour = "NOT IN YOUR LIBRARY", hs.LABEL
            else:
                text, colour = "NOT TICKED", hs.FAINT
            hs.update(value, text=text, fg=colour)
            hs.update(name, fg=hs.TEXT if colour == hs.TEXT else hs.LABEL)
        hs.update(self.main_action, text="CLOSE")
        hs.enable(self.main_action, True)
        hs.update(self.done_note, text=DONE_NOTE if got_any else "")
        if got_any:
            self.remove.label.pack(side="left", anchor="s", pady=(0, 2))
            self._say("ALL DONE. YOU CAN CLOSE THIS WINDOW.", hs.GREEN)
        else:
            self._say("THIS STEAM ACCOUNT DOESN'T OWN THE GAMES YOU TICKED, SO NOTHING WAS "
                      "DOWNLOADED.", hs.KEY_ACTION)

    def _failed(self, text):
        self._show_signin(False)
        self._set_status("STOPPED", hs.BAD)
        for bar in self.bars.values():
            if bar.stage in (report.READING, report.DOWNLOADING, report.PACKING, report.WAITING):
                bar.stage = report.FAILED
                bar.show()
        hs.update(self.main_action, text="BACK")
        self.state = "failed"
        self._say(text.upper(), hs.BAD)

    def _back_to_setup(self, text, colour):
        self._show_signin(False)
        self._show_page("setup")
        self.refresh_setup()
        self._say(text, colour)

    def _stop(self):
        if self.state == "failed":
            self._back_to_setup(DISCLAIMER, hs.LABEL)
            return
        if any(b.stage == report.INSTALLING for b in self.bars.values()):
            self._say("NEARLY DONE: PUTTING THE PACKS IN. ONE MOMENT.", hs.CYAN)
            return
        if self.closing_asked != "stop":
            self.closing_asked = "stop"
            self._say("CLICK STOP AGAIN TO STOP. NEXT TIME IT PICKS UP WHERE IT LEFT OFF.", hs.RED)
            self.root.after(3000, lambda: setattr(self, "closing_asked", None))
            return
        self.closing_asked = None
        hs.enable(self.main_action, False)
        self._say("STOPPING ...", hs.KEY_ACTION)
        depot.stop_all()

    def _close(self):
        """The frame's X. While the work runs, the first click only asks."""
        if self.state != "working" or not (self.worker and self.worker.is_alive()):
            self.root.destroy()
            return
        if any(b.stage == report.INSTALLING for b in self.bars.values()):
            self._say("NEARLY DONE: PUTTING THE PACKS IN. ONE MOMENT.", hs.CYAN)
            return
        if self.closing_asked != "close":
            self.closing_asked = "close"
            self._say("CLOSE AGAIN TO STOP. NEXT TIME IT PICKS UP WHERE IT LEFT OFF.", hs.RED)
            self.root.after(3000, lambda: setattr(self, "closing_asked", None))
            return
        depot.stop_all()
        self.root.destroy()

    def _remove(self):
        if build.game_running():
            self._say("CLOSE MOMENTUM FIRST, THEN REMOVE THE PACKS.", hs.RED)
            return
        removed = [] if self.demo else build.uninstall(self.game_dir)
        self._set_status(f"REMOVED {report.packs(len(removed)).upper()}", hs.FAINT)
        self.remove.label.pack_forget()
        self._say("THE PACKS ARE OUT OF MOMENTUM. RUN THIS AGAIN ANY TIME TO PUT THEM BACK.", hs.KEY_ACTION)

    # ---- bits ----

    def _set_status(self, word, colour):
        hs.update(self.status, text=word, fg=colour)
        self.strip.config(bg=colour if colour not in (hs.FAINT, hs.LABEL) else hs.LINE)

    def _say(self, text, colour=hs.CYAN):
        hs.update(self.message, text=text, fg=colour)

    def _callback_error(self, *exc):
        self._say(self._crash_note("".join(traceback.format_exception(*exc))).upper(), hs.BAD)

    def show(self, at=None):
        """On screen: in the middle, or at (x, y)."""
        root = self.root
        root.update_idletasks()
        if at is None:
            at = ((root.winfo_screenwidth() - root.winfo_reqwidth()) // 2,
                  max(0, (root.winfo_screenheight() - root.winfo_reqheight()) // 3))
        root.geometry(f"+{at[0]}+{at[1]}")
        root.deiconify()
        root.update_idletasks()
        taskbar_button(root)

    def mainloop(self):
        self.show()
        self.root.mainloop()

    # ---- the demo: everything above, with a pretend Steam ----

    def _demo_run(self, picked, account):
        from . import demo
        demo.run(self.events, picked, account)


def main(demo=False):
    try:
        App(demo=demo).mainloop()
    except Exception:
        # with no console to print to, say so in a box, and keep the details
        text = traceback.format_exc()
        path = settings.settings_file().parent / "crash.txt"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError:
            pass
        try:
            from tkinter import messagebox
            messagebox.showerror(TITLE, f"MomentumAssets couldn't start.\n\nThe details are in {path}")
        except Exception:
            pass
        os._exit(1)
    os._exit(0)          # the work's thread, and any DepotDownloader, go with the window
