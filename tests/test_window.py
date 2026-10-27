"""The window, driven by hand: what it shows for each piece of news, and when START may go.
Nothing is shown on screen (the window stays hidden) and nothing reaches Steam."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mas import depot, engine, games, report, settings, window


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.game = root / "Momentum Mod"
        (self.game / "momentum").mkdir(parents=True)
        patches = [mock.patch.object(window.momentum, "find_game", lambda: self.game),
                   mock.patch.object(settings, "free_bytes", lambda _p: 500 * 10 ** 9)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.settings = root / "settings.json"
        settings.save({"data": str(root / "MomentumAssets")}, self.settings)
        self.app = window.App(demo=True, settings_path=self.settings)
        self.addCleanup(self.app.root.destroy)

    def text(self, label):
        return label.cget("text")

    def test_start_is_ready_with_everything_ticked(self):
        self.assertEqual(self.text(self.app.status), "READY")
        self.assertTrue(self.app.main_action.enabled)
        self.assertEqual(self.text(self.app.total_label), "ABOUT 46.8 GB")
        self.assertIn("NEEDS ABOUT", self.text(self.app.space_note))
        self.assertIn("NOT MADE BY VALVE", self.text(self.app.message))

    def test_start_waits_for_a_game_and_an_account_name(self):
        for row in self.app.game_rows:
            row.box.set(False)
        self.app.refresh_setup()
        self.assertFalse(self.app.main_action.enabled)
        self.assertEqual(self.text(self.app.message), "TICK AT LEAST ONE GAME.")

        self.app.game_rows[0].box.set(True)
        self.app.method.set(depot.PASSWORD)
        self.app.refresh_setup()
        self.assertFalse(self.app.main_action.enabled)
        self.assertIn("ACCOUNT NAME", self.text(self.app.message))
        self.app.account.insert(0, "someone")
        self.app.refresh_setup()
        self.assertTrue(self.app.main_action.enabled)
        self.assertIn("NEVER SEES", self.text(self.app.method_note))

    def test_not_enough_space(self):
        with mock.patch.object(settings, "free_bytes", lambda _p: 10 * 10 ** 9):
            self.app.refresh_setup()
        self.assertFalse(self.app.main_action.enabled)
        self.assertEqual(self.app.space_note.cget("fg"), window.hs.BAD)
        self.assertIn("NOT ENOUGH SPACE", self.text(self.app.message))

    def test_space_leaves_out_games_already_in(self):
        """Partly installed and short of room for everything (as on a PC with 45.6 GB free and
        TF2's packs in): START must still go, counting TF2 as up to date until Steam says."""
        custom = self.game / "momentum" / "custom"
        custom.mkdir(parents=True)
        (custom / "mounted_1_tf2_01.vpk").write_bytes(b"x")
        with mock.patch.object(settings, "free_bytes", lambda _p: 45_600_000_000):
            self.app.refresh_setup()
        self.assertTrue(self.app.main_action.enabled)
        self.assertIn("NEEDS ABOUT 33.9 GB", self.text(self.app.space_note))
        self.assertIn("ALREADY IN", self.text(self.app.space_note))

        for short in ("css", "csgo", "portal2"):                    # all in: nothing needed
            (custom / f"mounted_9_{short}_01.vpk").write_bytes(b"x")
        with mock.patch.object(settings, "free_bytes", lambda _p: 45_600_000_000):
            self.app.refresh_setup()
        self.assertTrue(self.app.main_action.enabled)
        self.assertIn("45.6 GB FREE.", self.text(self.app.space_note))
        self.assertIn("ALL OF THESE ARE ALREADY IN", self.text(self.app.space_note))
        for p in custom.glob("mounted_9_*"):
            p.unlink()

        (custom / "mounted_1_tf2_01.vpk").unlink()                 # nothing in: 51.8 GB, short
        with mock.patch.object(settings, "free_bytes", lambda _p: 45_600_000_000):
            self.app.refresh_setup()
        self.assertFalse(self.app.main_action.enabled)
        self.assertIn("NEEDS ABOUT 51.8 GB", self.text(self.app.space_note))

    def test_a_folder_in_onedrive_is_refused(self):
        with mock.patch.dict(os.environ, {"OneDrive": str(Path(self.tmp.name) / "OneDrive")}):
            self.app.data = Path(self.tmp.name) / "OneDrive" / "MomentumAssets"
            self.app.refresh_setup()
        self.assertFalse(self.app.main_action.enabled)
        self.assertIn("ONEDRIVE", self.text(self.app.space_note))

    def test_a_whole_run(self):
        app = self.app
        app._show_page("working")
        app._handle(("qr", [[True, False], [False, True]]))
        self.assertEqual(self.text(app.status), "SIGN IN")
        self.assertTrue(app.signin_frame.winfo_manager())
        self.assertEqual(len(app.qr_canvas.find_withtag("module")), 2)

        app._handle(("signed_in", "player"))
        self.assertFalse(app.signin_frame.winfo_manager())
        self.assertEqual(self.text(app.status), "WORKING")
        self.assertEqual(self.text(app.where["STEAM ACCOUNT"]), "PLAYER")

        app._handle(("stage", 240, report.NOT_OWNED, ""))
        app._handle(("stage", 440, report.DOWNLOADING, ""))
        app._handle(("progress", 440, 0.5, 18 * 10 ** 9))
        bar = app.bars[440]
        self.assertEqual(self.text(bar.stage_label), "DOWNLOADING 50%")
        self.assertEqual(self.text(bar.detail), "9.0 GB OF 18.0 GB")
        self.assertTrue(self.text(app.status_side).startswith("9.0 GB OF"))
        self.assertIn("SKIPPED", self.text(app.bars[240].detail))

        app._handle(("stage", 440, report.CLOSE_GAME, ""))
        self.assertIn("CLOSE MOMENTUM", self.text(app.message))

        result = engine.Outcome(built=[(440, 10, 17_900_000_000, 9)], not_owned=[240], packs_in_game=10)
        app._handle(("finished", result))
        self.assertEqual(self.text(app.status), "DONE: 10 PACKS INSTALLED")
        self.assertEqual(self.text(app.done_rows[440][1]), "10 PACKS, 17.9 GB")
        self.assertEqual(self.text(app.done_rows[240][1]), "NOT IN YOUR LIBRARY")
        self.assertEqual(self.text(app.main_action), "CLOSE")

    def test_a_lapsed_code_comes_off_the_screen(self):
        app = self.app
        app._show_page("working")
        app._handle(("signing_in", depot.QR, None))
        self.assertTrue(app.qr_canvas.find_withtag("waiting"))         # not a blank box
        app._handle(("qr", [[True, False], [False, True]]))
        self.assertEqual(len(app.qr_canvas.find_withtag("module")), 2)
        app._handle(("qr", None))                                        # Steam let it lapse
        self.assertFalse(app.qr_canvas.find_withtag("module"))
        self.assertTrue(app.qr_canvas.find_withtag("waiting"))

    def test_the_total_leaves_out_skipped_and_up_to_date_games(self):
        app = self.app
        app._show_page("working")
        app._handle(("stage", 240, report.NOT_OWNED, ""))
        app._handle(("stage", 620, report.UP_TO_DATE, ""))
        app._handle(("stage", 440, report.DOWNLOADING, ""))
        app._handle(("progress", 440, 0.5, 18 * 10 ** 9))
        csgo = games.BY_SHORT["csgo"].about_download       # not started: its measured size
        self.assertEqual(self.text(app.status_side),
                         f"9.0 GB OF {window.gb(18 * 10 ** 9 + csgo)}")

    def test_nothing_owned_says_so(self):
        """Packs already in the game from before aren't counted as this run's."""
        app = self.app
        app._show_page("working")
        app._handle(("finished", engine.Outcome(not_owned=[240, 620], packs_in_game=26)))
        self.assertEqual(self.text(app.status), "NOTHING INSTALLED")
        self.assertEqual(self.text(app.done_note), "")              # no "start Momentum and play"
        self.assertIn("DOESN'T OWN", self.text(app.message))
        self.assertFalse(app.remove.label.winfo_manager())

    def test_a_problem_stops_it_and_back_returns(self):
        app = self.app
        app._show_page("working")
        app._handle(("stage", 440, report.DOWNLOADING, ""))
        app._handle(("failed", "Not enough space on drive C."))
        self.assertEqual(self.text(app.status), "STOPPED")
        self.assertEqual(self.text(app.bars[440].stage_label), report.FAILED)
        self.assertEqual(self.text(app.main_action), "BACK")
        app._main_action()
        self.assertEqual(app.state, "setup")
        self.assertEqual(self.text(app.status), "READY")

    def test_stopping_asks_once(self):
        app = self.app
        app._show_page("working")
        with mock.patch.object(depot, "stop_all") as stop:
            app._stop()
            stop.assert_not_called()
            self.assertIn("AGAIN", self.text(app.message))
            app._stop()
            stop.assert_called_once()

    def test_no_stopping_while_the_packs_go_in(self):
        app = self.app
        app._show_page("working")
        app._handle(("stage", 440, report.INSTALLING, ""))
        with mock.patch.object(depot, "stop_all") as stop:
            app._stop()
            app._stop()
            stop.assert_not_called()
        self.assertIn("ONE MOMENT", self.text(app.message))

    def test_start_remembers_the_choices(self):
        app = self.app
        app.game_rows[1].box.set(False)
        with mock.patch.object(window.threading, "Thread"):
            app.start()
        saved = settings.load(self.settings)
        self.assertEqual(saved["games"], ["tf2", "csgo", "portal2"])
        self.assertEqual(saved["method"], depot.QR)
        self.assertEqual(self.text(app.bars[240].stage_label), report.NOT_PICKED)

    def test_the_demo_runs_through_the_thread_to_done(self):
        """START, the work in its own thread, its news through the queue, DONE."""
        import time
        from mas import demo
        app = self.app
        app._demo_run = lambda picked, account: demo.run(app.events, picked, account, speed=200)
        app.start()
        deadline = time.monotonic() + 10
        while app.state != "done" and time.monotonic() < deadline:
            app.root.update()
            time.sleep(0.01)
        self.assertEqual(app.state, "done")
        self.assertEqual(self.text(app.status), "DONE: 26 PACKS INSTALLED")
        self.assertEqual(self.text(app.done_rows[240][1]), "NOT IN YOUR LIBRARY")


class DemoQr(unittest.TestCase):
    def test_looks_like_a_code(self):
        from mas import demo
        rows = demo.fake_qr()
        self.assertEqual(len(rows), 37)
        self.assertTrue(all(len(r) == 37 for r in rows))
        self.assertFalse(any(rows[0]))                  # the quiet zone
        self.assertTrue(all(rows[4][4:11]))             # a finder square's top edge


if __name__ == "__main__":
    unittest.main()
