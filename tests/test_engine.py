"""The job as a whole, with a pretend Steam and a pretend Momentum; and the pieces around it:
finding Momentum, the data folder, the space check, what's reported."""

import json
import os
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from mas import build, depot, engine, momentum, report, settings, vpk

GAMEINFO = '''"GameInfo"
{
	mount
	{
		440 { "tf" { "vpk" "tf2_textures_dir" } }
		240 { "cstrike" { "vpk" "cstrike_pak_dir" } }
		620 { "portal2" { "vpk" "pak01" } }
	}
}
'''

# What each pretend game's pack holds. CS:S and Portal 2 share a file with TF2.
GAME_FILES = {
    440: ("tf/tf2_textures_dir.vpk", {"materials/tf/wall.vtf": b"tf wall" * 50,
                                      "materials/shared.vtf": b"from tf2" * 20,
                                      "scripts/tf.txt": b"left out"}),
    240: ("cstrike/cstrike_pak_dir.vpk", {"materials/shared.vtf": b"from css" * 20,
                                          "sound/vo/hello.wav": b"voice, left out",
                                          "models/css/crate.mdl": b"crate" * 30}),
    620: ("portal2/pak01_dir.vpk", {"materials/shared.vtf": b"from portal2" * 20,
                                    "materials/hl2.vtf": b"Momentum has this one"}),
}


def make_game_pack(path, files):
    """A game's _dir pack with every file's data inside it (no numbered parts)."""
    out, off = [], 0
    for rel in sorted(files):
        out.append(vpk.OutFile(rel, zlib.crc32(files[rel]), len(files[rel]), off))
        off += len(files[rel])
    path.parent.mkdir(parents=True, exist_ok=True)
    start = vpk.create(path, out)
    with open(path, "r+b") as f:
        for of in out:
            f.seek(start + of.offset)
            f.write(files[of.path])
    vpk.finish(path)


class FakeSteam:
    """Stands in for depot.Session: the 'Steam' folder holds each game's pack, CS:S isn't owned
    unless asked, and every run is counted."""

    def __init__(self, store, owned=(440, 620)):
        self.store, self.owned, self.runs, self.account = store, set(owned), [], "player"

    def run(self, app, out_dir, *, manifest_only=False, filelist=None, on_percent=None):
        self.runs.append((app, "manifest" if manifest_only else "files"))
        if app not in self.owned:
            raise depot.NotOwned(f"app {app} isn't in your Steam library yet.")
        rel = GAME_FILES[app][0]
        src = self.store / str(app) / rel
        if manifest_only:
            sha = "0" * 40
            (out_dir / f"manifest_{app + 1}_1.txt").write_text(
                "Manifest ID / date     : 1 / today\n"
                f"Total bytes on disk    : {src.stat().st_size}\n"
                "Total bytes compressed : 1\n\n"
                "          Size Chunks File SHA                                 Flags Name\n"
                f"{src.stat().st_size:>14} 1 {sha} 0 {rel.replace('/', chr(92))}\n")
            return
        for line in filelist.read_text().split():
            dst = out_dir / line
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes((self.store / str(app) / line).read_bytes())


class Recorder(report.Reporter):
    def __init__(self):
        self.stages, self.said = {}, []

    def stage(self, app, stage, detail=""):
        self.stages.setdefault(app, []).append(stage)

    def say(self, text):
        self.said.append(text)


class WholeJob(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.game = root / "Momentum Mod"
        (self.game / "momentum" / "custom").mkdir(parents=True)
        (self.game / "momentum" / "gameinfo.txt").write_text(GAMEINFO)
        (self.game / "momentum" / "materials").mkdir()
        (self.game / "momentum" / "materials" / "hl2.vtf").write_bytes(b"x")
        self.store = root / "steam"
        for app, (rel, files) in GAME_FILES.items():
            make_game_pack(self.store / str(app) / rel, files)
        self.data = root / "data"
        patches = [mock.patch.object(build, "game_running", lambda: False)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, steam, picked=("tf2", "css", "portal2")):
        out = Recorder()
        with mock.patch.object(engine, "open_session", lambda *a, **k: steam):
            result = engine.run(self.data, set(picked), out, game_dir=self.game)
        return result, out

    def _packs(self):
        got = {}
        for p in sorted((self.game / "momentum" / "custom").glob("mounted_*.vpk")):
            ix, raw = vpk.read(p), p.read_bytes()
            got[p.name] = {e.path: raw[ix.data_start + e.offset:ix.data_start + e.offset + e.length]
                           for e in ix.entries}
        return got

    def test_build_skip_unowned_then_nothing_to_do(self):
        steam = FakeSteam(self.store)
        result, out = self._run(steam)
        self.assertEqual(out.stages[240], [report.WAITING, report.READING, report.NOT_OWNED])
        # once its list is in, a game waits its turn rather than still "asking Steam"
        self.assertEqual(out.stages[620][:4], [report.WAITING, report.READING, report.WAITING,
                                               report.DOWNLOADING])
        self.assertEqual(out.stages[440][-1], report.DONE)
        self.assertEqual(result.not_owned, [240])
        self.assertEqual(result.packs_in_game, 2)
        self.assertEqual(result.code, 0)
        # Each game's pack is complete: Portal 2 keeps its own shared.vtf; voice, scripts and
        # what Momentum has stay out. TF2's pack sorts first, so its copy wins in the game.
        self.assertEqual(self._packs(), {
            "mounted_1_tf2_01.vpk": {"materials/shared.vtf": b"from tf2" * 20,
                                     "materials/tf/wall.vtf": b"tf wall" * 50},
            "mounted_3_portal2_01.vpk": {"materials/shared.vtf": b"from portal2" * 20},
        })
        self.assertIn("Done: 2 packs installed.", out.said[-1])
        self.assertTrue(engine.summary(engine.Outcome(not_owned=[240], packs_in_game=26))
                        .startswith("Nothing installed"))

        # Again, nothing changed: only the file lists are read; no pack is fetched or rebuilt.
        steam.runs.clear()
        result, out = self._run(steam, ("tf2", "portal2"))
        self.assertEqual([r for r in steam.runs if r[1] == "files"], [(440, "files"), (620, "files")])
        self.assertEqual(out.stages[440][-1], report.UP_TO_DATE)
        self.assertEqual([a for a, _ in result.up_to_date], [440, 620])
        self.assertEqual(out.stages[240], [report.NOT_PICKED])

    def test_adding_a_game_later_leaves_the_others_alone(self):
        self._run(FakeSteam(self.store), ("portal2",))
        before = (self.game / "momentum" / "custom" / "mounted_3_portal2_01.vpk").stat().st_mtime_ns
        result, out = self._run(FakeSteam(self.store, owned=(440, 240, 620)))
        after = (self.game / "momentum" / "custom" / "mounted_3_portal2_01.vpk").stat().st_mtime_ns
        self.assertEqual(before, after)
        self.assertEqual(out.stages[620][-1], report.UP_TO_DATE)
        self.assertEqual(sorted(self._packs()), ["mounted_1_tf2_01.vpk", "mounted_2_css_01.vpk",
                                                 "mounted_3_portal2_01.vpk"])
        self.assertIn("materials/shared.vtf", self._packs()["mounted_2_css_01.vpk"])

    def test_a_damaged_pack_is_built_again(self):
        self._run(FakeSteam(self.store), ("tf2",))
        pack = self.game / "momentum" / "custom" / "mounted_1_tf2_01.vpk"
        pack.write_bytes(pack.read_bytes()[:-10])
        result, out = self._run(FakeSteam(self.store), ("tf2",))
        self.assertEqual(out.stages[440][-1], report.DONE)
        self.assertEqual(len(result.built), 1)

    def test_old_packs_go_and_a_stop_mid_install_recovers(self):
        """A game's old packs never stay beside its new ones, whatever order number they had;
        and a stop while the packs were being moved in doesn't break the next run."""
        custom = self.game / "momentum" / "custom"
        (custom / "mounted_7_tf2_01.vpk").write_bytes(b"an old layout")
        (custom / "mounted_7_tf2_02.vpk").write_bytes(b"an old layout")
        make_game_pack(custom / "pocmanvpk.vpk", {"materials/pocman.vtf": b"Momentum's own"})
        real_move, moves = build.shutil.move, []

        def move_once(src, dst):
            if moves:
                raise OSError("the power went")
            moves.append(dst)
            return real_move(src, dst)
        old_max = build.MAX_PACK
        build.MAX_PACK = 300                       # two packs for TF2
        try:
            with mock.patch.object(build.shutil, "move", move_once), self.assertRaises(OSError):
                self._run(FakeSteam(self.store), ("tf2",))
            self.assertEqual(sorted(p.name for p in custom.iterdir()),
                             ["mounted_1_tf2_01.vpk", "pocmanvpk.vpk"])
            result, out = self._run(FakeSteam(self.store), ("tf2",))
        finally:
            build.MAX_PACK = old_max
        self.assertEqual(out.stages[440][-1], report.DONE)
        self.assertEqual(sorted(p.name for p in custom.iterdir()),
                         ["mounted_1_tf2_01.vpk", "mounted_1_tf2_02.vpk", "pocmanvpk.vpk"])
        self.assertFalse((self.data / "build" / "tf2").exists())       # no second copy kept
        self.assertFalse(list((self.data / "depots" / "440").rglob("*_0[0-9][0-9].vpk")))

    def test_not_enough_space_stops_before_downloading(self):
        steam = FakeSteam(self.store)
        with mock.patch.object(settings, "free_bytes", lambda _p: 1000):
            with self.assertRaises(engine.Problem) as caught:
                self._run(steam, ("tf2",))
        self.assertIn("Not enough space", str(caught.exception))
        self.assertEqual([r for r in steam.runs if r[1] == "files"], [(440, "files")])  # the index only
        self.assertEqual(self._packs(), {})

    def test_the_data_folder_is_checked_first(self):
        steam = FakeSteam(self.store)
        out = Recorder()
        with mock.patch.object(engine, "open_session", lambda *a, **k: steam):
            with self.assertRaises(engine.Problem):
                engine.run(self.game / "data", {"tf2"}, out, game_dir=self.game)
        self.assertEqual(steam.runs, [])



class Space(unittest.TestCase):
    GB = 1_000_000_000

    def test_one_drive(self):
        needs = engine.space_needed([18 * self.GB, 6 * self.GB], r"C:\MomentumAssets", r"c:\Steam\Momentum")
        self.assertEqual(needs, {"C:\\": 24 * self.GB + 2 * build.BATCH_BYTES})

    def test_two_drives(self):
        needs = engine.space_needed([18 * self.GB, 6 * self.GB], r"D:\MomentumAssets", r"C:\Steam\Momentum")
        self.assertEqual(needs, {"D:\\": 18 * self.GB + 2 * build.BATCH_BYTES, "C:\\": 24 * self.GB})

    def test_nothing_to_build(self):
        self.assertEqual(engine.space_needed([], r"C:\a", r"C:\b"), {})

    def test_problem_in_plain_words(self):
        text = engine.space_problem({"D:\\": 30 * self.GB}, free=lambda d: 10 * self.GB)
        self.assertEqual(text, "Not enough space on drive D. This needs 30.0 GB free and there's "
                               "10.0 GB: free up 20.0 GB, or untick a game.")
        self.assertIsNone(engine.space_problem({"D:\\": 1}, free=lambda d: 2))


class DataFolder(unittest.TestCase):
    def test_problems(self):
        game = Path(r"C:\Steam\steamapps\common\Momentum Mod")
        with mock.patch.dict(os.environ, {"OneDrive": r"C:\Users\p\OneDrive"}):
            self.assertIn("OneDrive", settings.folder_problem(Path(r"C:\Users\p\OneDrive\stuff"), game))
            self.assertIn("OneDrive", settings.folder_problem(Path(r"E:\OneDrive - Work\x"), game))
            self.assertIn("inside Momentum", settings.folder_problem(game / "assets", game))
            self.assertIn("drive letter", settings.folder_problem(Path("relative"), game))
            self.assertIsNone(settings.folder_problem(Path(r"C:\MomentumAssets"), game))

    def test_default_and_settle(self):
        self.assertEqual(settings.default_data(Path(r"D:\SteamLibrary\steamapps\common\Momentum Mod")),
                         Path(r"D:\MomentumAssets"))
        self.assertEqual(settings.settle(Path(r"E:\Games")), Path(r"E:\Games\MomentumAssets"))
        self.assertEqual(settings.settle(Path(r"E:\MomentumAssets")), Path(r"E:\MomentumAssets"))

    def test_remembered(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "s" / "settings.json"
            self.assertEqual(settings.load(f), {})
            settings.save({"data": r"D:\MomentumAssets"}, f)
            self.assertEqual(settings.load(f), {"data": r"D:\MomentumAssets"})


class FindMomentum(unittest.TestCase):
    def _install(self, root, app, folder):
        steamapps = root / "steamapps"
        (steamapps / "common" / folder / "momentum").mkdir(parents=True)
        (steamapps / "common" / folder / "momentum" / "gameinfo.txt").write_text(GAMEINFO)
        (steamapps / f"appmanifest_{app}.acf").write_text(f'"AppState" {{ "installdir" "{folder}" }}')

    def test_release_first_then_playtest(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            self._install(root, 1802710, "Momentum Mod Playtest")
            self.assertEqual(momentum.find_install(root), (1802710, root / "steamapps" / "common" / "Momentum Mod Playtest"))
            self._install(root, 669270, "Momentum Mod")
            self.assertEqual(momentum.find_install(root), (669270, root / "steamapps" / "common" / "Momentum Mod"))

    def test_not_installed(self):
        with tempfile.TemporaryDirectory() as t, self.assertRaises(RuntimeError):
            momentum.find_install(Path(t))


class Reporting(unittest.TestCase):
    def test_log_leaves_out_percent_lines(self):
        class Buf:
            text = ""

            def write(self, s):
                Buf.text += s

            def flush(self):
                pass
        inner = Recorder()
        out = report.Logged(inner, Buf())
        out.steam(" 12.50% tf/tf2_textures_001.vpk")
        out.steam("Got depot key for 441")
        out.stage(440, report.DOWNLOADING)
        self.assertEqual(Buf.text, "Got depot key for 441\n[440] DOWNLOADING\n")
        self.assertEqual(inner.stages, {440: [report.DOWNLOADING]})

    def test_qr_text_is_black_on_white(self):
        text = report.qr_text([[True, False], [False, True]])
        self.assertIn("\x1b[30;107m", text)     # top dark, bottom light
        self.assertIn("\x1b[97;40m", text)      # top light, bottom dark


class LapsedCode(unittest.TestCase):
    def test_a_qr_run_that_ends_without_signing_in_takes_its_code_back(self):
        shown = []

        class Out(report.Reporter):
            def qr(self, rows):
                shown.append(rows)
        sess = depot.Session.__new__(depot.Session)
        sess.report, sess.state, sess.data, sess.exe = Out(), {}, Path("."), Path("x")
        lines = [b"Use the Steam Mobile App to sign in with this QR code:\r\n",
                 "\u2588\u2588  \r\n".encode("utf-8"), "  \u2588\u2588\r\n".encode("utf-8"),
                 b"Unable to get steam3 credentials.\r\n"]

        class Proc:
            stdout = lines

            def wait(self):
                return 1
        with mock.patch.object(depot.subprocess, "Popen", lambda *a, **k: Proc()), \
                self.assertRaises(depot.SteamError):
            sess._run(240, Path(tempfile.gettempdir()), True, None, None)
        self.assertEqual(shown, [[[True, False], [False, True]], None])


class Progress(unittest.TestCase):
    def test_percent_lines_reach_the_bar(self):
        """DepotDownloader's percent lines move the game's bar, by bytes across the batch."""
        seen = []

        class Out(report.Reporter):
            def progress(self, app, fraction):
                seen.append(round(fraction, 3))
        sess = depot.Session.__new__(depot.Session)
        sess.report, sess.state, sess.data, sess.exe = Out(), {"account": "p"}, Path("."), Path("x")
        lines = [b" 50.00% a\r\n", b"100.00% b\r\n"]

        class Proc:
            stdout = lines

            def wait(self):
                return 0
        with mock.patch.object(depot.subprocess, "Popen", lambda *a, **k: Proc()):
            got = []
            sess._run(440, Path(tempfile.gettempdir()), True, None, got.append)
        self.assertEqual(got, [50.0, 100.0])


if __name__ == "__main__":
    unittest.main()
