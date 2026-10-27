"""Momentum Assets: gives Momentum Mod the textures, models and sounds it borrows from TF2,
CS:S, CS:GO and Portal 2, without installing those games.

    py momentum_assets.py           the window (what "Momentum Assets.bat" opens)

For the command line:

    py momentum_assets.py build [tf2 css csgo portal2]
                                    download and build the packs (all games, or those named)
                                    and put them in momentum\\custom. Picks up where it left off.
    py momentum_assets.py sizes     sign in, then work out exactly what we'd download and keep,
                                    per game. Downloads only each game's small pack indexes.
    py momentum_assets.py scan      per installed map: what Momentum can't find today, and
                                    which game's pack has it (no Steam needed)
    py momentum_assets.py remove    take our packs out of momentum\\custom again

The first time, you sign in with the Steam app's QR code, or with --account NAME to type your
password and Steam Guard code into Steam's own sign-in box. The data folder (downloads, logs,
reports) is remembered from the last run; --data sets it.
"""

import argparse
import json
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

from mas import build, depot, engine, games, momentum, report, settings, vpk
from mas.engine import gb

KIND_NAMES = {"materials": "textures", "models": "models", "sound": "sounds", "particles": "particles"}


def render(plans, not_owned, game_dir, data):
    lines = [f"Momentum Assets: sizes ({time.strftime('%Y-%m-%d %H:%M')})", ""]
    head = f"{'':34}{'Full install':>14}{'Packs':>11}{'Download':>11}{'Keep':>11}"
    lines += [head, "-" * len(head)]
    tot = [0, 0, 0, 0]
    for g in plans:
        row = [g.install_bytes, g.pack_bytes, g.download_bytes, g.keep_bytes]
        tot = [a + b for a, b in zip(tot, row)]
        lines.append(f"{g.name:34}" + "".join(f"{gb(v):>{w}}" for v, w in zip(row, (14, 11, 11, 11))))
    lines.append("-" * len(head))
    lines.append(f"{'Total':34}" + "".join(f"{gb(v):>{w}}" for v, w in zip(tot, (14, 11, 11, 11))))
    lines += ["",
              "Full install = every file Steam would install for the game.",
              "Packs = the game's packs Momentum reads (gameinfo.txt).",
              "Download = the pack parts holding at least one file we keep (sizes on disk;",
              "           Steam compresses, so the transfer is usually a bit smaller).",
              "Keep = what ends up in momentum\\custom.", ""]

    for g in plans:
        parts_total = sum(len(p.parts) for p in g.packs)
        lines.append(f"{g.name}:")
        lines.append(f"  pack parts needed: {len(g.parts_needed)} of {parts_total}")
        kinds = g.keep_by_top()
        lines.append("  keep: " + ", ".join(f"{KIND_NAMES[k]} {gb(kinds.get(k, 0))}" for k in momentum.KEEP_TOP)
                     + f" ({len(g.keep):,} files)")
        for reason, n in sorted(g.dropped.items(), key=lambda kv: -kv[1]):
            lines.append(f"  left out, {reason}: {gb(n)} ({g.dropped_files[reason]:,} files)")
        for p in g.packs:
            if p.missing:
                lines.append(f"  NOTE: gameinfo names {p.dir_path}, but the game doesn't ship it")
        lines.append("  Steam versions: " + ", ".join(f"depot {d} manifest {m}" for d, m, _ in g.manifests))
        lines.append("")

    if not_owned:
        lines.append("Not in this Steam account's library: " + ", ".join(games.name(a) for a in not_owned))
        lines.append("")

    needs = engine.space_needed([g.keep_bytes for g in plans], data, game_dir)
    lines.append("Free space now: " + ", ".join(
        f"{d.rstrip(chr(92))} {gb(settings.free_bytes(d))} (needs {gb(n)})" for d, n in needs.items()))
    lines.append(f"Space the finished packs take in momentum\\custom: {gb(sum(g.keep_bytes for g in plans))}")
    return "\n".join(lines)


def cmd_sizes(args, data, game_dir):
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    log = engine.Log(data / "logs" / f"sizes_{stamp}.log")
    out = report.Logged(report.Console(), log)
    mounts = momentum.read_mounts(game_dir)
    sess = engine.open_session(data, out, args.account, mounts[0].app)
    plans, _, not_owned = engine.make_plan(sess, data, game_dir, mounts, args.picked, out)

    text = render(plans, not_owned, game_dir, data) + f"\nSteam account used: {sess.account}"
    path = data / "reports" / f"sizes_{stamp}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    (data / "reports" / f"sizes_{stamp}.json").write_text(json.dumps({
        "momentum": str(game_dir),
        "games": [{
            "app": g.app, "name": g.name, "manifests": g.manifests,
            "install_bytes": g.install_bytes, "pack_bytes": g.pack_bytes,
            "download_bytes": g.download_bytes, "keep_bytes": g.keep_bytes,
            "keep_files": len(g.keep), "keep_by_kind": g.keep_by_top(),
            "dropped": g.dropped, "parts_needed": sorted(g.parts_needed),
        } for g in plans],
        "not_owned": not_owned,
    }, indent=1), encoding="utf-8")
    print("\n" + text)
    print(f"\nSaved: {path}")
    return 0 if plans else 2


def cmd_scan(args, data, game_dir):
    """What each installed map uses that Momentum can't find today, and which game has it."""
    from mas import bsp
    plans = engine.offline_plan(data, game_dir)
    have = momentum.what_momentum_has(game_dir)
    ours = set()
    custom = game_dir / "momentum" / "custom"
    for p in custom.glob(f"{momentum.OUR_PREFIX}*.vpk"):
        ours.update(e.path for e in vpk.read(p).entries)
    stand_in = set()
    for p in (game_dir / "mount").glob("*_placeholder.vpk"):
        stand_in.update(e.path for e in vpk.read(p).entries)
    source = {}
    for g in plans:
        for path, _, _ in g.keep:
            source.setdefault(path, games.short(g.app))

    shorts = [games.short(g.app) for g in plans]
    rows, totals = [], defaultdict(int)
    for bsp_path in sorted((game_dir / "momentum" / "maps").glob("*.bsp")):
        try:
            used, packed = bsp.references(bsp_path)
        except Exception as e:
            rows.append(f"{bsp_path.stem:36} couldn't read it: {e}")
            continue
        missing = defaultdict(list)
        for path in sorted(used):
            if path in packed or path in have or path in ours or path in stand_in:
                continue
            missing[source.get(path, "nowhere")].append(path)
        count = sum(len(v) for v in missing.values())
        for k, v in missing.items():
            totals[k] += len(v)
        detail = ", ".join(f"{k} {len(missing[k])}" for k in shorts + ["nowhere"] if missing.get(k))
        rows.append(f"{bsp_path.stem:36} {count:4} missing" + (f"  ({detail})" if detail else ""))
        if args.verbose:
            for k in shorts + ["nowhere"]:
                for path in missing.get(k, []):
                    rows.append(f"{'':40}{k:8} {path}")

    lines = [f"Maps: what Momentum can't find today, and which game's pack has it "
             f"({time.strftime('%Y-%m-%d %H:%M')})", ""]
    lines += rows
    lines += ["", "Totals: " + ", ".join(f"{k} {totals[k]}" for k in shorts + ["nowhere"] if totals.get(k)),
              "Counts materials, models and sounds the map names itself (not textures inside models).",
              "'nowhere' = not in any of the four games either (often fine: e.g. a sound the map",
              "never plays, or a name the map doesn't really use).",
              "Needs the games' pack indexes in the data folder: run 'sizes' or 'build' once first."]
    text = "\n".join(lines)
    path = data / "reports" / f"scan_{time.strftime('%Y-%m-%d_%H%M%S')}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nSaved: {path}")
    return 0


def cmd_build(args, data, game_dir):
    result = engine.run(data, args.picked, report.Console(), args.account, game_dir)
    return result.code


def cmd_remove(args, data, game_dir):
    if build.game_running():
        print("Close Momentum first, then run this again.")
        return 2
    apps = [games.BY_SHORT[s].app for s in args.games] or [None]
    removed = [n for app in apps for n in build.uninstall(game_dir, app)]
    print(f"Removed {len(removed)} packs from {game_dir / 'momentum' / 'custom'}.")
    return 0


def data_folder(args, game_dir):
    """--data, else the folder used last time, else one on Momentum's drive."""
    if args.data:
        return Path(args.data)
    saved = settings.load().get("data")
    return Path(saved) if saved else settings.default_data(game_dir)


def main():
    if sys.argv[1:2] == ["--signin-box"]:          # MomentumAssets.exe, opening its sign-in box
        from mas import signin_box
        return signin_box.main(sys.argv[2:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["build", "sizes", "scan", "remove"],
                    help="leave out for the window")
    ap.add_argument("games", nargs="*", metavar="game",
                    help="only these: " + ", ".join(games.BY_SHORT))
    ap.add_argument("--data", help="the data folder (remembered for next time)")
    ap.add_argument("--account", help="sign in with this account's password, in Steam's own "
                                      "sign-in box, rather than the QR code")
    ap.add_argument("--pause", action="store_true", help="wait for Enter before closing")
    ap.add_argument("-v", "--verbose", action="store_true", help="scan: list every missing file")
    ap.add_argument("--demo", action="store_true", help="the window with a pretend Steam")
    args = ap.parse_args()
    if args.command is None:
        from mas import window
        window.main(demo=args.demo)
        return 0
    unknown = set(args.games) - set(games.BY_SHORT)
    if unknown:
        ap.error(f"unknown game {', '.join(sorted(unknown))}; use {', '.join(games.BY_SHORT)}")
    args.picked = set(args.games or games.BY_SHORT)

    code = 1
    restore_console = depot.no_quick_edit()
    depot.console_utf8()
    data = None
    try:
        game_dir = momentum.find_game()
        data = data_folder(args, game_dir)
        problem = settings.folder_problem(data, game_dir)
        if problem:
            raise engine.Problem(problem)
        data.mkdir(parents=True, exist_ok=True)
        if args.command in ("build", "sizes"):
            settings.save({**settings.load(), "data": str(data)})
        code = {"sizes": cmd_sizes, "build": cmd_build, "scan": cmd_scan,
                "remove": cmd_remove}[args.command](args, data, game_dir)
    except (engine.Problem, depot.SteamError, RuntimeError) as e:
        print(f"\nStopped: {e}")
    except Exception:
        traceback.print_exc()
    finally:
        restore_console()
        if data and data.is_dir():
            (data / "logs").mkdir(exist_ok=True)
            (data / "logs" / "last_exit.txt").write_text(str(code))
        if args.pause:
            input("\nPress Enter to close this window.")
    return code


if __name__ == "__main__":
    sys.exit(main())
