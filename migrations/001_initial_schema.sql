-- ============================================================
-- 001_initial_schema.sql
-- Agente VFO ("Vanessa") — schema completo do banco SQLite
-- Gerado a partir do banco em produção em 04/08/2026
-- Compatível com Agno schema version 2.5.6 (tabela agno_sessions)
-- ============================================================
-- Uso:  sqlite3 vanessa.db < migrations/001_initial_schema.sql
-- Idempotente: pode ser reaplicado sem erro (IF NOT EXISTS).
-- ============================================================

BEGIN;

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
        );
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
        );
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
    last_lead_message_at TEXT DEFAULT '',
    lead_first_contact_at TEXT DEFAULT '',
    pending_response INTEGER DEFAULT 0,
    pending_message_text TEXT DEFAULT '',
    paused INTEGER DEFAULT 0
, conversation_id TEXT DEFAULT '', external_id TEXT DEFAULT '', sender_name TEXT DEFAULT '', lead_name TEXT DEFAULT '', payment_tier_sent INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS agno_sessions (
	session_id VARCHAR NOT NULL, 
	session_type VARCHAR NOT NULL, 
	agent_id VARCHAR, 
	team_id VARCHAR, 
	workflow_id VARCHAR, 
	user_id VARCHAR, 
	session_data JSON, 
	agent_data JSON, 
	team_data JSON, 
	workflow_data JSON, 
	metadata JSON, 
	runs JSON, 
	summary JSON, 
	created_at BIGINT NOT NULL, 
	updated_at BIGINT, 
	PRIMARY KEY (session_id)
);
CREATE INDEX IF NOT EXISTS idx_agno_sessions_created_at ON agno_sessions (created_at);
CREATE INDEX IF NOT EXISTS idx_agno_sessions_session_type ON agno_sessions (session_type);
CREATE TABLE IF NOT EXISTS agno_schema_versions (
	table_name VARCHAR NOT NULL, 
	version VARCHAR NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR, 
	PRIMARY KEY (table_name)
);
CREATE INDEX IF NOT EXISTS idx_agno_schema_versions_created_at ON agno_schema_versions (created_at);
CREATE TABLE IF NOT EXISTS agent_transactions (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                from_number TEXT,
                started_at TEXT,
                completed_at TEXT,
                status TEXT,
                user_message TEXT,
                agent_reply TEXT,
                events TEXT
            );
CREATE TABLE IF NOT EXISTS payment_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id TEXT, phone TEXT, session_id TEXT, link_url TEXT,
        utm_source TEXT DEFAULT 'whatsappIA', utm_campaign TEXT,
        link_sent INTEGER DEFAULT 1, link_sent_at TEXT,
        paid INTEGER DEFAULT 0, paid_at TEXT,
        order_id TEXT DEFAULT '', order_status TEXT DEFAULT '',
        payment_method TEXT DEFAULT '', product_name TEXT DEFAULT '',
        amount REAL DEFAULT 0, created_at TEXT, updated_at TEXT
    );

-- Versão de schema esperada pelo Agno
INSERT OR IGNORE INTO agno_schema_versions (table_name, version, created_at, updated_at)
VALUES ('agno_sessions', '2.5.6', datetime('now'), datetime('now'));

COMMIT;
