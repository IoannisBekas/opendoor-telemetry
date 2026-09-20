"""PostgreSQL helpers: connection, bulk upsert, run bookkeeping."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import psycopg
from psycopg import sql

from .config import ROOT, get_settings

log = logging.getLogger(__name__)


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    settings = get_settings()
    conn = psycopg.connect(settings.pg_dsn, autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = od, public")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_schema(conn: psycopg.Connection | None = None) -> None:
    """Run sql/001_schema.sql then sql/002_views.sql."""
    files = sorted((ROOT / "sql").glob("*.sql"))
    if not files:
        raise FileNotFoundError(f"no .sql files under {ROOT / 'sql'}")

    def _run(c: psycopg.Connection) -> None:
        for f in files:
            log.info("applying %s", f.name)
            c.execute(Path(f).read_text(encoding="utf-8"))

    if conn is not None:
        _run(conn)
    else:
        with connect() as c:
            _run(c)


def upsert(
    conn: psycopg.Connection,
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    conflict_keys: Sequence[str],
    *,
    update_on_conflict: bool = True,
    page_size: int = 1000,
) -> int:
    """INSERT ... ON CONFLICT with server-side batching.

    Returns the number of rows sent (not necessarily the number changed).
    """
    rows = list(rows)
    if not rows:
        return 0

    col_idents = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    placeholders = sql.SQL(", ").join(sql.Placeholder() * len(columns))
    conflict_idents = sql.SQL(", ").join(sql.Identifier(c) for c in conflict_keys)

    updatable = [c for c in columns if c not in conflict_keys]
    if update_on_conflict and updatable:
        action = sql.SQL("DO UPDATE SET {}").format(
            sql.SQL(", ").join(
                sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(c)) for c in updatable
            )
        )
    else:
        action = sql.SQL("DO NOTHING")

    stmt = sql.SQL(
        "INSERT INTO {table} ({cols}) VALUES ({vals}) ON CONFLICT ({keys}) {action}"
    ).format(
        table=sql.Identifier(table),
        cols=col_idents,
        vals=placeholders,
        keys=conflict_idents,
        action=action,
    )

    written = 0
    with conn.cursor() as cur:
        for start in range(0, len(rows), page_size):
            chunk = rows[start : start + page_size]
            cur.executemany(stmt, chunk)
            written += len(chunk)
    return written


def record_exception(
    conn: psycopg.Connection,
    source: str,
    *,
    accession: str | None = None,
    context: str | None = None,
    raw_label: str | None = None,
    raw_value: str | None = None,
    reason: str | None = None,
) -> None:
    """Log a parse failure as a row so layout drift is visible, not fatal."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO parse_exceptions "
            "(source, accession, context, raw_label, raw_value, reason) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (source, accession, context, raw_label, raw_value, reason),
        )


@contextmanager
def ingest_run(conn: psycopg.Connection, source: str) -> Iterator[dict[str, Any]]:
    """Bookkeeping wrapper; mutate state['rows'] to record the row count."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingest_runs (source) VALUES (%s) RETURNING id", (source,)
        )
        run_id = cur.fetchone()[0]

    state: dict[str, Any] = {"rows": 0, "detail": None}
    try:
        yield state
    except Exception as exc:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ingest_runs SET finished_at = now(), status = 'FAILED', detail = %s "
                "WHERE id = %s",
                (str(exc)[:2000], run_id),
            )
        conn.commit()
        raise
    else:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ingest_runs SET finished_at = now(), status = 'OK', "
                "rows_written = %s, detail = %s WHERE id = %s",
                (state["rows"], state["detail"], run_id),
            )
