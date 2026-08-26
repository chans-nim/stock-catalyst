"""수집 항목을 요약·테마 분류·중요도 평가한다.

telenews 와 같이 온디바이스 AI(Ollama 로컬 LLM)를 기본으로 사용하고,
config.yaml 의 analysis.provider 로 openai 전환도 가능하다.
- Ollama: POST {base_url}/api/chat, format=json (무료, 로컬)
- OpenAI: chat.completions (API 키 필요)
"""
import json
import re

import requests

from .config import CFG, OPENAI_API_KEY
from . import db

_SYSTEM_PROMPT = """당신은 한국 주식 시장의 재료(주가를 움직이는 뉴스·공시·이벤트) 분석가입니다.
입력으로 뉴스 기사 또는 DART 공시 목록이 JSON 배열로 주어집니다.
각 항목을 평가해 반드시 {"items": [...]} 형태의 JSON 으로만 응답하세요.

items 배열의 각 항목 형식:
{
  "id": <입력의 id 그대로>,
  "summary": "<핵심 재료를 1문장으로 요약>",
  "theme": "<테마/섹터 한 단어~두 단어 (예: 2차전지, 방산, AI반도체, 바이오, 정책수혜). 해당 없으면 '기타'>",
  "related_stocks": "<직접 관련 종목명들, 쉼표 구분. 없으면 빈 문자열>",
  "importance": <1~5 정수>
}

related_stocks 규칙 (매우 중요):
- title, body, corp_name 에 실제로 등장한 종목명만 적으세요.
- 추측·연상으로 채우지 마세요. 특히 삼성전자, SK하이닉스를 기본값처럼 넣지 마세요.
- 기사 주체가 "삼성물산"이면 삼성물산만, "큐리언트"이면 큐리언트만 적으세요.
- 공시(source=dart)는 corp_name 을 최우선으로 사용하세요.
- 확실하지 않으면 빈 문자열 "" 을 사용하세요.

importance 기준:
5 = 주가에 즉각적·확실한 영향 (대규모 수주/공급계약, 임상 성공/승인, 무상증자, M&A, 상한가급 재료)
4 = 강한 재료 (정책 수혜 구체화, 대형 고객사 확보, 호실적 서프라이즈)
3 = 참고할 만한 재료 (업황 개선, 신제품, 소규모 계약)
2 = 약한 재료 (일반 업계 동향)
1 = 재료 아님 (단순 시황, 광고성, 정기 보고서)"""

# 제목 앞쪽 "종목명," / "[특징주] 종목명," 패턴
_TITLE_STOCK_RE = re.compile(
    r"^(?:\[[^\]]+\]\s*)?([가-힣A-Za-z0-9＆&·\-]{2,20})\s*[,，]"
)


def _chat_ollama(user_content: str) -> str:
    """Ollama Chat API 호출 (telenews OllamaChatClient 방식)."""
    cfg = CFG["analysis"].get("ollama") or {}
    base_url = str(cfg.get("base_url", "http://localhost:11434")).rstrip("/")
    body = {
        "model": cfg.get("model", "qwen2.5:3b"),
        "stream": False,
        "format": "json",
        # 모델을 메모리에 상주시켜 다음 배치 응답 속도 확보
        "keep_alive": "30m",
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "options": {
            "temperature": 0.2,
            "num_predict": 2000,
            "num_ctx": 8192,
        },
    }
    try:
        resp = requests.post(
            f"{base_url}/api/chat", json=body,
            timeout=int(cfg.get("timeout_sec", 180)),
        )
    except requests.ConnectionError as e:
        raise RuntimeError(
            f"Ollama 서버({base_url})에 연결할 수 없습니다. "
            "`ollama serve` 실행 여부를 확인하세요."
        ) from e
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _chat_openai(user_content: str) -> str:
    from openai import OpenAI

    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY 가 설정되지 않았습니다 (.env 확인)")
    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=CFG["analysis"]["openai_model"],
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


def _batch_size(provider: str) -> int:
    """provider 별 배치 크기 (로컬 소형 모델은 작은 배치가 안정적)."""
    if provider == "ollama":
        return int((CFG["analysis"].get("ollama") or {}).get("batch_size", 5))
    return 20


def _filter_related_stocks(
    raw: str, title: str, body: str, corp_name: str
) -> str:
    """모델이 지어낸 관련주를 제거하고, 원문에 등장한 종목만 남긴다."""
    context = f"{title} {body} {corp_name}"
    kept: list[str] = []

    for name in re.split(r"[,，/·|]", str(raw or "")):
        name = name.strip()
        if len(name) < 2:
            continue
        if name in context:
            kept.append(name)
        elif corp_name and (name in corp_name or corp_name in name):
            kept.append(corp_name)

    # DART 등 corp_name 이 있으면 최소 보장
    if not kept and corp_name:
        kept.append(corp_name)

    # 제목 선두 종목명 패턴 보완 (예: "삼성물산, …", "큐리언트, …")
    if not kept:
        m = _TITLE_STOCK_RE.match(title or "")
        if m:
            candidate = m.group(1).strip()
            # 시황성 단어는 종목으로 보지 않음
            if candidate not in {"뉴욕증시", "코스피", "코스닥", "아시아", "유럽", "미", "美", "日", "中"}:
                kept.append(candidate)

    # 순서 유지 중복 제거
    return ", ".join(dict.fromkeys(kept))


def analyze_pending(conn, batch_size: int | None = None) -> int:
    """미분석 항목을 배치로 분석해 DB에 저장하고 처리 건수를 반환."""
    provider = str(CFG["analysis"].get("provider", "ollama")).lower()
    if batch_size is None:
        batch_size = _batch_size(provider)

    rows = db.unanalyzed(conn, limit=batch_size)
    if not rows:
        return 0

    payload = [
        {
            "id": r["id"],
            "source": r["source"],
            "title": r["title"],
            "body": r["body"][:300],
            "corp_name": r["corp_name"],
        }
        for r in rows
    ]

    chat = _chat_ollama if provider == "ollama" else _chat_openai
    content = chat(json.dumps(payload, ensure_ascii=False))
    parsed = json.loads(content)
    # 모델이 {"items": [...]} 또는 [...] 형태로 줄 수 있음
    results = parsed if isinstance(parsed, list) else next(
        (v for v in parsed.values() if isinstance(v, list)), []
    )

    by_id = {r["id"]: r for r in rows}
    count = 0
    for res in results:
        if not isinstance(res, dict):
            continue
        row = by_id.get(res.get("id"))
        if row is None:
            continue
        try:
            importance = max(1, min(5, int(res.get("importance", 1))))
        except (TypeError, ValueError):
            importance = 1
        related = _filter_related_stocks(
            str(res.get("related_stocks", "")),
            title=row["title"] or "",
            body=row["body"] or "",
            corp_name=row["corp_name"] or "",
        )
        db.save_analysis(
            conn,
            item_id=row["id"],
            summary=str(res.get("summary", ""))[:500],
            theme=str(res.get("theme", "기타")),
            related_stocks=related,
            importance=importance,
        )
        count += 1

    # 응답에서 누락된 항목은 재시도 루프에 빠지지 않도록 최저 중요도로 마감
    answered = {res.get("id") for res in results if isinstance(res, dict)}
    for row in rows:
        if row["id"] not in answered:
            db.save_analysis(conn, row["id"], "", "기타", "", 1)
    return count
