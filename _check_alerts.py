"""실시간 알림 기준 확인용 임시 스크립트."""
from stock_catalyst import db
from stock_catalyst.config import CFG

print("alert_min_importance =", CFG["analysis"]["alert_min_importance"])
conn = db.connect()
print("=== 오늘 수집·분석된 항목 (중요도순) ===")
rows = conn.execute(
    "SELECT importance, alerted, theme, related_stocks, summary, title "
    "FROM items WHERE collected_at >= '2026-07-23' ORDER BY importance DESC, id"
).fetchall()
for r in rows:
    mark = "🔔알림발송" if r["alerted"] else ""
    print(f"imp={r['importance']} {mark} [{r['theme']}] {r['title'][:55]}")
    if r["alerted"]:
        print(f"    요약: {r['summary'][:80]}")
        print(f"    관련주: {r['related_stocks'] or '(없음)'}")
