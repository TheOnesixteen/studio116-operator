from __future__ import annotations

from app.models import CommandResult
from tools.systemd_tools import inspect_service


def inspect_caddy() -> list[CommandResult]:
    return inspect_service("caddy")
