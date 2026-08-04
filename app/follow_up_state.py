"""
follow_up_state.py — Tabela dedicada para flags de follow-up e automação.

Resolve a race condition entre o Agno (que sobrescreve session_data) e o
follow_up_scheduler (que seta flags dentro de session_data).

Agora as flags ficam em tabela separada: follow_up_state.
Ambos (scheduler e agent tools) leem e escrevem aqui.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.config import SESSION_DB_PATH

logger = logging.getLogger("vanessa.follow_up_state")

# All flag/tracking columns that live in follow_up_state
_FLAG_COLUMNS = [
    "automation_1_sent",
    "automation_2_sent",
    "experiencia_sent",
    "follow_1_1_sent",
    "follow_1_2_sent",
    "follow_1_3_sent",
    "follow_1_4_sent",
    "follow_2_1_sent",
    "follow_2_2_sent",
    "follow_2_3_sent",
    "follow_3_1_sent",
    "follow_3_2_sent",
    "follow_3_3_sent",
    "follow_janela_24h_sent",
]

_TRACKING_COLUMNS = [
    "follow_up_flow",
    "follow_up_flow_count",
    "follow_up_flow_started_at",
    "follow_up_flow_anchor",
    "follow_up_expired",
    "is_purchased",
    "payment_tier_sent",
    "last_lead_message_at",
    "lead_first_contact_at",
    "pending_response",
    "pending_message_text",
    "paused",
    "conversation_id",
    "external_id",
    "sender_name",
    "lead_name",
]

_ALL_COLUMNS = _FLAG_COLUMNS + _TRACKING_COLUMNS

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS follow_up_state (
    session_id TEXT PRIMARY KEY,
    automation_1_sent INTEGER DEFAULT 0,
    automation_2_sent INTEGER DEFAULT 0,
    experiencia_sent INTEGER DEFAULT 0,
    follow_1_1_sent INTEGER DEFAULT 0,
    follow_1_2_sent INTEGER DEFAULT 0,
    follow_1_3_sent INTEGER DEFAULT 0,
    follow_1_4_sent INTEGER DEFAULT 0,
    follow_2_1_sent INTEGER DEFAULT 0,
    follow_2_2_sent INTEGER DEFAULT 0,
    follow_2_3_sent INTEGER DEFAULT 0,
    follow_3_1_sent INTEGER DEFAULT 0,
    follow_3_2_sent INTEGER DEFAULT 0,
    follow_3_3_sent INTEGER DEFAULT 0,
    follow_janela_24h_sent INTEGER DEFAULT 0,
    follow_up_flow INTEGER DEFAULT 0,
    follow_up_flow_count INTEGER DEFAULT 0,
    follow_up_flow_started_at TEXT DEFAULT '',
    follow_up_flow_anchor TEXT DEFAULT '',
    follow_up_expired INTEGER DEFAULT 0,
    is_purchased INTEGER DEFAULT 0,
    payment_tier_sent INTEGER DEFAULT 0,
    last_lead_message_at TEXT DEFAULT '',
    lead_first_contact_at TEXT DEFAULT '',
    pending_response INTEGER DEFAULT 0,
    pending_message_text TEXT DEFAULT '',
    paused INTEGER DEFAULT 0,
    conversation_id TEXT DEFAULT '',
    external_id TEXT DEFAULT '',
    sender_name TEXT DEFAULT '',
    lead_name TEXT DEFAULT ''
)
"""


def init_table() -> None:
    """Create the follow_up_state table if it doesn't exist."""
    conn = sqlite3.connect(SESSION_DB_PATH)
    conn.execute(_CREATE_TABLE)
    conn.commit()
    conn.close()
    # Migration: add columns that may not exist in older databases
    _ensure_columns()
    _init_payment_links()
    logger.info("follow_up_state table ensured")


def _ensure_columns() -> None:
    """Add missing columns to existing tables (idempotent migration)."""
    conn = sqlite3.connect(SESSION_DB_PATH)
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(follow_up_state)").fetchall()}
        for col in ["payment_tier_sent", "pending_response", "pending_message_text", "paused",
                     "conversation_id", "external_id", "sender_name", "lead_name"]:
            if col not in existing:
                col_type = "TEXT" if col in ("pending_message_text", "conversation_id", "external_id", "sender_name", "lead_name") else "INTEGER"
                default = "''" if col in ("pending_message_text", "conversation_id", "external_id", "sender_name", "lead_name") else "0"
                conn.execute(f"ALTER TABLE follow_up_state ADD COLUMN {col} {col_type} DEFAULT {default}")
                logger.info("_ensure_columns | added column: %s", col)
        conn.commit()
    except Exception as exc:
        logger.warning("_ensure_columns | migration error: %s", exc)
    finally:
        conn.close()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(SESSION_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_state(session_id: str) -> dict[str, Any]:
    """Get follow-up state for a session. Returns empty dict if not found."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM follow_up_state WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    if not row:
        return {}
    return {k: row[k] for k in _ALL_COLUMNS if k in row.keys()}


def get_all_states() -> dict[str, dict[str, Any]]:
    """Get all follow-up states, keyed by session_id."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM follow_up_state").fetchall()
    conn.close()
    result = {}
    for row in rows:
        sid = row["session_id"]
        result[sid] = {k: row[k] for k in _ALL_COLUMNS if k in row.keys()}
    return result


def ensure_row(session_id: str) -> None:
    """Ensure a row exists for this session (no-op if already exists)."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO follow_up_state (session_id) VALUES (?)",
        (session_id,),
    )
    conn.commit()
    conn.close()


def set_flag(session_id: str, flag_name: str, value: bool = True) -> None:
    """Set a single flag (boolean stored as 0/1)."""
    if flag_name not in _ALL_COLUMNS:
        logger.warning("set_flag | unknown column: %s", flag_name)
        return
    ensure_row(session_id)
    conn = _get_conn()
    conn.execute(
        f"UPDATE follow_up_state SET {flag_name} = ? WHERE session_id = ?",
        (1 if value else 0, session_id),
    )
    conn.commit()
    conn.close()
    logger.debug("set_flag | %s.%s = %s", session_id, flag_name, value)


def set_value(session_id: str, column: str, value: Any) -> None:
    """Set a single column value (any type)."""
    if column not in _ALL_COLUMNS:
        logger.warning("set_value | unknown column: %s", column)
        return
    ensure_row(session_id)
    conn = _get_conn()
    conn.execute(
        f"UPDATE follow_up_state SET {column} = ? WHERE session_id = ?",
        (value, session_id),
    )
    conn.commit()
    conn.close()
    logger.debug("set_value | %s.%s = %r", session_id, column, value)


def update_many(session_id: str, updates: dict[str, Any]) -> None:
    """Update multiple columns at once in a single transaction."""
    if not updates:
        return
    # Validate columns
    valid = {k: v for k, v in updates.items() if k in _ALL_COLUMNS}
    if not valid:
        return
    ensure_row(session_id)
    conn = _get_conn()
    set_clause = ", ".join(f"{k} = ?" for k in valid)
    values = list(valid.values()) + [session_id]
    conn.execute(
        f"UPDATE follow_up_state SET {set_clause} WHERE session_id = ?",
        values,
    )
    conn.commit()
    conn.close()
    logger.debug("update_many | %s: %s", session_id, list(valid.keys()))


def delete_state(session_id: str) -> None:
    """Delete follow-up state for a session (used by /flush)."""
    conn = _get_conn()
    conn.execute("DELETE FROM follow_up_state WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
    logger.info("delete_state | %s", session_id)


def get_flag(session_id: str, flag_name: str) -> bool:
    """Get a single flag value. Returns False if not found."""
    state = get_state(session_id)
    return bool(state.get(flag_name, False))


def get_bool(session_id: str, column: str) -> bool:
    """Get a boolean column value. Returns False if not found."""
    return get_flag(session_id, column)


def get_int(session_id: str, column: str, default: int = 0) -> int:
    """Get an integer column value."""
    state = get_state(session_id)
    return int(state.get(column, default))


def get_str(session_id: str, column: str, default: str = "") -> str:
    """Get a string column value."""
    state = get_state(session_id)
    return str(state.get(column, default))

# ═══════════════════════════════════════════════════════════════════════════════
# payment_links — Rastreamento de links de pagamento
# ═══════════════════════════════════════════════════════════════════════════════

_CREATE_PAYMENT_LINKS = """
CREATE TABLE IF NOT EXISTS payment_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT,
    phone TEXT,
    session_id TEXT,
    link_url TEXT,
    utm_source TEXT DEFAULT 'whatsappIA',
    utm_campaign TEXT,
    link_sent INTEGER DEFAULT 1,
    link_sent_at TEXT,
    paid INTEGER DEFAULT 0,
    paid_at TEXT,
    order_id TEXT DEFAULT '',
    order_status TEXT DEFAULT '',
    payment_method TEXT DEFAULT '',
    product_name TEXT DEFAULT '',
    amount REAL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
)
"""


def _init_payment_links() -> None:
    """Create the payment_links table if it doesn't exist."""
    conn = sqlite3.connect(SESSION_DB_PATH)
    conn.execute(_CREATE_PAYMENT_LINKS)
    conn.commit()
    conn.close()
    logger.info("payment_links table ensured")


def record_link_sent(
    lead_id: str,
    phone: str,
    session_id: str,
    link_url: str,
    utm_campaign: str,
) -> int:
    """Record that a payment link was sent to a lead. Returns the row id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO payment_links
           (lead_id, phone, session_id, link_url, utm_source, utm_campaign,
            link_sent, link_sent_at, paid, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'whatsappIA', ?, 1, ?, 0, ?, ?)""",
        (lead_id, phone, session_id, link_url, utm_campaign, now, now, now),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    logger.info("record_link_sent | id=%d phone=%s campaign=%s", row_id, phone, utm_campaign)
    return row_id


def mark_paid(
    lead_id: str = "",
    phone: str = "",
    order_id: str = "",
    order_status: str = "paid",
    payment_method: str = "",
    product_name: str = "",
    amount: float = 0,
) -> bool:
    """Mark a payment link as paid. Searches by lead_id or phone.
    Returns True if a row was updated."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    if lead_id:
        cur = conn.execute(
            """UPDATE payment_links SET paid=1, paid_at=?, order_id=?, order_status=?,
               payment_method=?, product_name=?, amount=?, updated_at=?
               WHERE lead_id=? AND paid=0""",
            (now, order_id, order_status, payment_method, product_name, amount, now, lead_id),
        )
    elif phone:
        cur = conn.execute(
            """UPDATE payment_links SET paid=1, paid_at=?, order_id=?, order_status=?,
               payment_method=?, product_name=?, amount=?, updated_at=?
               WHERE phone=? AND paid=0""",
            (now, order_id, order_status, payment_method, product_name, amount, now, phone),
        )
    else:
        conn.close()
        return False
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    logger.info("mark_paid | lead_id=%s phone=%s order=%s updated=%s", lead_id, phone, order_id, updated)
    return updated


def mark_refunded(order_id: str) -> bool:
    """Mark an order as refunded."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE payment_links SET order_status='refunded', updated_at=? WHERE order_id=?",
        (now, order_id),
    )
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    logger.info("mark_refunded | order_id=%s updated=%s", order_id, updated)
    return updated


def get_payment_link_by_lead(lead_id: str) -> dict | None:
    """Get the most recent payment link for a lead."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM payment_links WHERE lead_id=? ORDER BY created_at DESC LIMIT 1",
        (lead_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def get_payment_link_by_phone(phone: str) -> dict | None:
    """Get the most recent payment link for a phone."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM payment_links WHERE phone=? ORDER BY created_at DESC LIMIT 1",
        (phone,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)
