from __future__ import annotations

from app.models import CommandResult
from tools.log_tools import run_read_only_command


def inspect_service(service_name: str) -> list[CommandResult]:
    return [
        run_read_only_command(
            ["systemctl", "is-active", service_name],
            action="service_status_checks",
            timeout=5,
        ),
        run_read_only_command(
            ["systemctl", "status", service_name, "--no-pager"],
            action="service_status_checks",
            timeout=10,
        ),
    ]
