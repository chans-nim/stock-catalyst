"""재료 리포트: 미전송 ★N+ 만 발송. 같은 종목의 기전송 기사는 연관 기사로 표시."""
import html
import re
from datetime import datetime

from .config import CFG
from . import db
from .notify import escape

_DEFAULT_MAX_CHARS = 4000
_DEFAULT_MIN_IMPORTANCE = 3
_DEFAULT_RELATED_LIMIT = 3


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+0000")
    if len(text) >= 6 and text[-3] == ":":
        text = text[:-3] + text[-2:]
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _fmt_time(value: str | None) -> str:
    dt = _parse_time(value)
    if dt:
        return dt.strftime("%m-%d %H:%M")
    return (value or "")[:16]


def _cfg() -> dict:
    return CFG.get("report") or {}


def _stocks(r) -> set[str]:
    """관련주 + 공시 법인명에서 종목명 집합 추출."""
    names: set[str] = set()
    for part in re.split(r"[,，/·|]", r["related_stocks"] or ""):
        name = part.strip()
        if len(name) >= 2:
            names.add(name)
    corp = (r["corp_name"] or "").strip()
    if len(corp) >= 2:
        names.add(corp)
    return names


def _sort_key(r):
    """중요도 높은 순 → 최신 순."""
    dt = _naive(_parse_time(r["published_at"] or r["collected_at"]))
    return (int(r["importance"] or 0), dt or datetime.min)


def _fresh_candidates(conn, hours: int, min_imp: int) -> list:
    """아직 리포트에 넣지 않은(report_count=0) ★min+ 기사만."""
    rows = [
        r for r in db.recent_items(conn, hours=hours)
        if int(r["importance"] or 0) >= min_imp
        and int(r["report_count"] or 0) == 0
    ]
    rows.sort(key=_sort_key, reverse=True)
    return rows


def _reported_pool(conn, hours: int) -> list:
    """이미 전송된 기사 (연관 기사 매칭용). lookback 범위 내."""
    return [
        r for r in db.recent_items(conn, hours=hours)
        if int(r["report_count"] or 0) > 0
    ]


def _related_for(item, reported: list, limit: int) -> list:
    """동일 종목 또는 동일 클러스터(bge-m3)의 기전송 기사를 우선순위로 최대 limit건."""
    mine = _stocks(item)
    my_cluster = int(item["cluster_id"] or 0) if "cluster_id" in item.keys() else 0
    scored: list[tuple[int, object]] = []
    for r in reported:
        if int(r["id"]) == int(item["id"]):
            continue
        other = _stocks(r)
        same_stock = bool(mine & other)
        same_cluster = bool(
            my_cluster
            and "cluster_id" in r.keys()
            and int(r["cluster_id"] or 0) == my_cluster
        )
        if not (same_stock or same_cluster):
            continue
        # 종목+클러스터 모두 일치하면 우선
        priority = (2 if same_stock and same_cluster else 1 if same_stock else 0)
        scored.append((priority, r))
    scored.sort(key=lambda x: (x[0],) + _sort_key(x[1]), reverse=True)
    return [r for _, r in scored[:limit]]


def has_sendable(conn) -> bool:
    """미전송 ★min+ 기사가 있으면 True."""
    cfg = _cfg()
    hours = int(cfg.get("lookback_hours", CFG["briefing"].get("lookback_hours", 18)))
    min_imp = int(cfg.get("min_importance", _DEFAULT_MIN_IMPORTANCE))
    return bool(_fresh_candidates(conn, hours, min_imp))


def _item_block(r, related: list | None = None) -> str:
    stars = "★" * int(r["importance"] or 0) or "☆"
    sector = ""
    if "sector" in r.keys() and r["sector"]:
        sector = r["sector"]
    theme = escape(sector or r["theme"] or "기타")
    summary = escape((r["summary"] or r["title"] or "").strip())
    src = "공시" if r["source"] == "dart" else "뉴스"
    lines = [f"{stars} <b>[{theme}]</b> {summary}"]
    if r["title"] and r["summary"] and r["title"] != r["summary"]:
        lines.append(f"  · {escape(r['title'][:80])}")
    if r["related_stocks"]:
        lines.append(f"  관련주: {escape(r['related_stocks'])}")
    if r["corp_name"]:
        lines.append(f"  기업: {escape(r['corp_name'])}")
    when = _fmt_time(r["published_at"] or r["collected_at"])
    rest = " · ".join(p for p in [when, f"중요도 {r['importance']}"] if p)
    if r["url"]:
        href = html.escape(r["url"], quote=True)
        lines.append(f'  (<a href="{href}">{src}</a> · {rest})')
    else:
        lines.append(f"  ({src} · {rest})")

    if related:
        lines.append("  📎 <b>연관 기사</b> (동일 종목·클러스터)")
        for rel in related:
            r_stars = "★" * int(rel["importance"] or 0) or "☆"
            r_sum = escape((rel["summary"] or rel["title"] or "").strip()[:80])
            r_when = _fmt_time(rel["published_at"] or rel["collected_at"])
            shared = sorted(_stocks(r) & _stocks(rel))
            tags = []
            if shared:
                tags.append(", ".join(shared))
            if (
                "cluster_id" in r.keys()
                and "cluster_id" in rel.keys()
                and int(r["cluster_id"] or 0)
                and int(r["cluster_id"] or 0) == int(rel["cluster_id"] or 0)
            ):
                tags.append("유사그룹")
            tag_txt = f" · {' · '.join(tags)}" if tags else ""
            if rel["url"]:
                href = html.escape(rel["url"], quote=True)
                lines.append(
                    f'    - {r_stars} <a href="{href}">{r_sum}</a>'
                    f" ({r_when}{tag_txt})"
                )
            else:
                lines.append(f"    - {r_stars} {r_sum} ({r_when}{tag_txt})")
    return "\n".join(lines)


def build(conn, hours: int | None = None) -> tuple[str, list[int]]:
    """미전송 기사만 리포트. 동일 종목 기전송분은 연관 기사로 첨부."""
    cfg = _cfg()
    if hours is None:
        hours = int(cfg.get("lookback_hours", CFG["briefing"].get("lookback_hours", 18)))
    min_imp = int(cfg.get("min_importance", _DEFAULT_MIN_IMPORTANCE))
    max_chars = int(cfg.get("max_chars", _DEFAULT_MAX_CHARS))
    related_limit = int(cfg.get("related_limit", _DEFAULT_RELATED_LIMIT))
    # 연관 기사 검색 범위 (기본은 리포트 lookback 과 동일, 더 길게 가능)
    related_hours = int(cfg.get("related_lookback_hours", hours))

    fresh = _fresh_candidates(conn, hours, min_imp)
    reported = _reported_pool(conn, related_hours)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    header_lines = [
        f"📋 <b>재료 리포트 — {now}</b>",
        f"최근 {hours}시간 · ★{min_imp}+ · 미전송 {len(fresh)}건",
        "",
    ]
    if not fresh:
        header_lines.append("새로 보낼 기사가 없습니다.")
        return "\n".join(header_lines), []

    dist: dict[int, int] = {}
    for r in fresh:
        dist[r["importance"]] = dist.get(r["importance"], 0) + 1
    dist_text = " · ".join(
        f"{'★' * k}{k}:{dist[k]}" for k in sorted(dist.keys(), reverse=True)
    )
    header_lines.append(f"<i>{dist_text}</i>")
    header_lines.append("")
    header = "\n".join(header_lines)

    body_parts: list[str] = []
    included_ids: list[int] = []
    omitted_note = ""
    for r in fresh:
        related = _related_for(r, reported, related_limit)
        block = _item_block(r, related)
        candidate = header + "\n".join(body_parts + [block, ""])
        rest_count = len(fresh) - len(included_ids) - 1
        reserve = 40 if rest_count > 0 else 0
        if len(candidate.rstrip()) + reserve > max_chars:
            omitted = len(fresh) - len(included_ids)
            if omitted > 0:
                omitted_note = f"\n…외 {omitted}건 생략 (한도 {max_chars}자)"
            break
        body_parts.append(block)
        body_parts.append("")
        included_ids.append(int(r["id"]))

    text = (header + "\n".join(body_parts)).rstrip() + omitted_note
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0]
    return text, included_ids
