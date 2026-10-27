"""The password sign-in box: a console window of its own, in which DepotDownloader asks for the
Steam password and then the Steam Guard code (or for approval in the Steam app).

    python -m mas.signin_box ACCOUNT DEPOTDOWNLOADER.EXE ARGS...
    MomentumAssets.exe --signin-box ACCOUNT DEPOTDOWNLOADER.EXE ARGS...

DepotDownloader reads the keyboard itself, straight from this window: nothing typed here
passes through Momentum Assets, which only waits for the box to close.
"""

import subprocess
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    account, command = argv[0], argv[1:]
    if getattr(sys, "frozen", False):
        # MomentumAssets.exe has no console of its own: make one, for this box only
        import ctypes
        ctypes.windll.kernel32.AllocConsole()
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
        sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW("Steam sign-in")
    except (ImportError, AttributeError, OSError):
        pass
    print(f"Signing in to Steam as {account}.\n")
    print("1. Type your Steam password below and press Enter.")
    print("2. Then approve the sign-in in the Steam app on your phone, or type the Steam Guard")
    print("   code Steam sends you (from the app, or by email), and press Enter.\n")
    print("This box is DepotDownloader, the program that talks to Steam. Momentum Assets never")
    print("sees your password; this box closes by itself once you're signed in.\n")
    code = subprocess.call(command)
    if code != 0:
        print("\nThat didn't sign you in. Close this box and try again from Momentum Assets.")
        input("Press Enter to close this box.")
    return code


if __name__ == "__main__":
    sys.exit(main())
