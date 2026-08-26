"""Ollama bge-m3 임베딩 (telenews OllamaEmbeddingAdapter 방식).

POST {base_url}/api/embed
요청: {"model": "bge-m3", "input": ["..."]}
응답: {"embeddings": [[...]]}  — 기본 1024차원
"""
from __future__ import annotations

import math

import requests

from .config import CFG

_SECTOR_PROTOTYPES: dict[str, str] = {
    "반도체": "반도체 메모리 파운드리 HBM AI칩 웨이퍼 하이닉스 엔비디아 MLCC 전자부품 패키징",
    "2차전지": "2차전지 배터리 전기차 양극재 음극재 분리막 리튬 ESS",
    "바이오": "바이오 제약 임상 신약 ADC 세포치료 의료기기 승인 티슈진",
    "방산": "방산 무기 항공우주 방위산업 무기수출 국방",
    "원전": "원자력 원전 SMR 원전수출 소형모듈원전",
    "자동차": "자동차 전기차 완성차 부품 모빌리티",
    "금융": "은행 증권 보험 금리 금융지주 증시 공모 유상증자 전환사채 증권신고서",
    "조선": "조선 선박 LNG선 수주 해양플랜트",
    "건설": "건설 해외건설 부동산 인프라 수주 시멘트 아파트",
    "IT소프트웨어": "클라우드 소프트웨어 SaaS AI서비스 플랫폼 게임 앱",
    "디스플레이": "디스플레이 OLED LCD 패널",
    "에너지화학": "석유화학 정유 수소 신재생에너지 태양광",
    "정책수혜": "정부 정책 지원금 규제 법안 산업정책 수혜주",
    "기타": "일반 시황 경제 동향",
}

_sector_vecs: dict[str, list[float]] | None = None


def _cfg() -> dict:
    return (CFG.get("embedding") or {})


def embed(texts: list[str] | str) -> list[list[float]]:
    """텍스트(들)를 bge-m3 벡터로 변환."""
    cfg = _cfg()
    if isinstance(texts, str):
        texts = [texts]
    inputs = [t if t and t.strip() else "(empty)" for t in texts]
    base = str(cfg.get("base_url", "http://localhost:11434")).rstrip("/")
    model = cfg.get("model", "bge-m3")
    timeout = int(cfg.get("timeout_sec", 60))
    retries = int(cfg.get("max_retries", 2))

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{base}/api/embed",
                json={"model": model, "input": inputs},
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            vectors = data.get("embeddings")
            if not vectors:
                raise RuntimeError(f"임베딩 응답에 embeddings 없음: {data}")
            return [[float(x) for x in v] for v in vectors]
        except Exception as e:
            last_err = e
            if attempt < retries:
                continue
    raise RuntimeError(f"Ollama 임베딩 실패 (model={model}): {last_err}") from last_err


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def sector_prototypes() -> dict[str, list[float]]:
    """섹터 프로토타입 벡터 (프로세스 내 캐시)."""
    global _sector_vecs
    if _sector_vecs is not None:
        return _sector_vecs
    labels = list(_SECTOR_PROTOTYPES.keys())
    texts = [_SECTOR_PROTOTYPES[k] for k in labels]
    vectors = embed(texts)
    _sector_vecs = dict(zip(labels, vectors))
    return _sector_vecs


def classify_sector(vec: list[float]) -> tuple[str, float]:
    """가장 가까운 섹터와 유사도 반환."""
    best_name, best_sim = "기타", -1.0
    for name, proto in sector_prototypes().items():
        if name == "기타":
            continue
        sim = cosine(vec, proto)
        if sim > best_sim:
            best_name, best_sim = name, sim
    min_sim = float(_cfg().get("sector_min_similarity", 0.35))
    if best_sim < min_sim:
        return "기타", best_sim
    return best_name, best_sim


def item_text(row) -> str:
    """임베딩용 텍스트 (제목 + 요약/본문)."""
    title = (row["title"] or "").strip()
    body = (row["summary"] or row["body"] or "").strip()[:400]
    corp = (row["corp_name"] or "").strip()
    parts = [p for p in (title, body, corp) if p]
    return " ".join(parts)
