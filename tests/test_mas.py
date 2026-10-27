import hashlib
import json
import os
import sys
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from mas import build, depot, kv, momentum, plan, vpk


def _vpk_exe():
    """Valve's vpk.exe, which ships with Momentum - if Momentum is installed here."""
    try:
        return momentum.find_game() / "bin" / "win64" / "vpk.exe"
    except Exception:
        return Path("no-vpk.exe")


VPK_EXE = _vpk_exe()

GAMEINFO = r'''
"GameInfo"
{
	game 		"Momentum Mod"
	mount
	{
		440
		{
			"fallback"	"mount/tf_placeholder.vpk"
			"tf"
			{
				"vpk"	"tf2_misc_dir"
				"vpk"	"tf2_textures_dir"   // a comment
				"dir"	"download"
			}
		}
		// *appid*
		// {
			// "vpk"	"vpk_name"
		// }
		620
		{
			"update" { "vpk" "pak01" }
			"portal2" { "vpk" "pak01" }
		}
	}
	FileSystem { SearchPaths { game+mod	momentum/custom/* } }
	"cond"	"1"	[$WIN32]
}
'''


class KeyValues(unittest.TestCase):
    def test_mount_block(self):
        gi = kv.get(kv.parse(GAMEINFO), "GameInfo")
        self.assertEqual(kv.get(gi, "game"), "Momentum Mod")
        self.assertEqual(kv.get(gi, "cond"), "1")
        mount = kv.get(gi, "mount")
        self.assertEqual([k for k, _ in mount], ["440", "620"])
        tf = kv.get(kv.get(mount, "440"), "tf")
        self.assertEqual([v for k, v in tf if k == "vpk"], ["tf2_misc_dir", "tf2_textures_dir"])
        self.assertEqual(kv.get(kv.get(kv.get(gi, "FileSystem"), "SearchPaths"), "game+mod"),
                         "momentum/custom/*")

    def test_read_mounts(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "momentum").mkdir()
            (Path(t) / "momentum" / "gameinfo.txt").write_text(GAMEINFO)
            mounts = momentum.read_mounts(Path(t))
        self.assertEqual([m.app for m in mounts], [440, 620])
        self.assertEqual(mounts[0].fallback, "mount/tf_placeholder.vpk")
        self.assertEqual(mounts[0].folders[0].dirs, ["download"])
        self.assertEqual([f.name for f in mounts[1].folders], ["update", "portal2"])

    def test_vpk_names(self):
        self.assertEqual(momentum.vpk_dir_file("tf", "tf2_misc_dir"), "tf/tf2_misc_dir.vpk")
        self.assertEqual(momentum.vpk_dir_file("csgo", "pak01"), "csgo/pak01_dir.vpk")
        self.assertEqual(vpk.chunk_name("pak01_dir.vpk", 7), "pak01_007.vpk")
        self.assertTrue(momentum._is_part("pak01_000.vpk"))
        self.assertFalse(momentum._is_part("pak01_dir.vpk"))
        self.assertFalse(momentum._is_part("pocmanvpk.vpk"))


@unittest.skipUnless(VPK_EXE.is_file(), "needs Momentum's vpk.exe")
class VpkAgainstValvesTool(unittest.TestCase):
    """Packs made by Valve's own vpk.exe must read back exactly."""

    FILES = {
        "materials/brick/wall01.vmt": b'"LightmappedGeneric" { "$basetexture" "brick/wall01" }\n',
        "materials/brick/wall01.vtf": os.urandom(700_000),
        "models/props/crate.mdl": os.urandom(900_000),
        "sound/ambient/hum.wav": os.urandom(5000),
        "readme.txt": b"a file at the top level",
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        src = self.root / "pak01"
        for rel, data in self.FILES.items():
            p = src / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def tearDown(self):
        self.tmp.cleanup()

    def _vpk(self, *options):
        # Folder mode ("vpk <folder>"): its "a" command can't write under %TEMP% here.
        subprocess.run([str(VPK_EXE), *options, str(self.root / "pak01")], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _check(self, index, read_bytes):
        got = {e.path: e for e in index.entries}
        self.assertEqual(set(got), set(self.FILES))
        for rel, data in self.FILES.items():
            self.assertEqual(got[rel].size, len(data), rel)
            self.assertEqual(read_bytes(got[rel]), data, rel)

    def test_single_file(self):
        self._vpk()
        path = self.root / "pak01.vpk"
        ix = vpk.read(path)
        raw = path.read_bytes()

        def read_bytes(e):
            self.assertEqual(e.archive, vpk.IN_DIR)
            start = ix.data_start + e.offset
            return e.preload + raw[start:start + e.length]
        self._check(ix, read_bytes)

    def test_multi_part(self):
        self._vpk("-M", "-c", "1")
        ix = vpk.read(self.root / "pak01_dir.vpk")
        self.assertGreaterEqual(len({e.archive for e in ix.entries}), 2)

        def read_bytes(e):
            if e.archive == vpk.IN_DIR:
                raw = (self.root / "pak01_dir.vpk").read_bytes()
                start = ix.data_start + e.offset
            else:
                raw = (self.root / vpk.chunk_name("pak01_dir.vpk", e.archive)).read_bytes()
                start = e.offset
            return e.preload + raw[start:start + e.length]
        self._check(ix, read_bytes)


    def test_valve_tool_reads_our_packs(self):
        files, offset = [], 0
        for rel in sorted(self.FILES):
            data = self.FILES[rel]
            files.append(vpk.OutFile(rel, zlib.crc32(data), len(data), offset))
            offset += len(data)
        path = self.root / "ours.vpk"
        start = vpk.create(path, files)
        with open(path, "r+b") as f:
            for of in files:
                f.seek(start + of.offset)
                f.write(self.FILES[of.path])
        vpk.finish(path)

        # Our own reader, byte for byte.
        ix = vpk.read(path)
        raw = path.read_bytes()
        self._check(ix, lambda e: raw[ix.data_start + e.offset:ix.data_start + e.offset + e.length])

        # The three sums, worked out the way Valve's packs have them.
        tree = raw[28:28 + ix.tree_size]
        sums = raw[-48:]
        self.assertEqual(sums[:16], hashlib.md5(tree).digest())
        self.assertEqual(sums[32:], hashlib.md5(raw[:-16]).digest())

        # Valve's vpk.exe reads the same names, sizes and checksums. (It can't unpack anything
        # on this PC, even packs it made itself, so its detailed listing is the check.)
        listing = subprocess.run([str(VPK_EXE), "L", str(path)], capture_output=True, text=True).stdout
        seen = {}
        for line in listing.splitlines():
            name, *fields = line.split()
            kv_ = dict(f.split("=", 1) for f in fields)
            seen[name.replace("\\", "/").lower()] = (int(kv_["crc"], 16), int(kv_["sz"]))
        self.assertEqual(seen, {rel: (zlib.crc32(d), len(d)) for rel, d in self.FILES.items()})


    def test_build_from_game_parts(self):
        """A game's multi-part pack in, our packs out in custom/, every byte checked."""
        import shutil

        # The "Steam" side: Valve's tool makes the game's pack in parts of 1 MB.
        self._vpk("-M", "-c", "1")
        steam = self.root / "steam" / "tf"
        steam.mkdir(parents=True)
        for f in self.root.glob("pak01_*.vpk"):
            shutil.move(str(f), str(steam / f.name))
        depot_files = [depot.DepotFile(f"tf/{f.name}", f.stat().st_size,
                                       hashlib.sha1(f.read_bytes()).hexdigest(), 1) for f in steam.iterdir()]

        class FakeSteam:
            """Like DepotDownloader after a stopped run: a file already there at the right
            size is taken as done, even if it's only half written."""

            def run(self, app, out_dir, *, manifest_only=False, filelist=None, on_percent=None):
                for rel in filelist.read_text().split():
                    src, dst = self_root / "steam" / rel, out_dir / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not (dst.is_file() and dst.stat().st_size == src.stat().st_size):
                        shutil.copy(src, dst)

        self_root = self.root
        data = self.root / "data"
        game_dir = self.root / "game"
        (game_dir / "momentum" / "custom").mkdir(parents=True)
        (data / "depots" / "440" / "tf").mkdir(parents=True)
        shutil.copy(steam / "pak01_dir.vpk", data / "depots" / "440" / "tf" / "pak01_dir.vpk")
        # A half-written part left by a stopped run: right size, zeros where data should be.
        size = (steam / "pak01_000.vpk").stat().st_size
        (data / "depots" / "440" / "tf" / "pak01_000.vpk").write_bytes(b"\0" * size)

        mount = momentum.Mount(440, [momentum.ModFolder("tf", ["pak01"])])
        g = plan.GamePlan(440, "Team Fortress 2", [(441, "1", "")], 0, plan.packs_for(mount, depot_files))
        indexes = {"tf/pak01_dir.vpk": vpk.read(data / "depots" / "440" / "tf" / "pak01_dir.vpk")}
        plan.decide([g], indexes, {"sound/ambient/hum.wav"})

        old_max = build.MAX_PACK
        build.MAX_PACK = 1_000_000      # forces two packs of ours
        try:
            names = build.build_game(FakeSteam(), g, 1, indexes, data, game_dir)
        finally:
            build.MAX_PACK = old_max

        self.assertEqual(names, ["mounted_1_tf2_01.vpk", "mounted_1_tf2_02.vpk"])
        got = {}
        for n in names:
            p = game_dir / "momentum" / "custom" / n
            ix = vpk.read(p)
            raw = p.read_bytes()
            for e in ix.entries:
                got[e.path] = raw[ix.data_start + e.offset:ix.data_start + e.offset + e.length]
        want = {k: v for k, v in self.FILES.items() if k != "sound/ambient/hum.wav" and k != "readme.txt"}
        self.assertEqual(got, want)
        self.assertFalse(list((data / "depots" / "440" / "tf").glob("pak01_0*.vpk")), "parts not cleaned up")
        self.assertFalse((data / "build" / "tf2").exists())
        self.assertIn("440", json.loads((data / "installed.json").read_text()))

        # Run again with nothing changed on Steam: nothing is downloaded or rebuilt.
        class NoSteam:
            def run(self, *a, **k):
                raise AssertionError("downloaded again")
        build.MAX_PACK = 1_000_000
        try:
            again = build.build_game(NoSteam(), g, 1, indexes, data, game_dir)
        finally:
            build.MAX_PACK = old_max
        self.assertEqual(again, names)


class Manifests(unittest.TestCase):
    def test_parse(self):
        text = """Content Manifest for Depot 441

Manifest ID / date     : 123456789 / 10/20/2026 1:02:03 AM
Total number of files  : 3
Total number of chunks : 9
Total bytes on disk    : 3000
Total bytes compressed : 2000


          Size Chunks File SHA                                 Flags Name
             0      0 0000000000000000000000000000000000000000    40 tf\\materials
          1000      1 1111111111111111111111111111111111111111     0 tf\\tf2_textures_dir.vpk
          2000      2 2222222222222222222222222222222222222222     0 tf\\TF2_Textures_000.vpk
"""
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "manifest_441_123456789.txt").write_text(text)
            [m] = depot.read_manifests(Path(t))
        self.assertEqual((m.depot, m.manifest, m.disk_bytes, m.download_bytes), (441, "123456789", 3000, 2000))
        self.assertEqual([f.path for f in m.files], ["tf/tf2_textures_dir.vpk", "tf/tf2_textures_000.vpk"])


class Starts(unittest.TestCase):
    def test_main_script_runs(self):
        root = Path(__file__).resolve().parent.parent
        r = subprocess.run([sys.executable, str(root / "momentum_assets.py"), "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class QrCode(unittest.TestCase):
    def test_relay_takes_exactly_the_code(self):
        size = 5
        grid = [[(x + y) % 2 == 0 for x in range(size)] for y in range(size)]
        drawn = []
        relay = depot._QrRelay(drawn.append)
        self.assertFalse(relay.feed("Logging in with QR code..."))
        self.assertTrue(relay.feed("Use the Steam Mobile App to sign in with this QR code:"))
        for row in grid:
            self.assertTrue(relay.feed("".join("██" if d else "  " for d in row)))
        self.assertFalse(relay.feed("Success! Next time you can login with -username x -remember-password instead of -qr."))
        self.assertEqual(drawn, [grid])


class Decide(unittest.TestCase):
    def _entry(self, path, size, archive=0):
        return vpk.Entry(path, 0, b"", archive, 0, size)

    def test_rules(self):
        mounts = [momentum.Mount(1, [momentum.ModFolder("a", ["pak01"])]),
                  momentum.Mount(2, [momentum.ModFolder("b", ["pak01"])])]
        files1 = [depot.DepotFile("a/pak01_dir.vpk", 10, "", 1), depot.DepotFile("a/pak01_000.vpk", 100, "", 1),
                  depot.DepotFile("a/pak01_001.vpk", 200, "", 1)]
        files2 = [depot.DepotFile("b/pak01_dir.vpk", 20, "", 2), depot.DepotFile("b/pak01_000.vpk", 300, "", 2)]
        g1 = plan.GamePlan(1, "one", [], 0, plan.packs_for(mounts[0], files1))
        g2 = plan.GamePlan(2, "two", [], 0, plan.packs_for(mounts[1], files2))
        self.assertEqual(g1.packs[0].parts, {0: 100, 1: 200})
        indexes = {
            "a/pak01_dir.vpk": vpk.Index(2, 0, 28, [
                self._entry("materials/x.vtf", 5, 0),
                self._entry("materials/hl2.vtf", 6, 1),        # Momentum has it
                self._entry("sound/vo/hello.wav", 7, 1),       # voice
                self._entry("scripts/x.txt", 8, 1),            # other folder
            ]),
            "b/pak01_dir.vpk": vpk.Index(2, 0, 28, [
                self._entry("materials/x.vtf", 9, 0),          # game one already has it
                self._entry("models/y.mdl", 4, 0),
            ]),
        }
        plan.decide([g1, g2], indexes, {"materials/hl2.vtf"})
        self.assertEqual([p for p, _, _ in g1.keep], ["materials/x.vtf"])
        self.assertEqual(g1.parts_needed, {("a/pak01_dir.vpk", 0)})
        self.assertEqual(g1.download_bytes, 10 + 100)   # the index, and part 0 only
        self.assertEqual(dict(g1.dropped), {"Momentum already has it": 6, "voice lines": 7,
                                            "other folders (scripts, maps, resource ...)": 8})
        # Each game's packs are complete on their own: game two keeps its own x.vtf.
        self.assertEqual([p for p, _, _ in g2.keep], ["materials/x.vtf", "models/y.mdl"])
        self.assertEqual(dict(g2.dropped), {})

    def test_earlier_pack_of_the_same_game_wins(self):
        mount = momentum.Mount(620, [momentum.ModFolder("update", ["pak01"]),
                                     momentum.ModFolder("portal2", ["pak01"])])
        files = [depot.DepotFile("update/pak01_dir.vpk", 10, "", 1),
                 depot.DepotFile("portal2/pak01_dir.vpk", 10, "", 1)]
        g = plan.GamePlan(620, "Portal 2", [], 0, plan.packs_for(mount, files))
        indexes = {"update/pak01_dir.vpk": vpk.Index(2, 0, 28, [self._entry("materials/a.vtf", 5, vpk.IN_DIR)]),
                   "portal2/pak01_dir.vpk": vpk.Index(2, 0, 28, [self._entry("materials/a.vtf", 7, vpk.IN_DIR)])}
        plan.decide([g], indexes, set())
        self.assertEqual([(path, src.dir_path) for path, src, _ in g.keep],
                         [("materials/a.vtf", "update/pak01_dir.vpk")])
        self.assertEqual(dict(g.dropped), {"an earlier pack already has it": 7})


if __name__ == "__main__":
    unittest.main()
