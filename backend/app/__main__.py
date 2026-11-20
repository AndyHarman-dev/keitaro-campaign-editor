"""`uv run python -m app [--stats-beta] [uvicorn options]`

Starts the app with uvicorn. `--stats-beta` turns on stats & trends by setting STATS_BETA=1
in the environment: `app.main` reads its settings at import, and `--reload` imports it again
in a child process, which inherits the environment. Every other argument goes to uvicorn.
"""

import argparse
import os

import uvicorn


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app", add_help=False, allow_abbrev=False)
    parser.add_argument("--stats-beta", action="store_true")
    ours, rest = parser.parse_known_args(argv)
    if ours.stats_beta:
        os.environ["STATS_BETA"] = "1"
    # uvicorn reads its APP argument from UVICORN_APP when none is given, so an explicit
    # target still wins and option values such as `--host ::1` are never mistaken for one.
    os.environ.setdefault("UVICORN_APP", "app.main:app")
    uvicorn.main.main(args=rest)


if __name__ == "__main__":
    main()
