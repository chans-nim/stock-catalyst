"""stock-catalyst CLI.

사용법:
  python main.py collect   # 1회 수집 + 분석 + 중요 재료 텔레그램 알림
  python main.py watch     # 상시 실행: 주기 수집 + 실시간 알림 + 아침 브리핑 자동 발송
  python main.py brief     # 아침 브리핑 즉시 생성·발송
  python main.py status    # DB 수집 현황 출력
"""
import sys
import time
import traceback
from datetime import datetime, date

from stock_catalyst.config import CFG
from stock_catalyst import db, analysis, notify, briefing
from stock_catalyst.collectors import dart, naver_news


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def collect_once(conn) -> None:
    """수집 -> 분석 -> 알림 1사이클."""
    new_count = 0
    for name, fetch in (("DART", dart.fetch_today), ("네이버뉴스", naver_news.fetch_keywords)):
        try:
            items = fetch()
            n = db.insert_items(conn, items)
            new_count += n
            _log(f"{name}: {len(items)}건 조회, 신규 {n}건")
        except Exception as e:
            _log(f"{name} 수집 실패: {e}")

    if new_count:
        while True:
            try:
                processed = analysis.analyze_pending(conn)
            except Exception as e:
                _log(f"분석 실패: {e}")
                break
            if processed == 0:
                break
            _log(f"분석 완료: {processed}건")

    min_imp = int(CFG["analysis"]["alert_min_importance"])
    alerts = db.pending_alerts(conn, min_imp)
    if alerts:
        sent_ids = []
        for row in alerts:
            try:
                notify.send(notify.format_alert(row))
                sent_ids.append(row["id"])
            except Exception as e:
                _log(f"알림 발송 실패 (id={row['id']}): {e}")
        db.mark_alerted(conn, sent_ids)
        _log(f"실시간 알림 {len(sent_ids)}건 발송")


def send_briefing(conn) -> None:
    text = briefing.build(conn)
    notify.send(text)
    _log("아침 브리핑 발송 완료")


def watch(conn) -> None:
    interval = int(CFG["collect"]["poll_interval_sec"])
    brief_time = str(CFG["briefing"]["time"])  # "HH:MM"
    last_brief_date: date | None = None
    _log(f"감시 시작 (주기 {interval}초, 브리핑 {brief_time})")

    while True:
        try:
            collect_once(conn)

            now = datetime.now()
            if now.strftime("%H:%M") >= brief_time and last_brief_date != now.date():
                send_briefing(conn)
                last_brief_date = now.date()
        except Exception:
            traceback.print_exc()
        time.sleep(interval)


def status(conn) -> None:
    total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    analyzed = conn.execute("SELECT COUNT(*) FROM items WHERE analyzed=1").fetchone()[0]
    alerted = conn.execute("SELECT COUNT(*) FROM items WHERE alerted=1").fetchone()[0]
    print(f"수집 {total}건 / 분석 {analyzed}건 / 알림 발송 {alerted}건")
    for row in conn.execute(
        "SELECT theme, COUNT(*) c FROM items WHERE analyzed=1 GROUP BY theme ORDER BY c DESC LIMIT 10"
    ):
        print(f"  {row['theme']}: {row['c']}건")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "collect"
    conn = db.connect()
    if cmd == "collect":
        collect_once(conn)
    elif cmd == "watch":
        watch(conn)
    elif cmd == "brief":
        send_briefing(conn)
    elif cmd == "status":
        status(conn)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
