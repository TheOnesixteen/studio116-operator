PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  project TEXT NOT NULL,
  title TEXT NOT NULL,
  goal TEXT NOT NULL,
  type TEXT,
  priority TEXT NOT NULL DEFAULT 'medium',
  status TEXT NOT NULL,
  requested_by TEXT,
  constraints_json TEXT NOT NULL DEFAULT '[]',
  acceptance_criteria_json TEXT NOT NULL DEFAULT '[]',
  routing_json TEXT NOT NULL DEFAULT '{}',
  dependencies_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS task_runs (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  worker_name TEXT NOT NULL,
  run_type TEXT NOT NULL,
  status TEXT NOT NULL,
  worktree_path TEXT,
  branch_name TEXT,
  started_at TEXT NOT NULL,
  heartbeat_at TEXT,
  completed_at TEXT,
  exit_code INTEGER,
  summary TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_artifacts (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  run_id TEXT,
  artifact_type TEXT NOT NULL,
  path TEXT NOT NULL,
  label TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
  FOREIGN KEY (run_id) REFERENCES task_runs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS locks (
  id TEXT PRIMARY KEY,
  lock_type TEXT NOT NULL,
  resource_key TEXT NOT NULL,
  task_id TEXT,
  run_id TEXT,
  worker_name TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  acquired_at TEXT NOT NULL,
  heartbeat_at TEXT,
  expires_at TEXT,
  released_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL,
  FOREIGN KEY (run_id) REFERENCES task_runs(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_lock
ON locks(lock_type, resource_key)
WHERE status = 'active';

CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  task_id TEXT,
  run_id TEXT,
  event_type TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT 'info',
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL,
  FOREIGN KEY (run_id) REFERENCES task_runs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS worker_executions (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  worker_name TEXT NOT NULL,
  command TEXT,
  stdin_summary TEXT,
  stdout TEXT,
  stderr TEXT,
  exit_code INTEGER,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (run_id) REFERENCES task_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS project_cache (
  project_key TEXT PRIMARY KEY,
  data_json TEXT NOT NULL,
  cached_at TEXT NOT NULL,
  expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project);
CREATE INDEX IF NOT EXISTS idx_task_runs_task_id ON task_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_status ON task_runs(status);
CREATE INDEX IF NOT EXISTS idx_task_artifacts_task_id ON task_artifacts(task_id);
CREATE INDEX IF NOT EXISTS idx_locks_status ON locks(status);
CREATE INDEX IF NOT EXISTS idx_locks_task_id ON locks(task_id);
CREATE INDEX IF NOT EXISTS idx_events_task_id ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_worker_executions_run_id ON worker_executions(run_id);
