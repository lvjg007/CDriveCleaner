from __future__ import annotations

import sys
from pathlib import Path

# 保证以脚本方式运行时可找到 src
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from src.ui.app_window import run_app

    run_app()


if __name__ == "__main__":
    main()
