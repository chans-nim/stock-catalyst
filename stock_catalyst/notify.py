"""텔레그램 발송."""
import requests

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

_MAX_LEN = 4000  # 텔레그램 메시지 한도(4096) 안전 마진


def send(text: str) -> None:
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 설정되지 않았습니다 (.env 확인)")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chunk_start in range(0, len(text), _MAX_LEN):
        chunk = text[chunk_start:chunk_start + _MAX_LEN]
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        resp.raise_for_status()


def format_alert(row) -> str:
    stars = "★" * row["importance"]
    src = "공시" if row["source"] == "dart" else "뉴스"
    lines = [f"🚨 <b>[{src}] {row['title']}</b>"]
    if row["corp_name"]:
        lines.append(f"기업: {row['corp_name']}")
    if row["summary"]:
        lines.append(row["summary"])
    meta = f"테마: {row['theme']} | 중요도: {stars}"
    if row["related_stocks"]:
        meta += f"\n관련주: {row['related_stocks']}"
    lines.append(meta)
    if row["url"]:
        lines.append(f'<a href="{row["url"]}">원문 보기</a>')
    return "\n".join(lines)
