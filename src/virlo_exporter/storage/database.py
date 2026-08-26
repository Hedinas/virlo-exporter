from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._lock, self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agents(
                    agent_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS runs(
                    agent_id TEXT NOT NULL, run_id TEXT NOT NULL, research_number INTEGER NOT NULL,
                    payload TEXT NOT NULL, started_at TEXT, PRIMARY KEY(agent_id, run_id),
                    UNIQUE(agent_id, research_number)
                );
                CREATE TABLE IF NOT EXISTS exports(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, run_id TEXT NOT NULL,
                    research_number INTEGER NOT NULL, export_number INTEGER NOT NULL, path TEXT NOT NULL,
                    started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL,
                    validation_state TEXT, UNIQUE(agent_id, run_id, export_number)
                );
                CREATE TABLE IF NOT EXISTS processes(
                    process_id TEXT PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS research_metadata(
                    agent_id TEXT NOT NULL, run_id TEXT NOT NULL, display_name TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(agent_id, run_id)
                );
                CREATE TABLE IF NOT EXISTS export_stages(
                    export_id INTEGER NOT NULL, sequence INTEGER NOT NULL, stage TEXT NOT NULL,
                    label TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT,
                    completed_at TEXT, summary TEXT, detail TEXT,
                    PRIMARY KEY(export_id, sequence)
                );
                """
            )
            db.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def cache_agent(self, agent: dict[str, Any]) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO agents(agent_id,payload,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)",
                (str(agent["id"]), json.dumps(agent, ensure_ascii=False)),
            )

    def cached_agents(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [
                json.loads(row["payload"])
                for row in db.execute("SELECT payload FROM agents ORDER BY updated_at DESC")
            ]

    def assign_runs(self, agent_id: str, runs: list[dict[str, Any]]) -> dict[str, int]:
        # Number chronologically; existing mappings never change.
        def sort_key(run: dict[str, Any]) -> str:
            return str(
                run.get("started_at")
                or run.get("created_at")
                or run.get("completed_at")
                or run.get("id")
            )

        with self._lock, self.connect() as db:
            existing = {
                row["run_id"]: row["research_number"]
                for row in db.execute(
                    "SELECT run_id,research_number FROM runs WHERE agent_id=?", (agent_id,)
                )
            }
            next_number = max(existing.values(), default=0) + 1
            for run in sorted(runs, key=sort_key):
                run_id = str(run.get("id") or run.get("run_id"))
                if not run_id:
                    continue
                number = existing.get(run_id)
                if number is None:
                    number = next_number
                    next_number += 1
                    existing[run_id] = number
                db.execute(
                    """INSERT INTO runs(agent_id,run_id,research_number,payload,started_at)
                       VALUES(?,?,?,?,?) ON CONFLICT(agent_id,run_id) DO UPDATE SET payload=excluded.payload""",
                    (agent_id, run_id, number, json.dumps(run, ensure_ascii=False), sort_key(run)),
                )
            return existing

    def research_number(self, agent_id: str, run_id: str) -> int:
        with self.connect() as db:
            row = db.execute(
                "SELECT research_number FROM runs WHERE agent_id=? AND run_id=?", (agent_id, run_id)
            ).fetchone()
        if row:
            return int(row[0])
        return self.assign_runs(agent_id, [{"id": run_id}])[run_id]

    def cached_runs(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT r.agent_id,r.run_id,r.research_number,r.payload,r.started_at,"
                "m.display_name FROM runs r LEFT JOIN research_metadata m "
                "ON m.agent_id=r.agent_id AND m.run_id=r.run_id ORDER BY r.started_at DESC"
            ).fetchall()
        values: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload"])
            payload.setdefault("id", row["run_id"])
            payload.setdefault("agent_id", row["agent_id"])
            payload["local_number"] = int(row["research_number"])
            payload["local_name"] = row["display_name"]
            values.append(payload)
        return values

    def rename_research(self, agent_id: str, run_id: str, display_name: str) -> None:
        value = display_name.strip()
        if not value:
            raise ValueError("Research name cannot be empty.")
        with self._lock, self.connect() as db:
            db.execute(
                """INSERT INTO research_metadata(agent_id,run_id,display_name)
                   VALUES(?,?,?) ON CONFLICT(agent_id,run_id) DO UPDATE SET
                   display_name=excluded.display_name,updated_at=CURRENT_TIMESTAMP""",
                (agent_id, run_id, value),
            )

    def research_display_name(self, agent_id: str, run_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT display_name FROM research_metadata WHERE agent_id=? AND run_id=?",
                (agent_id, run_id),
            ).fetchone()
        return str(row[0]) if row else None

    def begin_export(
        self, agent_id: str, run_id: str, research_number: int, path: str, started_at: str
    ) -> tuple[int, int]:
        with self._lock, self.connect() as db:
            row = db.execute(
                "SELECT COALESCE(MAX(export_number),0)+1 FROM exports WHERE agent_id=? AND run_id=?",
                (agent_id, run_id),
            ).fetchone()
            export_number = int(row[0])
            cursor = db.execute(
                """INSERT INTO exports(agent_id,run_id,research_number,export_number,path,started_at,status)
                   VALUES(?,?,?,?,?,?,?)""",
                (agent_id, run_id, research_number, export_number, path, started_at, "running"),
            )
            return int(cursor.lastrowid), export_number

    def update_export(
        self, export_id: int, *, path: str, status: str, completed_at: str | None, validation: str
    ) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "UPDATE exports SET path=?,status=?,completed_at=?,validation_state=? WHERE id=?",
                (path, status, completed_at, validation, export_id),
            )

    def export_history(self, agent_id: str, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM exports WHERE agent_id=? AND run_id=? AND status!='deleted' "
                "ORDER BY export_number DESC",
                (agent_id, run_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_export(self, export_id: int) -> None:
        """Permanently remove an export's local records. The exports row
        itself is kept as a tombstone (status='deleted', path cleared) so
        export_number stays monotonic -- a deleted #006 is never reissued
        to a later export. Only stage history is actually deleted; callers
        are responsible for removing the export's directory from disk."""
        with self._lock, self.connect() as db:
            db.execute("DELETE FROM export_stages WHERE export_id=?", (export_id,))
            db.execute(
                "UPDATE exports SET status='deleted', path='' WHERE id=?", (export_id,)
            )

    def upsert_export_stage(self, export_id: int, event: dict[str, Any]) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                """INSERT INTO export_stages(
                       export_id,sequence,stage,label,status,started_at,completed_at,summary,detail
                   ) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(export_id,sequence) DO UPDATE SET
                       status=excluded.status,completed_at=excluded.completed_at,
                       summary=excluded.summary,detail=excluded.detail""",
                (
                    export_id,
                    int(event["sequence"]),
                    str(event["stage"]),
                    str(event["label"]),
                    str(event["status"]),
                    event.get("started_at"),
                    event.get("completed_at"),
                    event.get("summary"),
                    event.get("detail"),
                ),
            )

    def export_stages(self, export_id: int) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM export_stages WHERE export_id=? ORDER BY sequence", (export_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_process(
        self, process_id: str, kind: str, label: str, status: str, payload: dict[str, Any]
    ) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                """INSERT INTO processes(process_id,kind,label,status,payload) VALUES(?,?,?,?,?)
                   ON CONFLICT(process_id) DO UPDATE SET status=excluded.status,payload=excluded.payload,updated_at=CURRENT_TIMESTAMP""",
                (process_id, kind, label, status, json.dumps(payload, ensure_ascii=False)),
            )

    def active_processes(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM processes WHERE status IN ('pending','running','processing') ORDER BY updated_at DESC"
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]
