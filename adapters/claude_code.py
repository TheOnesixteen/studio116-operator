from __future__ import annotations

from pathlib import Path


def intended_read_only_command(*, packet_path: Path) -> list[str]:
    return [
        "116studio-ai",
        "--read-only",
        "--packet",
        str(packet_path),
    ]
