from __future__ import annotations

from app.models import CommandResult
from tools.log_tools import run_read_only_command


def inspect_docker_health() -> list[CommandResult]:
    return [
        run_read_only_command(
            ["docker", "ps", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
            action="docker_ps",
            timeout=10,
        )
    ]
