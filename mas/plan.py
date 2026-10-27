"""Decides which files to keep from each game's packs, and what that costs to download.

The rules:
- only the packs Momentum's gameinfo.txt names, in its order;
- only materials/, models/, sound/ and particles/;
- no voice lines;
- nothing Momentum already has (custom/, the momentum/ folder, hammer/, hl2), because our
  packs go in custom/ and load first, so they'd otherwise hide Momentum's own files;
- nothing an earlier pack of the same game already gave (its order in gameinfo decides, as
  with real mounting).

Each game's packs are complete on their own, so any set of games can be picked, and picking
another later never changes the packs already built. Where two games have the same file, the
one gameinfo mounts first still wins: our packs load in name order, and the names carry the
mount order. (The overlap costs about 0.6 GB, nearly all of it CS:GO's.)
"""

from collections import defaultdict
from dataclasses import dataclass, field

from . import momentum, vpk

# Folders of spoken lines. sound/vo/ is TF2's and Portal 2's; the others are CS:S's and CS:GO's.
VOICE_PREFIXES = ("sound/vo/", "sound/player/vo/", "sound/bot/", "sound/radio/")


def is_voice(path):
    return path.startswith(VOICE_PREFIXES)


@dataclass
class Pack:
    """One pack gameinfo names, e.g. tf/tf2_textures_dir.vpk."""
    app: int
    dir_path: str                 # depot path of the _dir file
    parts: dict = field(default_factory=dict)   # part number -> size on Steam (bytes)
    part_sha: dict = field(default_factory=dict)  # part number -> SHA-1 Steam lists for it
    dir_size: int = 0
    missing: bool = False         # gameinfo names it but the game doesn't ship it


@dataclass
class GamePlan:
    app: int
    name: str
    manifests: list               # (depot, manifest id, date)
    install_bytes: int            # a full install of every depot we'd get
    packs: list
    keep: list = field(default_factory=list)     # (path, pack, entry)
    dropped: dict = field(default_factory=lambda: defaultdict(int))   # reason -> bytes
    dropped_files: dict = field(default_factory=lambda: defaultdict(int))
    parts_needed: set = field(default_factory=set)   # (pack dir_path, part number)

    @property
    def pack_bytes(self):
        return sum(p.dir_size + sum(p.parts.values()) for p in self.packs)

    @property
    def keep_bytes(self):
        return sum(e.size for _, _, e in self.keep)

    @property
    def download_bytes(self):
        sizes = {p.dir_path: p for p in self.packs}
        return (sum(p.dir_size for p in self.packs if not p.missing)
                + sum(sizes[d].parts.get(n, 0) for d, n in self.parts_needed))

    def keep_by_top(self):
        out = defaultdict(int)
        for path, _, e in self.keep:
            out[path.split("/", 1)[0]] += e.size
        return out


def packs_for(mount, depot_files):
    """The packs one game's mount entry names, with their sizes from Steam's file list."""
    by_path = {f.path: f for f in depot_files}
    packs = []
    for folder in mount.folders:
        for name in folder.vpks:
            dir_path = momentum.vpk_dir_file(folder.name, name).lower()
            p = Pack(mount.app, dir_path)
            if dir_path in by_path:
                p.dir_size = by_path[dir_path].size
                stem = dir_path[:-len("_dir.vpk")]
                for f in depot_files:
                    if f.path.startswith(stem + "_") and f.path != dir_path:
                        tail = f.path[len(stem) + 1:-4]
                        if len(tail) == 3 and tail.isdigit() and f.path.endswith(".vpk") and f.size:
                            p.parts[int(tail)] = f.size
                            p.part_sha[int(tail)] = f.sha1
            else:
                p.missing = True
            packs.append(p)
    return packs


def decide(games, indexes, have):
    """Fill in each GamePlan's keep list. indexes: depot path of a _dir file -> vpk.Index.
    have: paths Momentum already has."""
    for g in games:
        taken = set()
        for p in g.packs:
            if p.missing:
                continue
            for e in indexes[p.dir_path].entries:
                path = e.path
                top = path.split("/", 1)[0]
                if top not in momentum.KEEP_TOP:
                    reason = "other folders (scripts, maps, resource ...)"
                elif is_voice(path):
                    reason = "voice lines"
                elif path in have:
                    reason = "Momentum already has it"
                elif path in taken:
                    reason = "an earlier pack already has it"
                else:
                    taken.add(path)
                    g.keep.append((path, p, e))
                    if e.archive != vpk.IN_DIR and e.length:
                        g.parts_needed.add((p.dir_path, e.archive))
                    continue
                g.dropped[reason] += e.size
                g.dropped_files[reason] += 1
    return games
