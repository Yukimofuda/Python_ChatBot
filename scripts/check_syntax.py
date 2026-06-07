from __future__ import annotations

import pathlib
import sys


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    checked = 0
    for path in sorted(root.joinpath("src").rglob("*.py")):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
        checked += 1
    print(f"syntax ok: {checked} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
