"""stock-catalyst CLI.

사용법:
  python main.py           # 기본: 10분 주기 상시 실행 (watch)
  python main.py watch     # 상시 실행: 주기 수집 + 실시간 알림 + 아침 브리핑 자동 발송
  python main.py collect   # 1회 수집 + 분석 + 리포트/중요 재료 알림
  python main.py report    # 전체 기사 요약+중요도 리포트 즉시 발송
  python main.py brief     # 아침 브리핑 즉시 생성·발송
  python main.py words     # 오늘의 영단어 학습 리포트 즉시 생성·발송
  python main.py status    # DB 수집 현황 출력
"""
import sys
import time
import traceback
from datetime import datetime, date

from stock_catalyst.config import CFG
from stock_catalyst import db, analysis, notify, briefing, report, cluster, english_learning
from stock_catalyst.collectors import dart, rss_news


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def collect_once(conn) -> None:
    """수집 -> 분석 -> 리포트/알림 1사이클."""
    new_count = 0
    analyzed_total = 0
    for name, fetch in (("DART", dart.fetch_today), ("뉴스RSS", rss_news.fetch_feeds)):
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
            analyzed_total += processed
            _log(f"분석 완료: {processed}건")

        try:
            emb = cluster.process_pending(conn)
            if emb.get("embedded"):
                _log(f"임베딩/클러스터: {emb['embedded']}건 (bge-m3)")
        except Exception as e:
            _log(f"임베딩/클러스터 실패: {e}")

    # 신규 분석이 없어도 미임베딩 잔여분 처리
    elif CFG.get("embedding", {}).get("enabled", True):
        try:
            emb = cluster.process_pending(conn)
            if emb.get("embedded"):
                _log(f"임베딩/클러스터: {emb['embedded']}건 (bge-m3)")
        except Exception as e:
            _log(f"임베딩/클러스터 실패: {e}")

    # 신규 분석 또는 미전송 후보가 있으면 리포트 발송
    if CFG.get("report", {}).get("after_collect", True):
        if analyzed_total or report.has_sendable(conn):
            try:
                send_report(conn)
            except Exception as e:
                _log(f"재료 리포트 발송 실패: {e}")

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
        if sent_ids:
            db.mark_alerted(conn, sent_ids)
            _log(f"실시간 알림 {len(sent_ids)}건 발송")


def send_report(conn) -> None:
    text, ids = report.build(conn)
    if not ids:
        _log("재료 리포트 스킵 (발송 대상 없음)")
        return
    notify.send(text)
    # 발송 성공 후에만 노출 기록 → 실패 시 다음 주기에 재시도
    db.mark_reported(conn, ids)
    _log(f"재료 리포트 발송 완료 ({len(ids)}건, 노출 기록)")


def send_briefing(conn) -> None:
    try:
        text = briefing.build(conn)
        notify.send(text)
        _log("아침 브리핑 발송 완료")
    except Exception as e:
        _log(f"아침 브리핑 발송 실패: {e}")


def send_english_report() -> bool:
    """주식 브리핑과 독립적으로 오늘의 영단어 리포트를 발송한다."""
    try:
        notify.send(english_learning.build())
        _log("오늘의 영단어 리포트 발송 완료")
        return True
    except Exception as e:
        _log(f"오늘의 영단어 리포트 발송 실패: {e}")
        return False


def watch(conn) -> None:
    interval = int(CFG["collect"]["poll_interval_sec"])
    brief_time = str(CFG["briefing"]["time"])  # "HH:MM"
    english_cfg = CFG.get("english_learning") or {}
    english_enabled = bool(english_cfg.get("enabled", True))
    english_time = str(english_cfg.get("time", brief_time))
    last_brief_date: date | None = None
    last_english_date: date | None = None
    _log(f"감시 시작 (주기 {interval}초, 브리핑 {brief_time}, 영단어 {english_time})")

    while True:
        try:
            collect_once(conn)

            now = datetime.now()
            if now.strftime("%H:%M") >= brief_time and last_brief_date != now.date():
                send_briefing(conn)
                last_brief_date = now.date()
            if (
                english_enabled
                and now.strftime("%H:%M") >= english_time
                and last_english_date != now.date()
                and send_english_report()
            ):
                last_english_date = now.date()
        except Exception:
            traceback.print_exc()
        time.sleep(interval)


def status(conn) -> None:
    total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    analyzed = conn.execute("SELECT COUNT(*) FROM items WHERE analyzed=1").fetchone()[0]
    alerted = conn.execute("SELECT COUNT(*) FROM items WHERE alerted=1").fetchone()[0]
    embedded = conn.execute(
        "SELECT COUNT(*) FROM items WHERE embedding IS NOT NULL AND embedding != ''"
    ).fetchone()[0]
    clusters = conn.execute(
        "SELECT COUNT(DISTINCT cluster_id) FROM items WHERE cluster_id > 0"
    ).fetchone()[0]
    print(f"수집 {total}건 / 분석 {analyzed}건 / 임베딩 {embedded}건 / 클러스터 {clusters}개 / 알림 {alerted}건")
    print("섹터:")
    for row in conn.execute(
        "SELECT sector, COUNT(*) c FROM items WHERE sector != '' GROUP BY sector ORDER BY c DESC LIMIT 12"
    ):
        print(f"  {row['sector']}: {row['c']}건")
    print("테마:")
    for row in conn.execute(
        "SELECT theme, COUNT(*) c FROM items WHERE analyzed=1 GROUP BY theme ORDER BY c DESC LIMIT 10"
    ):
        print(f"  {row['theme']}: {row['c']}건")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "watch"
    # 영단어 리포트는 DB를 포함한 주식 모듈 실행 상태와 무관하게 동작한다.
    if cmd == "words":
        send_english_report()
        return

    conn = db.connect()
    if cmd == "collect":
        collect_once(conn)
    elif cmd == "watch":
        watch(conn)
    elif cmd == "report":
        send_report(conn)
    elif cmd == "brief":
        send_briefing(conn)
    elif cmd == "status":
        status(conn)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
