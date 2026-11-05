"""Start MINTRO: python -m mintro"""
from __future__ import annotations

import argparse
import logging

from . import server, store


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="mintro", description="What would crypto mining really earn on this computer?")
    p.add_argument("--port", type=int, default=8777)
    p.add_argument("--no-browser", action="store_true", help="don't open a browser and don't auto-quit")
    p.add_argument("--page", default="", choices=["", "card"], help="page to open: profit report (default) or card")
    args = p.parse_args(argv)

    store.DATA.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=store.DATA / "mintro.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    server.run(args.port, open_browser=not args.no_browser, page=args.page)


if __name__ == "__main__":
    main()
