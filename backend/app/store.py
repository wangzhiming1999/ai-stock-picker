"""SQLite 存储：保存分析批次与单股结果，提供历史查询。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from app.config import get_settings


def _db_path() -> Path:
    p = Path(get_settings().database_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _cursor() -> Iterator[sqlite3.Connection]:
    conn = _conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """初始化表结构。"""
    with _cursor() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS analysis_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                codes TEXT NOT NULL,           -- 逗号分隔
                mode TEXT NOT NULL,            -- llm / mock
                total INTEGER NOT NULL DEFAULT 0,
                avg_score REAL
            );
            CREATE TABLE IF NOT EXISTS analysis_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL REFERENCES analysis_batches(id) ON DELETE CASCADE,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                overall_score REAL NOT NULL,
                summary TEXT,
                dimensions TEXT NOT NULL,      -- JSON
                risks TEXT NOT NULL,           -- JSON
                suggestions TEXT NOT NULL      -- JSON
            );
            CREATE INDEX IF NOT EXISTS idx_results_batch ON analysis_results(batch_id);
            CREATE INDEX IF NOT EXISTS idx_batches_created ON analysis_batches(created_at);
            """
        )


def save_batch(codes: list[str], mode: str, results: list[dict]) -> int:
    """保存一批分析结果，返回 batch_id。"""
    init_db()
    avg = round(sum(r["overall_score"] for r in results) / len(results), 2) if results else None
    with _cursor() as conn:
        cur = conn.execute(
            "INSERT INTO analysis_batches (created_at, codes, mode, total, avg_score) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), ",".join(codes), mode, len(results), avg),
        )
        batch_id = cur.lastrowid
        for r in results:
            conn.execute(
                "INSERT INTO analysis_results (batch_id, code, name, overall_score, summary, dimensions, risks, suggestions) VALUES (?,?,?,?,?,?,?,?)",
                (
                    batch_id,
                    r["code"],
                    r["name"],
                    r["overall_score"],
                    r["summary"],
                    json.dumps(r.get("dimensions", []), ensure_ascii=False),
                    json.dumps(r.get("risks", []), ensure_ascii=False),
                    json.dumps(r.get("suggestions", []), ensure_ascii=False),
                ),
            )
        return batch_id


def list_batches(limit: int = 20) -> list[dict]:
    """列出最近的分析批次。"""
    init_db()
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT * FROM analysis_batches ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_batch(batch_id: int) -> dict | None:
    """查询批次及全部结果。"""
    init_db()
    with _cursor() as conn:
        row = conn.execute("SELECT * FROM analysis_batches WHERE id = ?", (batch_id,)).fetchone()
        if not row:
            return None
        batch = dict(row)
        results = conn.execute(
            "SELECT * FROM analysis_results WHERE batch_id = ? ORDER BY overall_score DESC", (batch_id,)
        ).fetchall()
        batch["results"] = [_row_to_result(r) for r in results]
        return batch


def _row_to_result(row: sqlite3.Row) -> dict:
    d = dict(row)
    for field in ("dimensions", "risks", "suggestions"):
        try:
            d[field] = json.loads(d[field])
        except (json.JSONDecodeError, TypeError):
            d[field] = []
    return d
