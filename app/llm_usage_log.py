"""Persistent log of LLM usage metrics per agent run."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("vanessa.llm_usage")

_DB_PATH: Path | None = None


def init(db_path: str) -> None:
    global _DB_PATH
    _DB_PATH = Path(db_path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_usage_log (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            ts                  TEXT    NOT NULL,
            session_id          TEXT    NOT NULL,
            model               TEXT    NOT NULL,
            input_tokens        INTEGER DEFAULT 0,
            output_tokens       INTEGER DEFAULT 0,
            cache_read_tokens   INTEGER DEFAULT 0,
            cache_write_tokens  INTEGER DEFAULT 0,
            total_tokens        INTEGER DEFAULT 0,
            cost_usd            REAL,
            latency_ms          INTEGER
        )
    """)
    conn.commit()
    conn.close()


def save(
    session_id: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    total_tokens: int = 0,
    cost_usd: float | None = None,
    latency_ms: int | None = None,
) -> None:
    if not _DB_PATH:
        return
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute(
            """
            INSERT INTO llm_usage_log
                (ts, session_id, model, input_tokens, output_tokens,
                 cache_read_tokens, cache_write_tokens, total_tokens, cost_usd, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                session_id,
                model,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cache_write_tokens,
                total_tokens,
                cost_usd,
                latency_ms,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error("llm_usage_log.save: %s", exc)


def query(
    session_id: str | None = None,
    from_iso: str | None = None,
    to_iso: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    if not _DB_PATH or not _DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        clauses, params = [], []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if from_iso:
            clauses.append("ts >= ?")
            params.append(from_iso)
        if to_iso:
            clauses.append("ts <= ?")
            params.append(to_iso)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM llm_usage_log {where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("llm_usage_log.query: %s", exc)
        return []


def totals(since_iso: str | None = None) -> dict[str, Any]:
    """Return aggregate totals (tokens, cost) optionally filtered by date."""
    if not _DB_PATH or not _DB_PATH.exists():
        return {}
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        where = "WHERE ts >= ?" if since_iso else ""
        params = (since_iso,) if since_iso else ()
        row = conn.execute(
            f"""SELECT
                COUNT(*)            AS runs,
                SUM(input_tokens)   AS input_tokens,
                SUM(output_tokens)  AS output_tokens,
                SUM(cache_read_tokens) AS cache_read_tokens,
                SUM(total_tokens)   AS total_tokens,
                SUM(cost_usd)       AS cost_usd,
                AVG(latency_ms)     AS avg_latency_ms
            FROM llm_usage_log {where}""",
            params,
        ).fetchone()
        conn.close()
        return dict(zip(
            ["runs", "input_tokens", "output_tokens", "cache_read_tokens",
             "total_tokens", "cost_usd", "avg_latency_ms"],
            row,
        )) if row else {}
    except Exception as exc:
        logger.error("llm_usage_log.totals: %s", exc)
        return {}
