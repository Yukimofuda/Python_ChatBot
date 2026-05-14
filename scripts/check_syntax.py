from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    paths = [ROOT / "bot.py", ROOT / "src", ROOT / "tests"]
    for path in paths:
        if not path.exists():
            continue
        files = [path] if path.is_file() else sorted(path.rglob("*.py"))
        for file_path in files:
            ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
