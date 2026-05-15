from __future__ import annotations

from pathlib import Path


def intended_review_command(*, packet_path: Path) -> list[str]:
    return [
        "gemini",
        "--prompt",
        f"Review this Operator worker packet for risks, gaps, ambiguity, and recommendations. "
        f"Do not modify files. Do not execute commands. Packet path: {packet_path}",
    ]
