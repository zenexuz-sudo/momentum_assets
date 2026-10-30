"""What the tool remembers between runs (the data folder, the games picked), and the checks on
where its data may go.

The settings file lives in %LOCALAPPDATA%\\MomentumAssets, so the data folder itself can be
anywhere. The data folder holds DepotDownloader, the games' small pack indexes, logs, and the
packs while they're being built (one game's at a time, plus about 2.5 GB of downloads).
"""

import json
import os
import shutil
from pathlib import Path

FOLDER_NAME = "MomentumAssets"


def settings_file():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / FOLDER_NAME / "settings.json"


def load(path=None):
    """The settings, or another of the files the tool keeps (state.json, installed.json, a
    game's progress.json). {} if it's missing or doesn't read: the caller then starts over."""
    path = path or settings_file()
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return values if isinstance(values, dict) else {}


def save(values, path=None):
    """Written beside the file first and then swapped in, so a stop part way through leaves the
    old file whole, never half a file."""
    path = path or settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(values, indent=1), encoding="utf-8")
    os.replace(temp, path)


def default_data(game_dir):
    """A MomentumAssets folder at the top of Momentum's drive: the finished packs are then moved
    into the game, not copied, so they never need the space twice."""
    return Path(Path(game_dir).anchor.upper()) / FOLDER_NAME


def settle(picked):
    """The folder a player picks is where our folder goes, unless it already is ours."""
    picked = Path(picked)
    if picked.name.lower() == FOLDER_NAME.lower() or (picked / "state.json").is_file():
        return picked
    return picked / FOLDER_NAME


def _onedrive_roots():
    roots = []
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if os.environ.get(var):
            roots.append(Path(os.environ[var]))
    return roots


def _inside(path, root):
    try:
        Path(os.path.abspath(path)).relative_to(os.path.abspath(root))
        return True
    except ValueError:
        return False


def folder_problem(data, game_dir=None):
    """Why `data` can't be the data folder, in plain words, or None if it can."""
    data = Path(data)
    if not data.is_absolute():
        return "Pick a whole folder path, starting with a drive letter."
    if (any(_inside(data, r) for r in _onedrive_roots())
            or any(p.lower() == "onedrive" or p.lower().startswith("onedrive -") for p in data.parts)):
        return ("That folder is in OneDrive, which would upload tens of GB of downloads. "
                "Pick a folder outside OneDrive.")
    if game_dir and _inside(data, game_dir):
        return "That folder is inside Momentum. Pick one outside the game's folder."
    if not Path(data.anchor).exists():
        return f"The drive {data.anchor} isn't there."
    if data.exists() and not data.is_dir():
        return "That's a file, not a folder."
    return None


def free_bytes(path):
    """Free space on the drive holding `path` (which needn't exist yet)."""
    return shutil.disk_usage(Path(path).anchor).free


def same_drive(a, b):
    return Path(a).anchor.lower() == Path(b).anchor.lower()
