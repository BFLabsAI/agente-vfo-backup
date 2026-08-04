#!/usr/bin/env python3
"""
Cria ou atualiza o banco SQLite do agente aplicando as migrations em ordem.

Uso:
    python migrate.py                                   # usa SESSION_DB_PATH do .env
    python migrate.py --db instances/vanessa-1/data/vanessa.db
    python migrate.py --check                           # só verifica, não altera

As migrations ficam em migrations/*.sql e são aplicadas em ordem alfabética.
Cada uma roda uma única vez; o controle fica na tabela schema_migrations.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_control_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename    TEXT PRIMARY KEY,
            applied_at  TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _applied(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}


def _pending(conn: sqlite3.Connection) -> list[Path]:
    done = _applied(conn)
    return [p for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if p.name not in done]


def resolve_db_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.getenv("SESSION_DB_PATH")
    if env:
        return Path(env)
    sys.exit(
        "Erro: informe o banco com --db, ou defina SESSION_DB_PATH no ambiente.\n"
        "Exemplo: python migrate.py --db instances/vanessa-1/data/vanessa.db"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Aplica as migrations do banco do agente.")
    ap.add_argument("--db", help="caminho do arquivo .db")
    ap.add_argument("--check", action="store_true", help="lista pendências e sai")
    args = ap.parse_args()

    if not MIGRATIONS_DIR.is_dir():
        sys.exit(f"Erro: pasta de migrations não encontrada em {MIGRATIONS_DIR}")

    db_path = resolve_db_path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not db_path.exists()

    conn = sqlite3.connect(db_path)
    try:
        _ensure_control_table(conn)
        pending = _pending(conn)

        print(f"Banco: {db_path}{'  (novo)' if is_new else ''}")

        if not pending:
            print("Nada a aplicar — o banco já está na versão mais recente.")
            return 0

        print(f"Migrations pendentes: {len(pending)}")
        for path in pending:
            print(f"  - {path.name}")

        if args.check:
            return 1

        for path in pending:
            print(f"Aplicando {path.name} ...", end=" ", flush=True)
            try:
                conn.executescript(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations (filename, applied_at) VALUES (?, ?)",
                    (path.name, _now()),
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                print("FALHOU")
                sys.exit(f"Erro em {path.name}: {exc}")
            print("ok")

        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        print(f"\nConcluído. Tabelas no banco ({len(tables)}): {', '.join(tables)}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
