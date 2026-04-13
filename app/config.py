from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schema.sql"
RUNTIME_DIR = REPO_ROOT / "runtime"
TASKS_DIR = RUNTIME_DIR / "tasks"
LOGS_DIR = RUNTIME_DIR / "logs"
ARTIFACTS_DIR = RUNTIME_DIR / "artifacts"
SESSIONS_DIR = RUNTIME_DIR / "sessions"
DB_PATH = RUNTIME_DIR / "operator.db"
OPERATOR_LOG_PATH = LOGS_DIR / "operator.log"
REGISTRY_DIR = REPO_ROOT / "registry"
POLICIES_PATH = REGISTRY_DIR / "policies.yaml"


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    schema_path: Path
    runtime_dir: Path
    tasks_dir: Path
    logs_dir: Path
    artifacts_dir: Path
    sessions_dir: Path
    db_path: Path
    operator_log_path: Path
    policies_path: Path


def get_settings() -> Settings:
    runtime_dir = Path(os.environ.get("OPERATOR_RUNTIME_DIR", str(RUNTIME_DIR)))
    db_path = Path(os.environ.get("OPERATOR_DB_PATH", str(runtime_dir / "operator.db")))
    return Settings(
        repo_root=REPO_ROOT,
        schema_path=SCHEMA_PATH,
        runtime_dir=runtime_dir,
        tasks_dir=runtime_dir / "tasks",
        logs_dir=runtime_dir / "logs",
        artifacts_dir=runtime_dir / "artifacts",
        sessions_dir=runtime_dir / "sessions",
        db_path=db_path,
        operator_log_path=runtime_dir / "logs" / "operator.log",
        policies_path=POLICIES_PATH,
    )


def ensure_runtime_dirs(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    for path in (
        settings.runtime_dir,
        settings.tasks_dir,
        settings.logs_dir,
        settings.artifacts_dir,
        settings.sessions_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
