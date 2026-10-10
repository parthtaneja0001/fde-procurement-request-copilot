from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "human_decisions.db"
JSONL_PATH = ROOT / "data" / "human_decisions.jsonl"


def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS human_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                action TEXT NOT NULL,
                notes TEXT,
                architecture TEXT,
                recommendation TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        conn.commit()


def record_human_decision(
    request_id: str,
    action: str,  # 'APPROVE', 'REJECT', 'REQUEST_INFO'
    notes: str = "",
    reviewer: str = "Procurement Officer",
    architecture: str = "single",
    recommendation: str = "",
) -> dict[str, Any]:
    """Persist human review action to SQLite and JSONL log."""
    _init_db()
    ts = datetime.now(timezone.utc).isoformat()
    record = {
        "request_id": request_id,
        "reviewer": reviewer,
        "action": action,
        "notes": notes,
        "architecture": architecture,
        "recommendation": recommendation,
        "timestamp": ts,
    }

    # Write to SQLite
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO human_reviews (request_id, reviewer, action, notes, architecture, recommendation, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (request_id, reviewer, action, notes, architecture, recommendation, ts),
        )
        conn.commit()

    # Write to JSONL
    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return record


def get_human_decisions(request_id: str | None = None) -> list[dict[str, Any]]:
    """Retrieve history of human review actions."""
    _init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if request_id:
            cursor.execute(
                "SELECT * FROM human_reviews WHERE request_id = ? ORDER BY id DESC",
                (request_id,),
            )
        else:
            cursor.execute("SELECT * FROM human_reviews ORDER BY id DESC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
