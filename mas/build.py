"""Builds our packs for momentum/custom from a game's pack parts, a batch at a time.

The layout (which file goes where in which of our packs) is fixed before anything downloads,
so each pack's index is written first and each batch of parts is copied straight into place,
then deleted. Disk use stays at the finished packs plus one batch. A stopped build picks up
where it left off.
"""

import hashlib
import shutil
import subprocess
import time
import zlib
from collections import defaultdict
from dataclasses import dataclass

from . import depot, games, momentum, report, settings, vpk

MAX_PACK = 1_900_000_000      # each of our packs stays under 2 GB
BATCH_BYTES = 2_500_000_000   # parts downloaded per batch
GAME_CHECK_EVERY = 30         # seconds between looks, while waiting for Momentum to close


class BuildError(RuntimeError):
    pass


@dataclass
class OutPack:
    name: str
    files: list      # vpk.OutFile
    sources: list    # (plan.Pack, vpk.Entry), same order as files


def layout(game, order):
    """Split a game's kept files into packs of at most MAX_PACK bytes, in path order."""
    prefix = f"{momentum.OUR_PREFIX}{order}_{games.short(game.app)}_"
    packs, cur, off = [], None, 0
    for path, src, e in sorted(game.keep, key=lambda k: k[0]):
        if cur is None or (off + e.size > MAX_PACK and cur.files):
            cur = OutPack(f"{prefix}{len(packs) + 1:02d}.vpk", [], [])
            packs.append(cur)
            off = 0
        cur.files.append(vpk.OutFile(path, e.crc, e.size, off))
        cur.sources.append((src, e))
        off += e.size
    return packs


def ours_for(custom, app):
    """Our packs for one game in momentum/custom, whatever mount order they were built for."""
    return sorted(custom.glob(f"{momentum.OUR_PREFIX}*_{games.short(app)}_*.vpk"))


def installed_matches(packs, custom, app):
    """The packs in momentum/custom are exactly these: the same names, and in each the same
    files, at the same places, with the same checksums. Then there's nothing to do, whatever
    else has changed on Steam."""
    if [p.name for p in ours_for(custom, app)] != sorted(p.name for p in packs):
        return False
    for p in packs:
        path = custom / p.name
        try:
            ix = vpk.read(path)
            size = path.stat().st_size
        except Exception:               # damaged or unreadable: build it again
            return False
        got = sorted((e.path, e.crc, e.size, e.offset) for e in ix.entries)
        if got != sorted((f.path, f.crc, f.size, f.offset) for f in p.files):
            return False
        data_size = max((f.offset + f.size for f in p.files), default=0)
        if size != vpk.HEADER_V2.size + ix.tree_size + data_size + vpk.SUMS_SIZE:
            return False
    return True


def game_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq momentum.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, creationflags=0x08000000).stdout
    return "momentum.exe" in out.lower()


def _fingerprint(game, packs):
    return {
        "manifests": [list(m) for m in game.manifests],
        "packs": [[p.name, len(p.files), sum(f.size for f in p.files)] for p in packs],
    }


def _copy(src_file, start, e, dst, dst_start, of):
    """Copy one file's bytes from a game pack into ours, checking its CRC on the way."""
    if e.length:
        src_file.seek(start + e.offset)
        body = src_file.read(e.length)
    else:
        body = b""
    data = e.preload + body
    if len(data) != of.size or zlib.crc32(data) != of.crc:
        raise BuildError(f"{of.path}: the downloaded bytes don't match Steam's checksum.")
    dst.seek(dst_start + of.offset)
    dst.write(data)


def _part_path(dir_path, n):
    """('tf/tf2_textures_dir.vpk', 7) -> 'tf/tf2_textures_007.vpk'."""
    folder, name = dir_path.rsplit("/", 1)
    return f"{folder}/{vpk.chunk_name(name, n)}"


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _fetch(sess, app, depot_dir, batch, packs_by_dir, out, on_percent=None):
    """Download a batch of parts and check each against the SHA-1 Steam lists for it.
    A part that doesn't match is deleted and fetched once more."""
    filelist = depot_dir / "filelist.txt"
    want = list(batch)
    for attempt in (1, 2):
        filelist.write_text("\n".join(_part_path(d, n) for d, n in want) + "\n")
        sess.run(app, depot_dir, filelist=filelist, on_percent=on_percent)
        bad = []
        for d, n in want:
            part = depot_dir / _part_path(d, n)
            sha = packs_by_dir[d].part_sha.get(n)
            if not part.is_file() or (sha and _sha1(part) != sha):
                part.unlink(missing_ok=True)
                bad.append((d, n))
        if not bad:
            return
        out.say(f"{len(bad)} part(s) came down damaged; fetching them again.")
        want = bad
    raise BuildError("Steam kept sending damaged parts: " + ", ".join(_part_path(d, n) for d, n in bad))


def build_game(sess, game, order, indexes, data, game_dir, out=None):
    """Download, copy and install one game's packs. Returns the installed pack names.
    `out` is a report.Reporter."""
    out = out or report.Reporter()
    app = game.app
    work = data / "build" / games.short(app)
    depot_dir = data / "depots" / str(app)
    packs = layout(game, order)
    fp = _fingerprint(game, packs)

    custom = game_dir / "momentum" / "custom"
    if installed_matches(packs, custom, app):
        out.stage(app, report.UP_TO_DATE)
        out.progress(app, 1.0)
        return [p.name for p in packs]

    progress_file = work / "progress.json"
    progress = settings.load(progress_file)
    # Start again if anything changed, if the progress file doesn't read, or if a stop while
    # the packs were going in (a power cut, say) left some of them already moved into the game.
    if progress.get("fingerprint") != fp or not all((work / p.name).is_file() for p in packs):
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        for p in packs:
            vpk.create(work / p.name, p.files)
        progress = {"fingerprint": fp, "done": []}
        settings.save(progress, progress_file)
        out.say(f"Started {report.packs(len(packs))} for {game.name} ({sum(len(p.files) for p in packs):,} files).")
    done = {tuple(d) for d in progress["done"]}

    # Where each file's bytes come from: a numbered part, or the game's _dir file itself.
    by_part = defaultdict(list)
    from_dir = defaultdict(list)
    for p in packs:
        for of, (src, e) in zip(p.files, p.sources):
            if e.archive == vpk.IN_DIR or not e.length:
                from_dir[src.dir_path].append((p, of, e))
            else:
                by_part[(src.dir_path, e.archive)].append((p, of, e))

    # Parts left from a stopped run may be half written (and the right size, since the
    # downloader sets the size first), so they're never trusted: fetch them again.
    for dir_path in {src.dir_path for p in packs for src, _ in p.sources}:
        folder, name = (depot_dir / dir_path).parent, (depot_dir / dir_path).name
        for left in folder.glob(name[:-len("_dir.vpk")] + "_[0-9][0-9][0-9].vpk"):
            left.unlink()

    sizes = {src.dir_path: src for p in packs for src, _ in p.sources}
    part_bytes = {k: sizes[k[0]].parts.get(k[1], 0) for k in by_part}
    total_bytes = sum(part_bytes.values()) or 1
    done_bytes = sum(n for k, n in part_bytes.items() if k in done)
    out.stage(app, report.DOWNLOADING)
    out.progress(app, done_bytes / total_bytes, total_bytes)

    handles = {p.name: open(work / p.name, "r+b") for p in packs}
    starts = {p.name: vpk.HEADER_V2.size + vpk.read(work / p.name).tree_size for p in packs}
    try:
        def save(key):
            for h in handles.values():
                h.flush()
            done.add(key)
            progress["done"] = sorted(done)
            settings.save(progress, progress_file)

        for dir_path, items in from_dir.items():
            key = (dir_path, -1)
            if key in done:
                continue
            ix = indexes[dir_path]
            with open(depot_dir / dir_path, "rb") as src:
                for p, of, e in items:
                    _copy(src, ix.data_start, e, handles[p.name], starts[p.name], of)
            save(key)

        todo = sorted(k for k in by_part if k not in done)
        batches, cur, cur_bytes = [], [], 0
        for k in todo:
            n = part_bytes[k]
            if cur and cur_bytes + n > BATCH_BYTES:
                batches.append(cur)
                cur, cur_bytes = [], 0
            cur.append(k)
            cur_bytes += n
        if cur:
            batches.append(cur)

        total = len(todo)
        got = 0
        t0 = time.time()
        for b, batch in enumerate(batches, 1):
            names = [_part_path(d, n) for d, n in batch]
            batch_bytes = sum(part_bytes[k] for k in batch)
            out.say(f"\n=== {game.name}: batch {b} of {len(batches)} ({len(batch)} parts) ===")

            def on_percent(pct, base=done_bytes, size=batch_bytes):
                out.progress(app, min(1.0, (base + size * pct / 100) / total_bytes), total_bytes)

            _fetch(sess, app, depot_dir, batch, sizes, out, on_percent)
            for (dir_path, n), rel in zip(batch, names):
                part = depot_dir / rel
                with open(part, "rb") as src:
                    for p, of, e in sorted(by_part[(dir_path, n)], key=lambda t: t[2].offset):
                        _copy(src, 0, e, handles[p.name], starts[p.name], of)
                part.unlink()
                save((dir_path, n))
                got += 1
            done_bytes += batch_bytes
            out.progress(app, done_bytes / total_bytes, total_bytes)
            mins = (time.time() - t0) / 60
            out.say(f"{got} of {total} parts done ({mins:.0f} min so far)")
    finally:
        for h in handles.values():
            h.close()

    out.stage(app, report.PACKING)
    for p in packs:
        vpk.finish(work / p.name)
        if len(vpk.read(work / p.name).entries) != len(p.files):
            raise BuildError(f"{p.name} didn't read back correctly.")
    return install(packs, work, game_dir, game, data, out)


def install(packs, work, game_dir, game, data, out=None):
    """Swap the finished packs into momentum/custom (the game must be closed)."""
    out = out or report.Reporter()
    custom = game_dir / "momentum" / "custom"
    if game_running():
        out.stage(game.app, report.CLOSE_GAME)
        out.say("Momentum is running. Close it and the packs go in by themselves.")
        while game_running():
            if depot.STOP.wait(GAME_CHECK_EVERY):
                raise depot.Stopped("Stopped.")
    out.stage(game.app, report.INSTALLING)
    for old in ours_for(custom, game.app):
        old.unlink()
    for p in packs:
        shutil.move(str(work / p.name), str(custom / p.name))
    record_file = data / "installed.json"
    record = settings.load(record_file)       # only a record: unreadable, it starts afresh
    record[str(game.app)] = {
        "game": game.name, "packs": [p.name for p in packs],
        "files": sum(len(p.files) for p in packs),
        "bytes": sum(f.size for p in packs for f in p.files),
        "manifests": [list(m) for m in game.manifests],
        "installed": time.strftime("%Y-%m-%d %H:%M"),
    }
    settings.save(record, record_file)
    shutil.rmtree(work, ignore_errors=True)
    out.stage(game.app, report.DONE, report.packs(len(packs)))
    out.progress(game.app, 1.0)
    out.say(f"Installed {report.packs(len(packs))} for {game.name} in {custom}.")
    return [p.name for p in packs]


def uninstall(game_dir, app=None):
    """Remove our packs (all, or one game's) from momentum/custom. Returns their names."""
    custom = game_dir / "momentum" / "custom"
    found = ours_for(custom, app) if app else sorted(custom.glob(f"{momentum.OUR_PREFIX}*.vpk"))
    for p in found:
        p.unlink()
    return [p.name for p in found]
