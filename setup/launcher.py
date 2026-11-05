"""MINTRO.exe: the floating card, or `MINTRO.exe --uninstall [--quiet]` (what Settings > Apps runs)."""
import sys

if "--uninstall" in sys.argv:
    from mintro.installer import uninstall
    uninstall(quiet="--quiet" in sys.argv)
else:
    from mintro.app import run
    run()
