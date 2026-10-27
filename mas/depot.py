"""Runs DepotDownloader (github.com/SteamRE/DepotDownloader) to fetch chosen files from Steam.

The player signs in once: by scanning a QR code with the Steam phone app, or with their
password and Steam Guard, typed into DepotDownloader's own console box (see signin_box.py), so
this tool never sees the password. DepotDownloader keeps the login (its own saved token), and
we keep only the account name, in state.json.
"""

import hashlib
import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import report

VERSION = "3.4.0"
ZIP_URL = (f"https://github.com/SteamRE/DepotDownloader/releases/download/"
           f"DepotDownloader_{VERSION}/DepotDownloader-windows-x64.zip")
ZIP_SHA256 = "41c9e9f0df54b3ad02e67a11726756e5c73283bd7c2e1b04acfa5ae4c2ed3767"

# Our own Steam logon id, so we never knock another DepotDownloader (or Steam) session off.
LOGIN_ID = 0x4D4F4D41  # "MOMA"
RETRIES = 3
RETRY_WAIT = 15

# The two ways to sign in, as state.json remembers which one the player used.
QR, PASSWORD = "qr", "password"

_SUCCESS = re.compile(r"login with -username (\S+) -remember-password")
_NOT_OWNED = re.compile(r"App (\d+) \((.*)\) is not available from this account")


class SteamError(RuntimeError):
    pass


class NotOwned(SteamError):
    pass


class LoginFailed(SteamError):
    pass


class Stopped(SteamError):
    """The player stopped it."""


_LOGIN_FAILED = ("Unable to login", "Access token was rejected", "Enter account password")


def ensure_tool(data, say=print):
    """Path to DepotDownloader.exe, downloading the pinned release the first time."""
    folder = data / "tools" / f"DepotDownloader_{VERSION}"
    exe = folder / "DepotDownloader.exe"
    if exe.is_file():
        return exe
    folder.mkdir(parents=True, exist_ok=True)
    zpath = data / "tools" / "DepotDownloader-windows-x64.zip"
    if not zpath.is_file() or _sha256(zpath) != ZIP_SHA256:
        say(f"Getting DepotDownloader {VERSION} ...")
        urllib.request.urlretrieve(ZIP_URL, zpath)
    if _sha256(zpath) != ZIP_SHA256:
        zpath.unlink()
        raise SteamError("The DepotDownloader download didn't match its known checksum, so it wasn't used.")
    with zipfile.ZipFile(zpath) as z:
        z.extract("DepotDownloader.exe", folder)
    return exe


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# No console window of its own for DepotDownloader when we read its output.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0     # CREATE_NO_WINDOW
_NEW_CONSOLE = 0x00000010 if sys.platform == "win32" else 0   # CREATE_NEW_CONSOLE

_running = set()     # the DepotDownloaders running now
STOP = threading.Event()


def stop_all():
    """Stop: end every DepotDownloader we started, and start no more until STOP is cleared.
    What they'd downloaded is fetched again next time (parts left half done are never
    trusted)."""
    STOP.set()
    for proc in list(_running):
        try:
            proc.kill()
        except OSError:
            pass


class Session:
    def __init__(self, data, reporter):
        self.data = data
        self.report = reporter
        self.exe = ensure_tool(data, reporter.say)
        self.state_file = data / "state.json"
        self.state = json.loads(self.state_file.read_text()) if self.state_file.is_file() else {}

    @property
    def account(self):
        return self.state.get("account")

    def _save(self):
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def sign_in_with_password(self, account, app):
        """The password sign-in: DepotDownloader in a console box of its own, where the player
        types their password and Steam Guard code (or approves in the Steam app). We only wait
        for it. True if it worked; the login is then saved as with the QR code."""
        self.report.signing_in(PASSWORD, account)
        self.report.say(f"Signing in to Steam as {account}: type your password in the "
                        "Steam sign-in box.")
        folder = self.data / "signin"
        folder.mkdir(parents=True, exist_ok=True)
        command = [str(self.exe), "-app", str(app), "-manifest-only", "-dir", str(folder),
                   "-loginid", str(LOGIN_ID), "-username", account, "-remember-password"]
        if getattr(sys, "frozen", False):
            # MomentumAssets.exe: it opens the box itself (signin_box makes the console)
            code = subprocess.call([sys.executable, "--signin-box", account, *command],
                                   cwd=str(self.data))
        else:
            code = subprocess.call([_console_python(), "-m", "mas.signin_box", account, *command],
                                   cwd=str(self.data), creationflags=_NEW_CONSOLE,
                                   env=_with_path(Path(__file__).resolve().parent.parent))
        if code != 0:
            return False
        self.state["account"], self.state["method"] = account, PASSWORD
        self._save()
        self.report.signed_in(account)
        return True

    def run(self, app, out_dir, *, manifest_only=False, filelist=None, on_percent=None):
        """Run DepotDownloader for one app, trying again after a passing Steam fault
        ("A task was canceled": a server that didn't answer in time). `on_percent(n)` hears
        its progress through the run, 0 to 100."""
        for attempt in range(1, RETRIES + 1):
            try:
                return self._login_and_run(app, out_dir, manifest_only, filelist, on_percent)
            except (NotOwned, LoginFailed, Stopped):
                raise
            except SteamError:
                if attempt == RETRIES:
                    raise
                self.report.say(f"Steam didn't answer properly; trying again in {RETRY_WAIT} s "
                                f"(attempt {attempt + 1} of {RETRIES}).")
                time.sleep(RETRY_WAIT)

    def _login_and_run(self, app, out_dir, manifest_only, filelist, on_percent):
        """Signs in by QR code if we have no saved login. If Steam turns the saved login down,
        signs in once more the way the player did last time: password or QR code."""
        had_login = bool(self.account)
        try:
            return self._run(app, out_dir, manifest_only, filelist, on_percent)
        except LoginFailed:
            if not had_login:
                raise
            self.report.say("The saved Steam login no longer works, so we'll sign in again.")
            account = self.state.pop("account", None)
            self._save()
            if self.state.get("method") == PASSWORD:
                if not self.sign_in_with_password(account, app):
                    raise LoginFailed("The Steam sign-in didn't finish. Try again.")
            return self._run(app, out_dir, manifest_only, filelist, on_percent)
        except (NotOwned, Stopped):
            raise
        except SteamError:
            # The QR sign-in can succeed and still end in an error: after a reconnect,
            # DepotDownloader keeps polling an old QR request. Go again with the saved login.
            if had_login or not self.account:
                raise
            self.report.say("Signed in. Carrying on with the saved login.")
            return self._run(app, out_dir, manifest_only, filelist, on_percent)

    def _run(self, app, out_dir, manifest_only, filelist, on_percent):
        if STOP.is_set():
            raise Stopped("Stopped.")
        args = [str(self.exe), "-app", str(app), "-dir", str(out_dir), "-loginid", str(LOGIN_ID),
                "-remember-password"]
        if self.account:
            args += ["-username", self.account]
        else:
            args += ["-qr"]
            self.report.signing_in(QR, None)
            self.report.say("Sign in: scan the QR code with the Steam app on your phone.")
        if manifest_only:
            args.append("-manifest-only")
        if filelist:
            args += ["-filelist", str(filelist)]
        out_dir.mkdir(parents=True, exist_ok=True)

        lines = []
        qr = _QrRelay(self.report.qr)
        self.report.steam(f"$ DepotDownloader {' '.join(args[1:])}")
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, cwd=str(self.data),
                                creationflags=_NO_WINDOW)
        _running.add(proc)
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if qr.feed(line):
                    continue
                lines.append(line)
                self.report.steam(line)
                p = report.PERCENT.match(line)
                if p and on_percent:
                    on_percent(float(p.group(1)))
                m = _SUCCESS.search(line)
                if m:
                    self.state["account"], self.state["method"] = m.group(1), QR
                    self._save()
                    self.report.qr(None)
                    self.report.signed_in(m.group(1))
            code = proc.wait()
        finally:
            _running.discard(proc)
            if qr.shown and not self.account:
                # the run ended without a sign-in: its code is dead, so take it off the screen
                self.report.qr(None)
        if STOP.is_set():
            raise Stopped("Stopped.")

        text = "\n".join(lines)
        m = _NOT_OWNED.search(text)
        if m:
            raise NotOwned(f"{m.group(2)} (app {m.group(1)}) isn't in your Steam library yet.")
        if any(s in text for s in _LOGIN_FAILED):
            raise LoginFailed("Steam login failed. See the log for details.")
        if code != 0:
            raise SteamError(f"DepotDownloader stopped with code {code} (app {app}). See the log.")
        return text


class _QrRelay:
    """Takes DepotDownloader's QR code out of its output, as rows of modules (True = dark),
    and hands each one it draws to `show`, to be drawn our way."""

    HEADER = "Use the Steam Mobile App to sign in with this QR code"

    def __init__(self, show):
        self.show = show
        self.rows = None
        self.size = 0
        self.shown = False          # a code went out during this run

    def feed(self, line):
        """Takes the line if it's part of a QR code; returns True when it did."""
        if self.HEADER in line:
            self.rows, self.size = [], 0
            return True
        if self.rows is None:
            return False
        if not self.rows:
            if not line:
                return True
            self.size = len(line) // 2
        self.rows.append([line[i * 2:i * 2 + 2].strip(" ") != "" for i in range(self.size)])
        if len(self.rows) >= self.size:
            self.show(self.rows)
            self.shown = True
            self.rows = None
        return True


def _console_python():
    """python.exe, not pythonw.exe: the sign-in box needs a console to show."""
    exe = Path(sys.executable)
    if exe.stem.lower() == "pythonw":
        exe = exe.with_name("python" + exe.suffix)
    return str(exe)


def _with_path(root):
    """The environment, with `root` on PYTHONPATH so `-m mas.signin_box` is found."""
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


@dataclass
class DepotFile:
    path: str      # lowercase, forward slashes, as in the game folder
    size: int
    sha1: str
    depot: int


@dataclass
class Manifest:
    depot: int
    manifest: str
    date: str
    files: list
    disk_bytes: int
    download_bytes: int


def read_manifests(folder):
    """Parse the manifest_<depot>_<id>.txt files DepotDownloader writes with -manifest-only."""
    out = []
    for p in sorted(folder.glob("manifest_*_*.txt")):
        _, depot, mid = p.stem.split("_", 2)
        files, date, disk, comp = [], "", 0, 0
        in_list = False
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not in_list:
                if line.startswith("Manifest ID / date"):
                    date = line.split("/", 2)[-1].strip()
                elif line.startswith("Total bytes on disk"):
                    disk = int(line.split(":")[1])
                elif line.startswith("Total bytes compressed"):
                    comp = int(line.split(":")[1])
                elif line.strip().startswith("Size Chunks File SHA"):
                    in_list = True
                continue
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            size, _chunks, sha, flags, name = parts
            if int(flags, 16) & 0x40:  # a directory, not a file
                continue
            files.append(DepotFile(name.replace("\\", "/").lower(), int(size), sha, int(depot)))
        out.append(Manifest(int(depot), mid, date, files, disk, comp))
    return out


def console_utf8():
    """Make DepotDownloader's QR code (block characters) survive the trip through our pipe."""
    if sys.platform == "win32":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.SetConsoleOutputCP(65001)
            # Colours for the QR code: turn on escape codes in an old-style console window.
            handle = k32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k32.GetConsoleMode(handle, ctypes.byref(mode)):
                k32.SetConsoleMode(handle, mode.value | 0x0004)
        except OSError:
            pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def no_quick_edit():
    """A click in the console window starts Windows' 'Select' mode, which freezes all output
    (and so the build) until Esc. Turn that off while we run; returns a function that puts
    the window's mode back."""
    if sys.platform != "win32":
        return lambda: None
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if not k32.GetConsoleMode(handle, ctypes.byref(mode)):
            return lambda: None
        old = mode.value
        # Clearing QuickEdit only sticks with the extended-flags bit set.
        k32.SetConsoleMode(handle, (old | 0x0080) & ~0x0040)
        return lambda: k32.SetConsoleMode(handle, old)
    except OSError:
        return lambda: None
