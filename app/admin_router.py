from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.config import SESSION_DB_PATH
from app.log_store import log_store

logger = logging.getLogger("vanessa.admin")

router = APIRouter(prefix="/vfo/admin", tags=["admin"])

_HTML = Path(__file__).parent.parent / "static" / "admin.html"


def _db():
    conn = sqlite3.connect(SESSION_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── UI ────────────────────────────────────────────────────────────────────────

@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def admin_ui():
    return FileResponse(_HTML)


# ── REST ──────────────────────────────────────────────────────────────────────

@router.get("/sessions")
async def list_sessions():
    """List all sessions with lead info and metrics."""
    conn = _db()
    try:
        rows = conn.execute("""
            SELECT session_id, agent_id, created_at, updated_at, session_data
            FROM agno_sessions
            ORDER BY updated_at DESC
        """).fetchall()

        sessions = []
        for row in rows:
            sd = {}
            try:
                sd = json.loads(row["session_data"])
                if isinstance(sd, str):
                    sd = json.loads(sd)
            except Exception:
                pass

            state = sd.get("session_state", {})
            metrics = sd.get("session_metrics", {})

            sessions.append({
                "session_id": row["session_id"],
                "lead_name": state.get("lead_name", ""),
                "from_number": state.get("from_number", ""),
                "conversation_id": state.get("conversation_id", ""),
                "is_interested": state.get("is_interested", False),
                "is_purchased": state.get("is_purchased", False),
                "payment_tier_sent": state.get("payment_tier_sent", 0),
                "total_tokens": metrics.get("total_tokens", 0),
                "cost": metrics.get("cost", 0),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })

        return {"sessions": sessions}
    finally:
        conn.close()


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    """Get conversation messages for a session."""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT runs FROM agno_sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()

        if not row:
            raise HTTPException(404, "Session not found")

        runs_raw = row["runs"]
        if not runs_raw:
            return {"messages": []}

        runs = json.loads(runs_raw)
        if isinstance(runs, str):
            runs = json.loads(runs)

        messages = []
        for run in runs:
            if isinstance(run, str):
                run = json.loads(run)

            # Extract user message from messages array
            run_messages = run.get("messages", [])
            user_msg = None
            for msg in run_messages:
                if isinstance(msg, dict) and msg.get("role") == "user":
                    user_msg = msg.get("content", "")
                    break

            messages.append({
                "run_id": run.get("run_id", ""),
                "user_message": user_msg or "",
                "agent_reply": run.get("content", ""),
                "reasoning": run.get("reasoning_content", ""),
                "created_at": run.get("created_at", 0),
                "status": run.get("status", ""),
                "model": run.get("model", ""),
                "session_state": run.get("session_state", {}),
            })

        return {"messages": messages}
    finally:
        conn.close()


@router.get("/stats")
async def get_stats():
    """Get overall stats."""
    conn = _db()
    try:
        rows = conn.execute("""
            SELECT session_data FROM agno_sessions
        """).fetchall()

        total_sessions = len(rows)
        total_tokens = 0
        total_cost = 0.0
        interested = 0
        purchased = 0

        for row in rows:
            try:
                sd = json.loads(row["session_data"])
                if isinstance(sd, str):
                    sd = json.loads(sd)
                state = sd.get("session_state", {})
                metrics = sd.get("session_metrics", {})
                total_tokens += metrics.get("total_tokens", 0)
                total_cost += metrics.get("cost", 0)
                if state.get("is_interested"):
                    interested += 1
                if state.get("is_purchased"):
                    purchased += 1
            except Exception:
                pass

        return {
            "total_sessions": total_sessions,
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 4),
            "interested": interested,
            "purchased": purchased,
        }
    finally:
        conn.close()


@router.get("/logs")
async def list_transactions(session_id: Optional[str] = Query(default=None)):
    """List all logged transactions (in-memory + persisted from DB)."""
    return _query_transactions(session_id)


@router.get("/stream")
async def sse_stream(request: Request):
    queue = log_store.subscribe()

    async def generator():
        try:
            init = json.dumps({"type": "init", "transactions": log_store.get_all()})
            yield f"data: {init}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            log_store.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/errors")
async def list_errors(
    tool_name: Optional[str] = Query(default=None),
    error_type: Optional[str] = Query(default=None),
    from_number: Optional[str] = Query(default=None),
    eval_requested: Optional[int] = Query(default=None),
    limit: int = Query(default=100, le=500),
):
    import app.error_log as error_log
    return error_log.query(
        tool_name=tool_name,
        error_type=error_type,
        from_number=from_number,
        eval_requested=eval_requested,
        limit=limit,
    )


@router.post("/errors/{error_id}/eval")
async def request_eval(error_id: int, notes: str = ""):
    import app.error_log as error_log
    ok = error_log.mark_eval(error_id, notes)
    return {"ok": ok}


@router.get("/llm-usage")
async def list_llm_usage(
    session_id: Optional[str] = Query(default=None),
    from_date: Optional[str] = Query(default=None, description="ISO date, e.g. 2026-05-01"),
    to_date: Optional[str] = Query(default=None, description="ISO date, e.g. 2026-05-07"),
    limit: int = Query(default=500, le=2000),
):
    import app.llm_usage_log as llm_log
    from_iso = (from_date + "T00:00:00+00:00") if from_date else None
    to_iso   = (to_date   + "T23:59:59+00:00") if to_date   else None
    rows = llm_log.query(session_id=session_id, from_iso=from_iso, to_iso=to_iso, limit=limit)
    totals = llm_log.totals()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00+00:00")
    today_totals = llm_log.totals(since_iso=today)
    return {"rows": rows, "totals": totals, "today": today_totals}


# ── SQLite helpers ────────────────────────────────────────────────────────────

def _db_connect() -> sqlite3.Connection | None:
    try:
        p = Path(SESSION_DB_PATH)
        if not p.exists():
            return None
        conn = sqlite3.connect(str(p))
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as exc:
        logger.warning("DB connect failed: %s", exc)
        return None


def _query_transactions(session_id: str | None = None) -> list[dict]:
    """Return completed transactions from DB, merged with any live in-memory ones."""
    # In-memory live transactions (processing / just completed)
    live = {tx["id"]: tx for tx in log_store.get_all(session_id=session_id)}

    # Historical from DB
    conn = _db_connect()
    db_rows: list[dict] = []
    if conn:
        try:
            conn.row_factory = sqlite3.Row
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            if "agent_transactions" in tables:
                q = "SELECT * FROM agent_transactions"
                params: list = []
                if session_id:
                    q += " WHERE session_id = ?"
                    params.append(session_id)
                q += " ORDER BY started_at DESC LIMIT 200"
                for row in conn.execute(q, params).fetchall():
                    r = dict(row)
                    try:
                        r["events"] = json.loads(r.get("events") or "[]")
                    except Exception:
                        r["events"] = []
                    # Compute duration_ms
                    if r.get("started_at") and r.get("completed_at"):
                        try:
                            a = datetime.fromisoformat(r["started_at"])
                            b = datetime.fromisoformat(r["completed_at"])
                            r["duration_ms"] = int((b - a).total_seconds() * 1000)
                        except Exception:
                            r["duration_ms"] = None
                    else:
                        r["duration_ms"] = None
                    db_rows.append(r)
        except Exception as exc:
            logger.error("query_transactions DB: %s", exc)
        finally:
            conn.close()

    # Merge: live takes precedence (more up-to-date events)
    merged = {**{r["id"]: r for r in db_rows}, **live}
    return sorted(merged.values(), key=lambda t: t.get("started_at", ""), reverse=True)
