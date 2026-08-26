"""bge-m3 임베딩 기반 기사 그룹화(클러스터) + 섹터 분류."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .config import CFG
from . import db, embedding


def _cfg() -> dict:
    return CFG.get("embedding") or {}


def _parse_vec(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            return [float(x) for x in data]
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


def process_pending(conn, limit: int = 50) -> dict:
    """분석 완료·미임베딩 항목에 벡터·섹터·클러스터를 부여. 처리 통계 반환."""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return {"embedded": 0, "clustered": 0}

    rows = db.pending_embeddings(conn, limit=limit)
    if not rows:
        return {"embedded": 0, "clustered": 0}

    threshold = float(cfg.get("similarity_threshold", 0.62))
    lookback_h = int(cfg.get("cluster_lookback_hours", 48))
    since = (datetime.now() - timedelta(hours=lookback_h)).isoformat(timespec="seconds")

    # 기존 클러스터 후보 (벡터 있는 최근 기사)
    pool = db.items_with_embedding(conn, since=since)
    pool_vecs: list[tuple[int, int, list[float]]] = []  # id, cluster_id, vec
    for r in pool:
        vec = _parse_vec(r["embedding"])
        if not vec:
            continue
        cid = int(r["cluster_id"] or r["id"])
        pool_vecs.append((int(r["id"]), cid, vec))

    embedded = 0
    clustered = 0
    batch_size = int(cfg.get("batch_size", 8))

    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        texts = [embedding.item_text(r) for r in chunk]
        vectors = embedding.embed(texts)

        for row, vec in zip(chunk, vectors):
            sector, sector_sim = embedding.classify_sector(vec)

            # 최근 풀에서 가장 유사한 클러스터에 편입
            best_cid, best_sim = int(row["id"]), -1.0
            for _oid, cid, pvec in pool_vecs:
                sim = embedding.cosine(vec, pvec)
                if sim > best_sim:
                    best_sim, best_cid = sim, cid
            if best_sim < threshold:
                best_cid = int(row["id"])  # 신규 클러스터

            # LLM theme 이 기타/비어 있으면 섹터로 보강
            theme = (row["theme"] or "").strip()
            if not theme or theme == "기타":
                theme = sector

            db.save_embedding(
                conn,
                item_id=int(row["id"]),
                embedding_json=json.dumps(vec),
                cluster_id=best_cid,
                sector=sector,
                theme=theme,
            )
            pool_vecs.append((int(row["id"]), best_cid, vec))
            embedded += 1
            clustered += 1

    return {"embedded": embedded, "clustered": clustered, "sector_samples": None}
