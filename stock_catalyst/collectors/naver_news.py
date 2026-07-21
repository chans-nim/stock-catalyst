"""네이버 뉴스 검색 API 수집기."""
import html
import re

import requests

from ..config import CFG, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

SEARCH_URL = "https://openapi.naver.com/v1/search/news.json"
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text)).strip()


def fetch_keywords() -> list[dict]:
    """config.yaml 의 news_keywords 로 최신 기사를 검색해 표준 item dict 목록으로 반환."""
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET):
        raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 설정되지 않았습니다 (.env 확인)")

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    display = int(CFG["collect"].get("news_display", 30))
    items: list[dict] = []
    for keyword in CFG["collect"]["news_keywords"]:
        resp = requests.get(SEARCH_URL, headers=headers, params={
            "query": keyword,
            "display": display,
            "sort": "date",
        }, timeout=15)
        resp.raise_for_status()
        for a in resp.json().get("items", []):
            url = a.get("originallink") or a["link"]
            items.append({
                "source": "news",
                "source_id": url,
                "title": _clean(a["title"]),
                "body": _clean(a.get("description", "")),
                "url": url,
                "published_at": a.get("pubDate", ""),
            })
    return items
