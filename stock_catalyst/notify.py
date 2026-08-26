"""텔레그램 발송."""
import html
import time

import requests

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

_MAX_LEN = 3500  # 4096 한도 여유 (태그 재삽입·경계 보정용)
_TIMEOUT = 30
_RETRIES = 3


def escape(text: str) -> str:
    """사용자 텍스트용 HTML 이스케이프 (& < >)."""
    return html.escape(text or "", quote=False)


def _split_chunks(text: str, max_len: int = _MAX_LEN) -> list[str]:
    """HTML 태그를 중간에 끊지 않도록 줄 단위로 분할."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    buf = ""
    for line in text.split("\n"):
        piece = line if not buf else buf + "\n" + line
        if len(piece) <= max_len:
            buf = piece
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        while len(line) > max_len:
            cut = max_len
            lt = line.rfind("<", 0, cut)
            gt = line.rfind(">", 0, cut)
            if lt > gt:
                cut = lt
            if cut <= 0:
                cut = max_len
            chunks.append(line[:cut])
            line = line[cut:]
        buf = line
    if buf:
        chunks.append(buf)
    return chunks


def _post_message(url: str, chunk: str) -> None:
    last_err: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            resp = requests.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=_TIMEOUT)
            if resp.ok:
                return
            detail = ""
            try:
                detail = resp.json().get("description", "")
            except Exception:
                detail = resp.text[:200]
            # 4xx는 재시도해도 의미 없음 (네트워크성 제외)
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                raise RuntimeError(f"텔레그램 발송 실패 ({resp.status_code}): {detail}")
            last_err = RuntimeError(f"텔레그램 발송 실패 ({resp.status_code}): {detail}")
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
        if attempt < _RETRIES - 1:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"텔레그램 발송 실패 (재시도 {_RETRIES}회): {last_err}") from last_err


def send(text: str) -> None:
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 설정되지 않았습니다 (.env 확인)")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chunk in _split_chunks(text):
        _post_message(url, chunk)


def format_alert(row) -> str:
    stars = "★" * row["importance"]
    src = "공시" if row["source"] == "dart" else "뉴스"
    lines = [f"🚨 <b>[{src}] {escape(row['title'])}</b>"]
    if row["corp_name"]:
        lines.append(f"기업: {escape(row['corp_name'])}")
    if row["summary"]:
        lines.append(escape(row["summary"]))
    meta = f"테마: {escape(row['theme'])} | 중요도: {stars}"
    if row["related_stocks"]:
        meta += f"\n관련주: {escape(row['related_stocks'])}"
    lines.append(meta)
    if row["url"]:
        href = html.escape(row["url"], quote=True)
        lines.append(f'<a href="{href}">원문 보기</a>')
    return "\n".join(lines)
