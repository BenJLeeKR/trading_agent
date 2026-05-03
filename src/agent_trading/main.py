from __future__ import annotations

from pprint import pprint

from agent_trading.runtime.bootstrap import build_default_runtime


def main() -> None:
    runtime = build_default_runtime()
    pprint(runtime)


if __name__ == "__main__":
    main()
