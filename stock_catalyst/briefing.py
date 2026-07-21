"""아침 브리핑 생성: 최근 수집된 재료를 테마별로 정리하고 관심 종목 시세를 붙인다."""
from collections import defaultdict
from datetime import datetime

from .config import CFG
from . import db
from .collectors import kis

_STOCK_NAMES = {}  # 코드 -> 이름 (브리핑 표기용, DART corp 매칭으로 채워짐)


def build(conn) -> str:
    hours = int(CFG["briefing"].get("lookback_hours", 18))
    rows = db.recent_items(conn, hours=hours)
    today = datetime.now().strftime("%Y-%m-%d (%a)")

    lines = [f"☀️ <b>아침 재료 브리핑 — {today}</b>", ""]

    # 관심 종목 시세
    watchlist = CFG.get("watchlist") or []
    if watchlist:
        lines.append("<b>📊 관심 종목</b>")
        for q in kis.fetch_watchlist([str(c) for c in watchlist]):
            if "error" in q:
                lines.append(f"  {q['code']}: 조회 실패 ({q['error'][:60]})")
            else:
                arrow = "🔺" if q["change_rate"] > 0 else ("🔻" if q["change_rate"] < 0 else "▪️")
                lines.append(f"  {q['code']}: {q['price']:,}원 {arrow}{abs(q['change_rate'])}%")
        lines.append("")

    if not rows:
        lines.append(f"최근 {hours}시간 수집된 재료가 없습니다.")
        return "\n".join(lines)

    # 중요 재료 TOP (중요도 4 이상)
    top = [r for r in rows if r["importance"] >= 4][:10]
    if top:
        lines.append("<b>🔥 핵심 재료</b>")
        for r in top:
            stars = "★" * r["importance"]
            title = r["summary"] or r["title"]
            lines.append(f"  {stars} [{r['theme']}] {title}")
            if r["related_stocks"]:
                lines.append(f"      관련주: {r['related_stocks']}")
        lines.append("")

    # 테마별 집계 (재료 아님(1) 제외)
    by_theme: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["importance"] >= 2:
            by_theme[r["theme"]].append(r)

    if by_theme:
        lines.append("<b>🗂 테마별 동향</b>")
        ranked = sorted(by_theme.items(), key=lambda kv: -len(kv[1]))
        for theme, theme_rows in ranked[:8]:
            if theme == "기타":
                continue
            lines.append(f"  ▪ {theme} ({len(theme_rows)}건)")
            for r in theme_rows[:3]:
                lines.append(f"     - {r['summary'] or r['title']}")
        lines.append("")

    lines.append(f"수집: 최근 {hours}시간, 총 {len(rows)}건 분석")
    return "\n".join(lines)
