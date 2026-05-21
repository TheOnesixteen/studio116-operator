import json
import subprocess
from flask import Flask, jsonify, request, send_from_directory
import os

app = Flask(__name__)
WEB_DIR = os.path.dirname(os.path.abspath(__file__))

OPERATOR = "./scripts/operator"
TIMEOUT = 60


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


@app.route("/api/submit", methods=["POST"])
def submit():
    body = request.get_json(silent=True) or {}
    task = body.get("task", "").strip()
    if not task:
        return jsonify({"ok": False, "error": "missing 'task' field"}), 400
    return run([OPERATOR, "do", task])
