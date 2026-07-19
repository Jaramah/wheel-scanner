"""SQLite persistence for the multi-agent platform."""

import os
import sqlite3
import threading
import time

DB_PATH = os.environ.get(
    "AGENT_PLATFORM_DB",
    os.path.join(os.path.dirname(__file__), "platform.db"),
)

_local = threading.local()


def _conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT,
    base_url      TEXT,
    credential    TEXT,            -- encrypted
    cred_kind     TEXT DEFAULT 'api_key',   -- api_key | subscription
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    description   TEXT,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    mode          TEXT NOT NULL,          -- cross_review | ensemble
    rounds        INTEGER NOT NULL,
    status        TEXT NOT NULL,          -- queued | running | done | error
    result        TEXT,
    error         TEXT,
    agent_ids     TEXT,                   -- json list
    created_at    REAL NOT NULL,
    finished_at   REAL
);

CREATE TABLE IF NOT EXISTS steps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    round         INTEGER NOT NULL,
    agent_id      INTEGER,
    agent_name    TEXT,
    role          TEXT,                   -- builder | reviewer | synthesizer
    kind          TEXT,                   -- draft | review | revision | synthesis | verdict | note
    content       TEXT,
    approved      INTEGER,                -- nullable bool for reviews
    created_at    REAL NOT NULL
);
"""


def init_db() -> None:
    conn = _conn()
    conn.executescript(SCHEMA)
    conn.commit()


# ---- generic helpers -------------------------------------------------------

def _insert(table: str, **fields) -> int:
    fields.setdefault("created_at", time.time())
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    conn = _conn()
    cur = conn.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
        tuple(fields.values()),
    )
    conn.commit()
    return cur.lastrowid


def _rows(query: str, params=()):
    return [dict(r) for r in _conn().execute(query, params).fetchall()]


def _row(query: str, params=()):
    r = _conn().execute(query, params).fetchone()
    return dict(r) if r else None


# ---- agents ----------------------------------------------------------------

def create_agent(**fields) -> int:
    return _insert("agents", **fields)


def list_agents():
    return _rows("SELECT * FROM agents ORDER BY created_at DESC")


def get_agent(agent_id: int):
    return _row("SELECT * FROM agents WHERE id = ?", (agent_id,))


def delete_agent(agent_id: int) -> None:
    conn = _conn()
    conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    conn.commit()


# ---- projects & tasks ------------------------------------------------------

def create_project(**fields) -> int:
    return _insert("projects", **fields)


def list_projects():
    return _rows("SELECT * FROM projects ORDER BY created_at DESC")


def get_project(project_id: int):
    return _row("SELECT * FROM projects WHERE id = ?", (project_id,))


def delete_project(project_id: int) -> None:
    conn = _conn()
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()


def create_task(**fields) -> int:
    return _insert("tasks", **fields)


def list_tasks(project_id: int):
    return _rows(
        "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    )


def get_task(task_id: int):
    return _row("SELECT * FROM tasks WHERE id = ?", (task_id,))


# ---- runs & steps ----------------------------------------------------------

def create_run(**fields) -> int:
    return _insert("runs", **fields)


def update_run(run_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn = _conn()
    conn.execute(
        f"UPDATE runs SET {cols} WHERE id = ?",
        tuple(fields.values()) + (run_id,),
    )
    conn.commit()


def get_run(run_id: int):
    return _row("SELECT * FROM runs WHERE id = ?", (run_id,))


def list_runs(task_id: int):
    return _rows(
        "SELECT * FROM runs WHERE task_id = ? ORDER BY created_at DESC",
        (task_id,),
    )


def add_step(**fields) -> int:
    return _insert("steps", **fields)


def list_steps(run_id: int):
    return _rows(
        "SELECT * FROM steps WHERE run_id = ? ORDER BY id ASC",
        (run_id,),
    )
