"""The whole job, the same for the window and the command line: sign in, read each picked
game's file list from Steam, decide what to keep, check the space, then build and install.

Everything it has to say goes to a report.Reporter.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

from . import build, depot, games, momentum, plan, report, settings, vpk


class Problem(RuntimeError):
    """Something the player has to sort out, said in plain words."""


@dataclass
class Outcome:
    built: list = field(default_factory=list)        # (app, packs, bytes, minutes)
    up_to_date: list = field(default_factory=list)   # (app, packs)
    not_owned: list = field(default_factory=list)    # apps
    packs_in_game: int = 0                           # all our packs in momentum/custom now

    @property
    def code(self):
        return 0 if self.built or self.up_to_date else 2


class Log:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(path, "a", encoding="utf-8")
        self.path = path

    def write(self, s):
        self.f.write(s)

    def flush(self):
        self.f.flush()

    def close(self):
        self.f.close()


def gb(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e8 else f"{n / 1e6:.0f} MB"


def space_needed(sizes, data, game_dir):
    """{drive: bytes} the build needs free. `sizes`: what each game to build keeps.

    The packs are built in the data folder, one game at a time, with up to two batches of
    downloads beside them, and then moved into the game. On one drive that's a move, so the
    drive needs all the packs plus the batches; on two, the data drive needs the biggest
    game's packs plus the batches, and the game's drive all the packs."""
    sizes = list(sizes)
    if not sizes:
        return {}
    batches = 2 * build.BATCH_BYTES
    data_drive, game_drive = Path(data).anchor.upper(), Path(game_dir).anchor.upper()
    if data_drive == game_drive:
        return {data_drive: sum(sizes) + batches}
    return {data_drive: max(sizes) + batches, game_drive: sum(sizes)}


def space_problem(needs, free=None):
    """Plain words for the first drive without room enough, or None."""
    free = free or settings.free_bytes
    for drive, need in needs.items():
        have = free(drive)
        if have < need:
            return (f"Not enough space on drive {drive.rstrip(':' + chr(92))}. This needs {gb(need)} "
                    f"free and there's {gb(have)}: free up {gb(need - have)}, or untick a game.")
    return None


def fetch_game(sess, mount, data, out):
    """Steam's file list for one game, then its pack indexes. Returns a GamePlan and indexes."""
    folder = data / "depots" / str(mount.app)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("manifest_*_*.txt"):
        old.unlink()

    out.stage(mount.app, report.READING)
    sess.run(mount.app, folder, manifest_only=True)
    mans = depot.read_manifests(folder)
    files = [f for m in mans for f in m.files]
    packs = plan.packs_for(mount, files)

    wanted = [p.dir_path for p in packs if not p.missing]
    indexes = {}
    if wanted:
        filelist = folder / "filelist.txt"
        filelist.write_text("\n".join(wanted) + "\n")
        sess.run(mount.app, folder, filelist=filelist)
        for d in wanted:
            indexes[d] = vpk.read(folder / d)

    g = plan.GamePlan(mount.app, games.name(mount.app), [(m.depot, m.manifest, m.date) for m in mans],
                      sum(m.disk_bytes for m in mans), packs)
    return g, indexes


def make_plan(sess, data, game_dir, mounts, picked, out):
    """Each picked game's file list and pack indexes, and what to keep from them.
    Returns the GamePlans of the games this account owns, their indexes, and the apps it
    doesn't own."""
    plans, indexes, not_owned = [], {}, []
    for m in mounts:
        if games.short(m.app) not in picked:
            out.stage(m.app, report.NOT_PICKED)
            continue
        try:
            g, ix = fetch_game(sess, m, data, out)
        except depot.NotOwned:
            out.stage(m.app, report.NOT_OWNED)
            out.say(f"{games.name(m.app)} isn't in this Steam account's library, so it's skipped.")
            not_owned.append(m.app)
            continue
        plans.append(g)
        indexes.update(ix)
    plan.decide(plans, indexes, momentum.what_momentum_has(game_dir))
    return plans, indexes, not_owned


def offline_plan(data, game_dir):
    """The same plan as make_plan, from the file lists and indexes already on disk (no Steam),
    for every game they're there for."""
    plans, indexes = [], {}
    for m in momentum.read_mounts(game_dir):
        folder = data / "depots" / str(m.app)
        mans = depot.read_manifests(folder)
        if not mans:
            continue
        packs = plan.packs_for(m, [f for man in mans for f in man.files])
        if any(not (folder / p.dir_path).is_file() for p in packs if not p.missing):
            continue
        for p in packs:
            if not p.missing:
                indexes[p.dir_path] = vpk.read(folder / p.dir_path)
        plans.append(plan.GamePlan(m.app, games.name(m.app),
                                   [(x.depot, x.manifest, x.date) for x in mans],
                                   sum(x.disk_bytes for x in mans), packs))
    plan.decide(plans, indexes, momentum.what_momentum_has(game_dir))
    return plans


def open_session(data, out, password_account=None, first_app=440):
    """Signed in to Steam, or about to be: with a saved login, by password now if asked for
    (in DepotDownloader's own box), or else by the QR code at the first download."""
    sess = depot.Session(data, out)
    if password_account and sess.account != password_account:
        if not sess.sign_in_with_password(password_account, first_app):
            raise depot.LoginFailed("The Steam sign-in didn't finish. Try again.")
    elif sess.account:
        out.signed_in(sess.account)
    return sess


def run(data, picked, out, password_account=None, game_dir=None):
    """The whole job. `picked`: short names of the games wanted. Returns an Outcome; raises
    Problem, or depot.SteamError, if it has to stop."""
    data = Path(data)
    game_dir = game_dir or momentum.find_game()
    problem = settings.folder_problem(data, game_dir)
    if problem:
        raise Problem(problem)
    data.mkdir(parents=True, exist_ok=True)
    log = Log(data / "logs" / f"build_{time.strftime('%Y-%m-%d_%H%M%S')}.log")
    out = report.Logged(out, log)
    try:
        return _run(data, picked, out, password_account, game_dir)
    finally:
        log.close()


def _run(data, picked, out, password_account, game_dir):
    mounts = momentum.read_mounts(game_dir)
    out.say(f"Momentum: {game_dir}")
    for m in mounts:
        if games.short(m.app) in picked:
            out.stage(m.app, report.WAITING)
    first = next((m.app for m in mounts if games.short(m.app) in picked), 440)
    sess = open_session(data, out, password_account, first)
    plans, indexes, not_owned = make_plan(sess, data, game_dir, mounts, picked, out)
    for g in plans:
        out.stage(g.app, report.WAITING)       # Steam's list is in; its turn comes

    order = {m.app: i for i, m in enumerate(mounts, 1)}
    custom = game_dir / "momentum" / "custom"
    to_build = [g for g in plans
                if not build.installed_matches(build.layout(g, order[g.app]), custom, g.app)]
    problem = space_problem(space_needed([g.keep_bytes for g in to_build], data, game_dir))
    if problem:
        raise Problem(problem)

    result = Outcome(not_owned=not_owned)
    for g in plans:
        t0 = time.time()
        try:
            names = build.build_game(sess, g, order[g.app], indexes, data, game_dir, out)
        except Exception:
            out.stage(g.app, report.FAILED)
            raise
        if any(g is b for b in to_build):
            result.built.append((g.app, len(names), g.keep_bytes, (time.time() - t0) / 60))
        else:
            result.up_to_date.append((g.app, len(names)))
    result.packs_in_game = len(list(custom.glob(f"{momentum.OUR_PREFIX}*.vpk")))
    out.say(summary(result))
    return result


def summary(result):
    if result.built or result.up_to_date:
        lines = [f"Done: {report.packs(result.packs_in_game)} installed."]
    else:
        lines = ["Nothing installed: this Steam account doesn't own the games picked."]
    for app, n, size, mins in result.built:
        lines.append(f"  {games.name(app)}: {report.packs(n)}, {gb(size)}, {mins:.0f} min")
    for app, n in result.up_to_date:
        lines.append(f"  {games.name(app)}: already up to date ({report.packs(n)})")
    for app in result.not_owned:
        lines.append(f"  {games.name(app)}: not in this Steam account's library, skipped")
    return "\n".join(lines)
