"""SQLite 저장 레이어. 모든 수집 항목(공시/뉴스)을 items 테이블 하나로 통합 관리한다."""
import sqlite3
from datetime import datetime, timedelta

from .config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,            -- 'dart' | 'news'
    source_id TEXT NOT NULL UNIQUE,  -- dart: rcept_no, news: 기사 URL
    title TEXT NOT NULL,
    body TEXT DEFAULT '',
    url TEXT DEFAULT '',
    corp_name TEXT DEFAULT '',       -- dart 공시 제출 법인
    stock_code TEXT DEFAULT '',
    published_at TEXT DEFAULT '',
    collected_at TEXT NOT NULL,
    -- 분석 결과
    analyzed INTEGER DEFAULT 0,
    summary TEXT DEFAULT '',
    theme TEXT DEFAULT '',
    related_stocks TEXT DEFAULT '',  -- 쉼표 구분 종목명 목록
    importance INTEGER DEFAULT 0,    -- 1~5
    alerted INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_collected ON items(collected_at);
CREATE INDEX IF NOT EXISTS idx_items_analyzed ON items(analyzed);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def insert_items(conn: sqlite3.Connection, items: list[dict]) -> int:
    """중복(source_id)은 무시하고 새로 들어온 건수를 반환."""
    now = datetime.now().isoformat(timespec="seconds")
    inserted = 0
    for it in items:
        cur = conn.execute(
            """INSERT OR IGNORE INTO items
               (source, source_id, title, body, url, corp_name, stock_code, published_at, collected_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                it["source"], it["source_id"], it["title"], it.get("body", ""),
                it.get("url", ""), it.get("corp_name", ""), it.get("stock_code", ""),
                it.get("published_at", ""), now,
            ),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


def unanalyzed(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM items WHERE analyzed = 0 ORDER BY id LIMIT ?", (limit,)
    ).fetchall()


def save_analysis(conn: sqlite3.Connection, item_id: int, summary: str,
                  theme: str, related_stocks: str, importance: int) -> None:
    conn.execute(
        """UPDATE items SET analyzed=1, summary=?, theme=?, related_stocks=?, importance=?
           WHERE id=?""",
        (summary, theme, related_stocks, importance, item_id),
    )
    conn.commit()


def pending_alerts(conn: sqlite3.Connection, min_importance: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM items WHERE analyzed=1 AND alerted=0 AND importance>=? ORDER BY id",
        (min_importance,),
    ).fetchall()


def mark_alerted(conn: sqlite3.Connection, item_ids: list[int]) -> None:
    conn.executemany("UPDATE items SET alerted=1 WHERE id=?", [(i,) for i in item_ids])
    conn.commit()


def recent_items(conn: sqlite3.Connection, hours: int) -> list[sqlite3.Row]:
    since = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    return conn.execute(
        """SELECT * FROM items WHERE collected_at >= ? AND analyzed = 1
           ORDER BY importance DESC, id DESC""",
        (since,),
    ).fetchall()
