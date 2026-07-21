"""OpenAI 로 수집 항목을 요약·테마 분류·중요도 평가한다."""
import json

from openai import OpenAI

from .config import CFG, OPENAI_API_KEY
from . import db

_SYSTEM_PROMPT = """당신은 한국 주식 시장의 재료(주가를 움직이는 뉴스·공시·이벤트) 분석가입니다.
입력으로 뉴스 기사 또는 DART 공시 목록이 JSON 배열로 주어집니다.
각 항목에 대해 다음을 평가해 JSON 배열로만 응답하세요.

각 항목 형식:
{
  "id": <입력의 id 그대로>,
  "summary": "<핵심 재료를 1문장으로 요약>",
  "theme": "<테마/섹터 한 단어~두 단어 (예: 2차전지, 방산, AI반도체, 바이오, 정책수혜). 해당 없으면 '기타'>",
  "related_stocks": "<직접 관련 종목명들, 쉼표 구분. 없으면 빈 문자열>",
  "importance": <1~5 정수>
}

importance 기준:
5 = 주가에 즉각적·확실한 영향 (대규모 수주/공급계약, 임상 성공/승인, 무상증자, M&A, 상한가급 재료)
4 = 강한 재료 (정책 수혜 구체화, 대형 고객사 확보, 호실적 서프라이즈)
3 = 참고할 만한 재료 (업황 개선, 신제품, 소규모 계약)
2 = 약한 재료 (일반 업계 동향)
1 = 재료 아님 (단순 시황, 광고성, 정기 보고서)"""


def _client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY 가 설정되지 않았습니다 (.env 확인)")
    return OpenAI(api_key=OPENAI_API_KEY)


def analyze_pending(conn, batch_size: int = 20) -> int:
    """미분석 항목을 배치로 분석해 DB에 저장하고 처리 건수를 반환."""
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

    client = _client()
    resp = client.chat.completions.create(
        model=CFG["analysis"]["openai_model"],
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content
    parsed = json.loads(content)
    # 모델이 {"items": [...]} 또는 [...] 형태로 줄 수 있음
    results = parsed if isinstance(parsed, list) else next(
        (v for v in parsed.values() if isinstance(v, list)), []
    )

    by_id = {r["id"]: r for r in rows}
    count = 0
    for res in results:
        row = by_id.get(res.get("id"))
        if row is None:
            continue
        db.save_analysis(
            conn,
            item_id=row["id"],
            summary=str(res.get("summary", ""))[:500],
            theme=str(res.get("theme", "기타")),
            related_stocks=str(res.get("related_stocks", "")),
            importance=max(1, min(5, int(res.get("importance", 1)))),
        )
        count += 1

    # 응답에서 누락된 항목은 재시도 루프에 빠지지 않도록 최저 중요도로 마감
    for row in rows:
        if row["id"] not in {res.get("id") for res in results}:
            db.save_analysis(conn, row["id"], "", "기타", "", 1)
    return count
