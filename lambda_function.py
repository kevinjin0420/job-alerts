from __future__ import annotations

from typing import Any

from watch import main


def handler(event: dict[str, Any], context: Any) -> None:
    exit_code = main()
    if exit_code != 0:
        raise RuntimeError(f"watch.main() exited with code {exit_code}")
