from __future__ import annotations

import logging
from typing import Any

from app.models import CommandResult

logger = logging.getLogger(__name__)

NOT_IMPLEMENTED_SUMMARY = (
    "shell_ops adapter is a stub. "
    "Live shell task execution is not yet implemented."
)


def run_task(task: dict[str, Any], *, run_id: str) -> CommandResult:
    logger.warning(
        "shell_ops adapter received task %s (run %s) but live execution is not implemented",
        task.get("id"),
        run_id,
    )
    return CommandResult(
        command="shell_ops (not implemented)",
        stdout="",
        stderr=NOT_IMPLEMENTED_SUMMARY,
        exit_code=1,
    )
