import json
import logging
import sqlite3
import traceback
from datetime import datetime, timezone

import httpx

_logger = logging.getLogger("vanessa.error_log")
_db_path: str = ""


def init(db_path: str) -> None:
    global _db_path
    _db_path = db_path
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tool_errors (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at      TEXT    NOT NULL,
            session_id      TEXT    NOT NULL,
            from_number     TEXT    NOT NULL,
            tool_name       TEXT    NOT NULL,
            error_type      TEXT    NOT NULL,
            http_status     INTEGER,
            error_message   TEXT    NOT NULL,
            request_context TEXT,
            raw_traceback   TEXT,
            eval_requested  INTEGER NOT NULL DEFAULT 0,
            eval_notes      TEXT
        )
    """)
    conn.commit()
    conn.close()


def _classify(exc: Exception, http_status: int | None) -> str:
    if http_status == 403:
        msg = str(exc).lower()
        return "auth_token_expired" if "expirado" in msg else "auth_token_invalid"
    if http_status == 404:
        return "auth_not_found"
    if http_status == 422:
        return "api_domain_error"
    if http_status and http_status >= 500:
        return "api_server_error"
    exc_name = type(exc).__name__.lower()
    if "timeout" in exc_name or "connect" in exc_name or "network" in exc_name:
        return "api_network_error"
    exc_str = str(exc).lower()
    if "timeout" in exc_str or "connection" in exc_str:
        return "api_network_error"
    return "unknown"


def record(
    session_id: str,
    from_number: str,
    tool_name: str,
    exc: Exception,
    context: dict | None = None,
    error_type: str | None = None,
) -> None:
    if not _db_path:
        return
    try:
        http_status: int | None = None
        if isinstance(exc, httpx.HTTPStatusError):
            http_status = exc.response.status_code

        etype = error_type or _classify(exc, http_status)
        tb = traceback.format_exc()

        conn = sqlite3.connect(_db_path)
        conn.execute(
            """INSERT INTO tool_errors
               (created_at, session_id, from_number, tool_name, error_type,
                http_status, error_message, request_context, raw_traceback)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                session_id or "",
                from_number or "",
                tool_name,
                etype,
                http_status,
                str(exc)[:2000],
                json.dumps(context or {}, default=str)[:4000],
                tb[:4000],
            ),
        )
        conn.commit()
        conn.close()
        _logger.info("error_log | recorded tool=%s type=%s session=%s", tool_name, etype, session_id)

        # Broadcast to SSE stream so dashboard updates in real time
        try:
            from app.log_store import log_store
            log_store._broadcast({
                "type": "tool_error",
                "error": {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "session_id": session_id or "",
                    "from_number": from_number or "",
                    "tool_name": tool_name,
                    "error_type": etype,
                    "http_status": http_status,
                    "error_message": str(exc)[:300],
                },
            })
        except Exception:
            pass
    except Exception as e:
        _logger.warning("error_log | failed to record: %s", e)


def query(
    tool_name: str | None = None,
    error_type: str | None = None,
    from_number: str | None = None,
    eval_requested: int | None = None,
    limit: int = 100,
) -> list[dict]:
    if not _db_path:
        return []
    try:
        conn = sqlite3.connect(_db_path)
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM tool_errors WHERE 1=1"
        params: list = []
        if tool_name:
            sql += " AND tool_name=?"; params.append(tool_name)
        if error_type:
            sql += " AND error_type=?"; params.append(error_type)
        if from_number:
            sql += " AND from_number=?"; params.append(from_number)
        if eval_requested is not None:
            sql += " AND eval_requested=?"; params.append(eval_requested)
        sql += " ORDER BY id DESC LIMIT ?"; params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        _logger.warning("error_log | query failed: %s", e)
        return []


def mark_eval(error_id: int, notes: str = "") -> bool:
    if not _db_path:
        return False
    try:
        conn = sqlite3.connect(_db_path)
        conn.execute(
            "UPDATE tool_errors SET eval_requested=1, eval_notes=? WHERE id=?",
            (notes, error_id),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        _logger.warning("error_log | mark_eval failed: %s", e)
        return False
