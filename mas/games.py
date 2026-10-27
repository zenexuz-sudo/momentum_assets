"""The four games Momentum borrows from, in the order its gameinfo.txt mounts them."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Game:
    app: int
    short: str            # in our packs' names and on the command line
    name: str
    free: bool            # free on Steam (DepotDownloader adds it to the library itself)
    about_download: int   # bytes, measured 2026-10; shown until Steam's own file lists are in
    about_keep: int


GAMES = (
    Game(440, "tf2", "Team Fortress 2", True, 18_087_216_157, 17_914_400_363),
    Game(240, "css", "Counter-Strike: Source", False, 1_395_524_718, 1_311_379_146),
    Game(4465480, "csgo", "Counter-Strike: Global Offensive", True, 21_537_246_668, 21_035_949_499),
    Game(620, "portal2", "Portal 2", False, 7_098_448_329, 6_527_074_203),
)

BY_APP = {g.app: g for g in GAMES}
BY_SHORT = {g.short: g for g in GAMES}


def name(app):
    g = BY_APP.get(app)
    return g.name if g else f"app {app}"


def short(app):
    g = BY_APP.get(app)
    return g.short if g else str(app)
