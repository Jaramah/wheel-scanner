"""Multi-agent operating platform — Flask backend + JSON API.

Users register multiple coding-agent credentials (subscription keys or API
keys), create projects and tasks, then let several agents collaborate on a
task while cross-reviewing each other's work.

Run:  python app.py     (serves UI + API on :5001)
"""

import json
import os
import threading

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import db
import orchestrator
from crypto import decrypt, encrypt, mask
from providers import PROVIDERS

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

db.init_db()


def _public_agent(a):
    cred = decrypt(a.get("credential") or "")
    return {
        "id": a["id"],
        "name": a["name"],
        "provider": a["provider"],
        "provider_label": PROVIDERS.get(a["provider"], {}).get("label", a["provider"]),
        "model": a["model"],
        "base_url": a["base_url"],
        "cred_kind": a["cred_kind"],
        "credential_hint": mask(cred) if cred else "",
        "has_credential": bool(cred),
        "created_at": a["created_at"],
    }


# ---- static UI -------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ---- meta ------------------------------------------------------------------

@app.route("/api/providers")
def api_providers():
    return jsonify([
        {"id": pid, **{k: v for k, v in meta.items()}}
        for pid, meta in PROVIDERS.items()
    ])


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


# ---- agents ----------------------------------------------------------------

@app.route("/api/agents", methods=["GET", "POST"])
def api_agents():
    if request.method == "GET":
        return jsonify([_public_agent(a) for a in db.list_agents()])

    data = request.get_json(force=True) or {}
    provider = data.get("provider", "mock")
    if provider not in PROVIDERS:
        return jsonify({"error": f"unknown provider '{provider}'"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    meta = PROVIDERS[provider]
    agent_id = db.create_agent(
        name=name,
        provider=provider,
        model=(data.get("model") or meta.get("default_model") or "").strip(),
        base_url=(data.get("base_url") or "").strip(),
        credential=encrypt((data.get("credential") or "").strip()),
        cred_kind=meta.get("cred_kind", "api_key"),
    )
    return jsonify(_public_agent(db.get_agent(agent_id))), 201


@app.route("/api/agents/<int:agent_id>", methods=["DELETE"])
def api_agent_delete(agent_id):
    db.delete_agent(agent_id)
    return jsonify({"deleted": agent_id})


# ---- projects & tasks ------------------------------------------------------

@app.route("/api/projects", methods=["GET", "POST"])
def api_projects():
    if request.method == "GET":
        out = []
        for p in db.list_projects():
            p["tasks"] = db.list_tasks(p["id"])
            out.append(p)
        return jsonify(out)

    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    pid = db.create_project(name=name, description=(data.get("description") or "").strip())
    return jsonify(db.get_project(pid)), 201


@app.route("/api/projects/<int:project_id>", methods=["DELETE"])
def api_project_delete(project_id):
    db.delete_project(project_id)
    return jsonify({"deleted": project_id})


@app.route("/api/projects/<int:project_id>/tasks", methods=["POST"])
def api_create_task(project_id):
    if not db.get_project(project_id):
        return jsonify({"error": "project not found"}), 404
    data = request.get_json(force=True) or {}
    title = (data.get("title") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    if not title or not prompt:
        return jsonify({"error": "title and prompt are required"}), 400
    tid = db.create_task(project_id=project_id, title=title, prompt=prompt)
    return jsonify(db.get_task(tid)), 201


# ---- runs ------------------------------------------------------------------

@app.route("/api/tasks/<int:task_id>/runs", methods=["GET", "POST"])
def api_runs(task_id):
    task = db.get_task(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404

    if request.method == "GET":
        return jsonify(db.list_runs(task_id))

    data = request.get_json(force=True) or {}
    mode = data.get("mode", "cross_review")
    if mode not in ("cross_review", "ensemble"):
        return jsonify({"error": "mode must be cross_review or ensemble"}), 400
    try:
        rounds = max(1, min(6, int(data.get("rounds", 2))))
    except (TypeError, ValueError):
        rounds = 2
    agent_ids = data.get("agent_ids") or []
    agent_ids = [int(a) for a in agent_ids]
    if not agent_ids:
        return jsonify({"error": "select at least one agent"}), 400

    run_id = db.create_run(
        task_id=task_id,
        mode=mode,
        rounds=rounds,
        status="queued",
        agent_ids=json.dumps(agent_ids),
    )
    threading.Thread(
        target=orchestrator.execute_run, args=(run_id,), daemon=True
    ).start()
    return jsonify(db.get_run(run_id)), 201


@app.route("/api/runs/<int:run_id>")
def api_run_detail(run_id):
    run = db.get_run(run_id)
    if not run:
        return jsonify({"error": "run not found"}), 404
    run["steps"] = db.list_steps(run_id)
    return jsonify(run)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
