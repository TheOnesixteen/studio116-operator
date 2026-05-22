import json
import os
import sqlite3 as _sqlite3
import subprocess
import tempfile
import uuid
from pathlib import Path

import yaml
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)
WEB_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(WEB_DIR)
RUNTIME_DIR = os.environ.get("OPERATOR_RUNTIME_DIR", os.path.join(PROJECT_ROOT, "runtime"))
DB_PATH = os.environ.get("OPERATOR_DB_PATH", os.path.join(RUNTIME_DIR, "operator.db"))
ARTIFACTS_DIR = os.path.join(RUNTIME_DIR, "artifacts")

OPERATOR = "./scripts/operator"
TIMEOUT = 60
LIVE_WRITABLE_MODES = {
    "live_codex_docs_only",
    "live_codex_tests_only",
    "live_codex_policy_file_only",
    "live_codex_model_file_only",
    "live_codex_scaffold_only",
    "sequential_pipeline",
}
PREVIEW_POLICY_FILE_TARGETS = {"app/policies.py"}


def _db():
    con = _sqlite3.connect(DB_PATH)
    con.row_factory = _sqlite3.Row
    return con


def _friction_level(routing):
    mode = routing.get("delegation_mode", "")
    if mode in ("live_codex_docs_only", "live_codex_scaffold_only"):
        return "low"
    if mode in ("live_codex_tests_only", "live_codex_model_file_only", "live_codex_policy_file_only"):
        return "medium"
    if mode == "sequential_pipeline":
        target_paths = routing.get("target_paths", [])
        doc_exts = {".md", ".txt", ".yaml", ".yml", ".rst"}
        if not target_paths or all(
            any(str(p).endswith(ext) for ext in doc_exts) for p in target_paths
        ):
            return "low"
        return "medium"
    return "high"


def run(cmd):
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd="/root/Projects/studio116-operator",
        )
        raw = result.stdout.strip() or result.stderr.strip()
        if result.returncode != 0:
            return jsonify({"ok": False, "error": raw}), 400
        try:
            return jsonify({"ok": True, "output": json.loads(raw)})
        except (json.JSONDecodeError, ValueError):
            return jsonify({"ok": True, "output": raw})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "command timed out"}), 504
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/htmx.min.js")
def htmx_js():
    return send_from_directory(WEB_DIR, "htmx.min.js")


@app.route("/api/inbox")
def inbox():
    try:
        con = _db()
        rows = con.execute(
            "SELECT id, project, title, status, routing_json, created_at, updated_at FROM tasks"
            " WHERE status = 'review' ORDER BY updated_at ASC"
        ).fetchall()

        result = []
        for row in rows:
            t = dict(row)
            routing = {}
            try:
                routing = json.loads(t.get("routing_json") or "{}")
            except (json.JSONDecodeError, ValueError):
                pass

            run_row = con.execute(
                "SELECT id FROM task_runs WHERE task_id = ? ORDER BY started_at DESC LIMIT 1",
                (t["id"],),
            ).fetchone()
            run_id = dict(run_row)["id"] if run_row else ""

            changed_files = []
            cf_path = Path(ARTIFACTS_DIR) / t["id"] / run_id / "changed_files.json"
            if cf_path.exists():
                try:
                    cf_raw = json.loads(cf_path.read_text(encoding="utf-8"))
                    raw = cf_raw.get("changed_files", cf_raw) if isinstance(cf_raw, dict) else cf_raw
                    if isinstance(raw, list):
                        changed_files = raw
                except (json.JSONDecodeError, OSError):
                    pass

            result.append({
                "id": t["id"],
                "project": t["project"],
                "title": t["title"],
                "status": t["status"],
                "pipeline": routing.get("delegation_mode", ""),
                "risk_level": _friction_level(routing),
                "changed_files": changed_files,
                "created_at": t["created_at"],
                "updated_at": t["updated_at"],
            })

        con.close()
        return jsonify({"ok": True, "review": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/tasks")
def tasks():
    result = subprocess.run(
        [OPERATOR, "tasks", "list"],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        cwd="/root/Projects/studio116-operator",
    )
    rows = []
    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            rows.append({"id": parts[0], "status": parts[1], "project": parts[2], "title": parts[3]})
        elif len(parts) == 3:
            rows.append({"id": parts[0], "status": parts[1], "project": parts[2], "title": ""})
    return jsonify({"ok": True, "output": rows})


@app.route("/api/health")
def health():
    try:
        import sqlite3 as _sqlite3
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runtime", "operator.db")
        con = _sqlite3.connect(db_path)
        con.execute("SELECT 1")
        con.close()
        return jsonify({"ok": True, "status": "ok"})
    except Exception as e:
        return jsonify({"ok": False, "status": "degraded", "error": str(e)}), 500


@app.route("/api/status")
def status():
    return run([OPERATOR, "status"])


@app.route("/api/run", methods=["POST"])
def run_next():
    return run([OPERATOR, "run", "next"])


@app.route("/api/tasks/<task_id>/review-packet")
def review_packet(task_id):
    try:
        con = _db()
        task = con.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            con.close()
            return jsonify({"ok": False, "error": "task not found"}), 404
        task = dict(task)
        if task["status"] != "review":
            con.close()
            return jsonify({"ok": False, "error": f"task is not in review status (current: {task['status']})"}), 400
        run_row = con.execute(
            "SELECT * FROM task_runs WHERE task_id = ? ORDER BY started_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        con.close()

        run_row = dict(run_row) if run_row else {}
        run_id = run_row.get("id", "")
        artifact_dir = Path(ARTIFACTS_DIR) / task_id / run_id

        routing = {}
        try:
            routing = json.loads(task.get("routing_json") or "{}")
        except (json.JSONDecodeError, ValueError):
            pass

        pipeline = {
            "delegation_mode": routing.get("delegation_mode", ""),
            "agent1": routing.get("agent1"),
            "agent2": routing.get("agent2"),
            "target_paths": routing.get("target_paths", []),
        }

        plan_text = None
        agent1_path = artifact_dir / "agent1_result.json"
        if agent1_path.exists():
            try:
                a1 = json.loads(agent1_path.read_text(encoding="utf-8"))
                plan_text = a1.get("stdout") or a1.get("plan")
            except (json.JSONDecodeError, OSError):
                pass

        changed_files = []
        cf_path = artifact_dir / "changed_files.json"
        if cf_path.exists():
            try:
                cf_data = json.loads(cf_path.read_text(encoding="utf-8"))
                raw = cf_data.get("changed_files", cf_data) if isinstance(cf_data, dict) else cf_data
                if isinstance(raw, list):
                    for f in raw:
                        if isinstance(f, str):
                            changed_files.append({"path": f, "additions": None, "deletions": None})
                        elif isinstance(f, dict):
                            changed_files.append(f)
            except (json.JSONDecodeError, OSError):
                pass

        diff_raw = None
        diff_path = artifact_dir / "git_diff.patch"
        if diff_path.exists():
            try:
                diff_raw = diff_path.read_text(encoding="utf-8")
            except OSError:
                pass

        return jsonify({
            "ok": True,
            "review_packet": {
                "task": {
                    "id": task["id"],
                    "title": task["title"],
                    "goal": task["goal"],
                    "project": task["project"],
                    "status": task["status"],
                    "risk_level": routing.get("risk_level", "medium"),
                    "created_at": task["created_at"],
                },
                "pipeline": pipeline,
                "plan": {"text": plan_text},
                "changed_files": changed_files,
                "diff": {"raw": diff_raw},
                "approval": {
                    "allowed": True,
                    "friction_level": _friction_level(routing),
                },
                "rollback_available": (artifact_dir / "rollback_patch.patch").exists(),
            },
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/tasks/<task_id>/approve", methods=["POST"])
def approve_task(task_id):
    return run([OPERATOR, "task", "approve", task_id])


@app.route("/api/tasks/<task_id>/reject", methods=["POST"])
def reject_task(task_id):
    return run([OPERATOR, "task", "reject", task_id])


@app.route("/api/projects")
def projects():
    try:
        projects_path = os.path.join(PROJECT_ROOT, "registry", "projects.yaml")
        with open(projects_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        result = []
        for slug, proj in (data.get("projects") or {}).items():
            result.append({
                "slug": slug,
                "name": proj.get("name") or slug,
                "path": proj.get("repo_path"),
                "description": proj.get("notes"),
            })
        return jsonify({"ok": True, "projects": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/preview", methods=["POST"])
def preview():
    body = request.get_json(silent=True) or {}
    task_text = body.get("task", "").strip()
    project_slug = (body.get("project") or "").strip()
    mode = (body.get("mode") or "auto").strip()

    if not task_text:
        return jsonify({"ok": False, "error": "missing 'task' field"}), 400

    worker_script = os.path.join(WEB_DIR, "preview_worker.py")
    payload = json.dumps({
        "task": task_text,
        "project": project_slug,
        "mode": mode,
        "project_root": PROJECT_ROOT,
    })

    try:
        result = subprocess.run(
            ["python3", worker_script],
            input=payload,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=PROJECT_ROOT,
        )
        raw = result.stdout.strip()
        if not raw:
            err = result.stderr.strip() or "preview produced no output"
            return jsonify({"ok": False, "error": err}), 500
        return jsonify(json.loads(raw))
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "preview timed out"}), 504
    except json.JSONDecodeError as exc:
        return jsonify({"ok": False, "error": f"invalid JSON from preview: {exc}"}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/ingest", methods=["POST"])
def ingest():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "no file uploaded"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "empty filename"}), 400

    ext = Path(f.filename).suffix.lower()
    if ext not in (".md", ".txt", ".docx"):
        return jsonify({"ok": False, "error": f"unsupported file type: {ext}"}), 400

    project_slug = (request.form.get("project") or "auto").strip()
    mode = (request.form.get("mode") or "auto").strip()

    tmp_path = os.path.join(tempfile.gettempdir(), f"operator-ingest-{uuid.uuid4().hex}{ext}")
    try:
        f.save(tmp_path)

        # --- Primary path: structured operator ingest ---
        result = subprocess.run(
            [OPERATOR, "ingest", tmp_path, "--yes"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=PROJECT_ROOT,
        )
        if result.returncode == 0:
            raw = result.stdout.strip()
            try:
                return jsonify({"ok": True, "output": json.loads(raw)})
            except (json.JSONDecodeError, ValueError):
                return jsonify({"ok": True, "output": raw})

        # --- Fallback: raw document mode ---
        task_text = _extract_text(tmp_path, ext)
        if task_text is None:
            # .docx and python-docx unavailable — surface original error
            return jsonify({"ok": False, "error": result.stderr.strip() or result.stdout.strip()}), 400

        task_text = task_text[:6000]

        worker_script = os.path.join(WEB_DIR, "preview_worker.py")
        payload = json.dumps({
            "task": task_text,
            "project": project_slug,
            "mode": mode,
            "project_root": PROJECT_ROOT,
        })
        pw = subprocess.run(
            ["python3", worker_script],
            input=payload,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=PROJECT_ROOT,
        )
        pw_raw = pw.stdout.strip()
        if not pw_raw:
            err = pw.stderr.strip() or "raw document preview produced no output"
            return jsonify({"ok": False, "error": err}), 500

        preview_data = json.loads(pw_raw)
        if not preview_data.get("ok"):
            return jsonify(preview_data), 500

        preview_data["mode"] = "raw_document"
        preview_data["raw_task"] = task_text
        return jsonify(preview_data)

    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "ingest timed out"}), 504
    except json.JSONDecodeError as exc:
        return jsonify({"ok": False, "error": f"invalid JSON from preview worker: {exc}"}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _extract_text(path: str, ext: str) -> "str | None":
    """Return plain text from a file, or None if extraction is not possible."""
    if ext in (".md", ".txt"):
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    if ext == ".docx":
        try:
            import docx as _docx  # python-docx
            doc = _docx.Document(path)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            return None
    return None


@app.route("/api/submit", methods=["POST"])
def submit():
    body = request.get_json(silent=True) or {}
    task = body.get("task", "").strip()
    project = (body.get("project") or "").strip()
    if not task:
        return jsonify({"ok": False, "error": "missing 'task' field"}), 400
    delegation_mode = (body.get("delegation_mode") or "").strip()
    preview = body.get("preview") if isinstance(body.get("preview"), dict) else {}
    pipeline_raw = (preview.get("pipeline_raw") or delegation_mode).strip()
    if pipeline_raw:
        project_slug = (preview.get("project") or project or "operator").strip()
        target_paths = preview.get("target_paths") if isinstance(preview.get("target_paths"), list) else []
        target_paths = [p.strip() for p in target_paths if isinstance(p, str) and p.strip()]
        if pipeline_raw in LIVE_WRITABLE_MODES and not target_paths:
            return jsonify({
                "ok": False,
                "error": "live writable preview requires explicit target_paths; refusing CLI defaults",
            }), 400
        if pipeline_raw == "live_codex_policy_file_only" and (
            not target_paths or any(path not in PREVIEW_POLICY_FILE_TARGETS for path in target_paths)
        ):
            return jsonify({
                "ok": False,
                "error": "live_codex_policy_file_only requires explicit app/policies.py target path",
            }), 400
        worker = preview.get("agent1") if pipeline_raw == "dry_run" else "codex"
        if worker not in {"codex", "claude_code", "gemini_cli"}:
            return jsonify({"ok": False, "error": f"unsupported preview worker: {worker}"}), 400
        cmd = [
            OPERATOR,
            "task",
            "create",
            "--project",
            project_slug,
            "--type",
            "delegated",
            "--title",
            task.splitlines()[0][:60] or "Queued Operator task",
            "--goal",
            task,
            "--worker",
            worker,
            "--delegation-mode",
            pipeline_raw,
        ]
        for target_path in target_paths:
            cmd += ["--target-path", target_path]
        return run(cmd)
    cmd = [OPERATOR, "do", task, "--yes"]
    if project and project not in ("auto", "scratchpad", ""):
        cmd += ["--project", project]
    return run(cmd)
