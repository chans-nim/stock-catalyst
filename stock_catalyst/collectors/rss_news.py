"""언론사 RSS 피드 뉴스 수집기.

네이버 개발자 API 가 정책 변경으로 사용 불가해져,
telenews 프로젝트(CollectRssFeedsUseCase)의 RSS 수집 방식을 이식했다.
- config.yaml 의 news_feeds 목록을 순회하며 RSS 2.0 / Atom 피드를 파싱
- 제목+요약에 news_keywords 가 포함된 기사만 표준 item dict 로 반환
- 피드 하나가 실패해도 나머지 피드는 계속 수집
"""
import html
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

from ..config import CFG

_UA = "Mozilla/5.0 (compatible; StockCatalyst RSS Collector/1.0)"
_TAG_RE = re.compile(r"<[^>]+>")
_XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>")
# 이스케이프 안 된 & 를 &amp; 로 (telenews sanitizeRssXml 축약판)
_BARE_AMP_RE = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#)")


def _clean(text: str | None) -> str:
    """HTML 태그 제거 + 엔티티 디코딩 + 공백 정리."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def _parse_date(text: str | None) -> str:
    """RFC822(RSS pubDate) 또는 ISO8601(Atom) 날짜를 ISO 문자열로. 실패 시 원문 반환."""
    if not text:
        return ""
    try:
        return parsedate_to_datetime(text).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return text.strip()


def _fetch_root(url: str) -> ET.Element:
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
    resp.raise_for_status()
    try:
        return ET.fromstring(resp.content)
    except ET.ParseError:
        # 비표준 XML(이스케이프 안 된 & 등) 보정 후 재시도
        text = _XML_DECL_RE.sub("", resp.text)
        return ET.fromstring(_BARE_AMP_RE.sub("&amp;", text))


def _parse_rss_items(root: ET.Element) -> list[dict]:
    """RSS 2.0 / RDF(RSS 1.0): <item> 구조."""
    items = []
    for node in root.findall(".//{*}item"):
        title = _clean(node.findtext("{*}title"))
        link = (node.findtext("{*}link") or "").strip()
        if not title or not link:
            continue
        items.append({
            "title": title,
            "url": link,
            "body": _clean(node.findtext("{*}description")),
            "published_at": _parse_date(node.findtext("{*}pubDate") or node.findtext("{*}date")),
        })
    return items


def _parse_atom_entries(root: ET.Element) -> list[dict]:
    """Atom: <feed><entry> 구조."""
    items = []
    for node in root.findall(".//{*}entry"):
        title = _clean(node.findtext("{*}title"))
        link = ""
        for link_el in node.findall("{*}link"):
            href = (link_el.get("href") or "").strip()
            if not href:
                continue
            rel = link_el.get("rel") or "alternate"
            if rel == "alternate":
                link = href
                break
            link = link or href
        if not title or not link:
            continue
        body = _clean(node.findtext("{*}summary")) or _clean(node.findtext("{*}content"))
        published = node.findtext("{*}published") or node.findtext("{*}updated")
        items.append({
            "title": title,
            "url": link,
            "body": body,
            "published_at": _parse_date(published),
        })
    return items


def _parse_feed(root: ET.Element) -> list[dict]:
    tag = root.tag.split("}")[-1].lower()
    if tag in ("rss", "rdf"):
        return _parse_rss_items(root)
    if tag == "feed":
        return _parse_atom_entries(root)
    raise RuntimeError(f"지원하지 않는 피드 형식: {root.tag}")


def _matches(text: str, keywords: list) -> bool:
    """키워드 중 하나라도 매칭되면 True. 공백 포함 키워드는 모든 단어가 있어야 매칭.

    키워드 목록이 비어 있으면 전체 수집.
    """
    if not keywords:
        return True
    for kw in keywords:
        tokens = str(kw).split()
        if tokens and all(t in text for t in tokens):
            return True
    return False


def fetch_feeds() -> list[dict]:
    """config.yaml 의 news_feeds 를 수집해 표준 item dict 목록으로 반환."""
    feeds = CFG["collect"].get("news_feeds") or []
    if not feeds:
        raise RuntimeError("config.yaml 에 collect.news_feeds 가 설정되지 않았습니다")

    keywords = CFG["collect"].get("news_keywords") or []
    max_per_feed = int(CFG["collect"].get("news_max_per_feed", 50))

    items: list[dict] = []
    seen: set[str] = set()
    errors: list[str] = []

    for feed in feeds:
        name, url = feed["name"], feed["url"]
        try:
            parsed = _parse_feed(_fetch_root(url))[:max_per_feed]
        except Exception as e:
            errors.append(f"[{name}] {e}")
            continue
        for it in parsed:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            if not _matches(f"{it['title']} {it['body']}", keywords):
                continue
            items.append({
                "source": "news",
                "source_id": it["url"],
                "title": it["title"],
                "body": it["body"],
                "url": it["url"],
                "published_at": it["published_at"],
            })

    if errors:
        print(f"  [rss] 일부 피드 수집 실패: {'; '.join(errors)}", flush=True)
    if errors and not items and len(errors) == len(feeds):
        raise RuntimeError(f"모든 RSS 피드 수집 실패: {'; '.join(errors)}")
    return items
