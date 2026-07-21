"""DART 전자공시 수집기 (Open API 공시검색)."""
from datetime import datetime

import requests

from ..config import CFG, DART_API_KEY

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def fetch_today() -> list[dict]:
    """오늘 접수된 전체 공시 목록을 가져와 표준 item dict 목록으로 반환."""
    if not DART_API_KEY:
        raise RuntimeError("DART_API_KEY 가 설정되지 않았습니다 (.env 확인)")

    today = datetime.now().strftime("%Y%m%d")
    exclude = CFG["collect"].get("dart_exclude") or []
    items: list[dict] = []
    page = 1
    while True:
        resp = requests.get(LIST_URL, params={
            "crtfc_key": DART_API_KEY,
            "bgn_de": today,
            "end_de": today,
            "page_no": page,
            "page_count": 100,
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "013":  # 조회 결과 없음
            break
        if data.get("status") != "000":
            raise RuntimeError(f"DART API 오류 {data.get('status')}: {data.get('message')}")

        for d in data.get("list", []):
            title = d["report_nm"].strip()
            if any(kw in title for kw in exclude):
                continue
            items.append({
                "source": "dart",
                "source_id": d["rcept_no"],
                "title": title,
                "corp_name": d["corp_name"],
                "stock_code": d.get("stock_code") or "",
                "url": VIEWER_URL.format(rcept_no=d["rcept_no"]),
                "published_at": d["rcept_dt"],
            })

        if page >= int(data.get("total_page", 1)):
            break
        page += 1
    return items
