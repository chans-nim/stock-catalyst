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
    alerted INTEGER DEFAULT 0,
    -- 리포트 노출 추적 (재전송 우선순위 조정용)
    report_count INTEGER DEFAULT 0,
    last_reported_at TEXT DEFAULT '',
    -- bge-m3 임베딩 / 클러스터 / 섹터
    embedding TEXT DEFAULT '',
    cluster_id INTEGER DEFAULT 0,
    sector TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_items_collected ON items(collected_at);
CREATE INDEX IF NOT EXISTS idx_items_analyzed ON items(analyzed);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    alters = []
    if "report_count" not in cols:
        alters.append("ALTER TABLE items ADD COLUMN report_count INTEGER DEFAULT 0")
    if "last_reported_at" not in cols:
        alters.append("ALTER TABLE items ADD COLUMN last_reported_at TEXT DEFAULT ''")
    if "embedding" not in cols:
        alters.append("ALTER TABLE items ADD COLUMN embedding TEXT DEFAULT ''")
    if "cluster_id" not in cols:
        alters.append("ALTER TABLE items ADD COLUMN cluster_id INTEGER DEFAULT 0")
    if "sector" not in cols:
        alters.append("ALTER TABLE items ADD COLUMN sector TEXT DEFAULT ''")
    for sql in alters:
        conn.execute(sql)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_id)")
    conn.commit()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
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


def mark_reported(conn: sqlite3.Connection, item_ids: list[int]) -> None:
    """리포트에 포함된 항목의 노출 횟수·시각을 갱신."""
    if not item_ids:
        return
    now = datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        """UPDATE items
           SET report_count = COALESCE(report_count, 0) + 1,
               last_reported_at = ?
           WHERE id = ?""",
        [(now, i) for i in item_ids],
    )
    conn.commit()


def recent_items(conn: sqlite3.Connection, hours: int) -> list[sqlite3.Row]:
    since = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    return conn.execute(
        """SELECT * FROM items WHERE collected_at >= ? AND analyzed = 1
           ORDER BY importance DESC, id DESC""",
        (since,),
    ).fetchall()


def pending_embeddings(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    """분석은 끝났지만 임베딩이 없는 항목."""
    return conn.execute(
        """SELECT * FROM items
           WHERE analyzed = 1 AND (embedding IS NULL OR embedding = '')
           ORDER BY id DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def items_with_embedding(conn: sqlite3.Connection, since: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM items
           WHERE analyzed = 1 AND embedding != '' AND collected_at >= ?
           ORDER BY id DESC""",
        (since,),
    ).fetchall()


def save_embedding(
    conn: sqlite3.Connection,
    item_id: int,
    embedding_json: str,
    cluster_id: int,
    sector: str,
    theme: str | None = None,
) -> None:
    if theme is not None:
        conn.execute(
            """UPDATE items
               SET embedding=?, cluster_id=?, sector=?, theme=?
               WHERE id=?""",
            (embedding_json, cluster_id, sector, theme, item_id),
        )
    else:
        conn.execute(
            """UPDATE items SET embedding=?, cluster_id=?, sector=? WHERE id=?""",
            (embedding_json, cluster_id, sector, item_id),
        )
    conn.commit()


def cluster_mates(conn: sqlite3.Connection, cluster_id: int, exclude_id: int = 0) -> list[sqlite3.Row]:
    if not cluster_id:
        return []
    return conn.execute(
        """SELECT * FROM items
           WHERE cluster_id = ? AND id != ? AND analyzed = 1
           ORDER BY importance DESC, id DESC""",
        (cluster_id, exclude_id),
    ).fetchall()
