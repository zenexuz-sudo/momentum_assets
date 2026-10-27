"""Finds Momentum Mod, reads what it borrows from other games, and lists what it already has."""

import os
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from . import kv, vpk

# The full release first, then the Playtest (Valve's blog: the Playtest app is switched off at 1.0).
# Each with the folder Steam installs it in, should its manifest not say.
MOMENTUM_APPS = ((669270, "Momentum Mod"), (1802710, "Momentum Mod Playtest"))

# Only these top-level folders are copied in. Everything else a game holds (scripts, maps,
# resource, cfg ...) is left out. Particles are tiny, and maps can name a game's effects.
KEEP_TOP = ("materials", "models", "sound", "particles")

# Our packs in momentum/custom start with this, so we can tell them from Momentum's own.
OUR_PREFIX = "mounted_"


@dataclass
class ModFolder:
    name: str                                   # e.g. "tf", "portal2_dlc1"
    vpks: list = field(default_factory=list)    # as named in gameinfo, e.g. "tf2_misc_dir", "pak01"
    dirs: list = field(default_factory=list)


@dataclass
class Mount:
    app: int
    folders: list
    fallback: str = ""


def steam_root():
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key, value in ((r"Software\Valve\Steam", "SteamPath"),
                           (r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    p = Path(winreg.QueryValueEx(k, value)[0])
                    if p.is_dir():
                        return p
            except OSError:
                pass
    p = Path(r"C:\Program Files (x86)\Steam")
    if p.is_dir():
        return p
    raise RuntimeError("Steam isn't installed (couldn't find its folder).")


def library_folders(root):
    vdf = root / "steamapps" / "libraryfolders.vdf"
    out = [root]
    if vdf.is_file():
        top = kv.get(kv.parse(vdf.read_text(encoding="utf-8", errors="replace")), "libraryfolders") or []
        for _, lib in top:
            if isinstance(lib, list) and kv.get(lib, "path"):
                out.append(Path(kv.get(lib, "path")))
    seen, uniq = set(), []
    for p in out:
        k = str(p).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def find_game(root=None):
    """Momentum's install folder (the one holding momentum/gameinfo.txt): the full release if
    it's installed, else the Playtest."""
    return find_install(root)[1]


def find_install(root=None):
    """(Steam app id, install folder) of the Momentum find_game() finds."""
    libraries = library_folders(root or steam_root())
    for app, folder in MOMENTUM_APPS:
        for lib in libraries:
            acf = lib / "steamapps" / f"appmanifest_{app}.acf"
            if acf.is_file():
                state = kv.get(kv.parse(acf.read_text(encoding="utf-8", errors="replace")), "AppState") or []
                game = lib / "steamapps" / "common" / (kv.get(state, "installdir") or folder)
                if (game / "momentum" / "gameinfo.txt").is_file():
                    return app, game
    raise RuntimeError("Momentum Mod isn't installed through Steam on this PC.")


def read_mounts(game):
    """The mount block of momentum/gameinfo.txt, in the order the game mounts it."""
    info = kv.parse((game / "momentum" / "gameinfo.txt").read_text(encoding="utf-8", errors="replace"))
    gi = kv.get(info, "GameInfo") or []
    mounts = []
    for app, block in kv.get(gi, "mount") or []:
        if not app.isdigit() or not isinstance(block, list):
            continue
        m = Mount(int(app), [])
        for key, val in block:
            if key.lower() == "fallback":
                m.fallback = val
            elif isinstance(val, list):
                f = ModFolder(key)
                for k2, v2 in val:
                    if k2.lower() == "vpk":
                        f.vpks.append(v2)
                    elif k2.lower() == "dir":
                        f.dirs.append(v2)
                m.folders.append(f)
        mounts.append(m)
    if not mounts:
        raise RuntimeError("Couldn't find the mount list in Momentum's gameinfo.txt.")
    return mounts


def vpk_dir_file(folder, name):
    """The file a gameinfo "vpk" line names, as a depot path: 'pak01' -> 'csgo/pak01_dir.vpk'.

    The engine tries name.vpk first, then name_dir.vpk; every pack we mount is a multi-part
    one, so it's always the _dir form."""
    base = name[:-4] if name.lower().endswith("_dir") else name
    return f"{folder}/{base}_dir.vpk"


def _walk_keep(base, have):
    for top in KEEP_TOP:
        d = base / top
        if not d.is_dir():
            continue
        for dirpath, _, files in os.walk(d):
            rel = Path(dirpath).relative_to(base).as_posix().lower()
            for f in files:
                have.add(f"{rel}/{f.lower()}")


def what_momentum_has(game):
    """Every path in KEEP_TOP that Momentum finds before any mounted game.

    That's custom/* (except our own packs), the loose momentum/ tree, hammer/, and
    mount/hl2_dir.vpk. The *_placeholder.vpk stand-ins are not included: with real
    mounting they aren't loaded, so the real game's files should win over them."""
    have = set()
    custom = game / "momentum" / "custom"
    if custom.is_dir():
        for p in sorted(custom.iterdir()):
            if p.name.lower().startswith(OUR_PREFIX):
                continue
            if p.is_dir():
                _walk_keep(p, have)
            elif p.suffix.lower() == ".vpk" and not _is_part(p.name):
                have.update(e.path for e in vpk.read(p).entries)
    _walk_keep(game / "momentum", have)
    _walk_keep(game / "hammer", have)
    hl2 = game / "mount" / "hl2_dir.vpk"
    if hl2.is_file():
        have.update(e.path for e in vpk.read(hl2).entries)
    return {p for p in have if p.split("/", 1)[0] in KEEP_TOP}


def _is_part(name):
    """True for the numbered parts of a multi-part pack (pak01_000.vpk)."""
    stem = name[:-4]
    return len(stem) > 4 and stem[-4] == "_" and stem[-3:].isdigit()
