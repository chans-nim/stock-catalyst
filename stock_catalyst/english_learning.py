"""네이버 오늘의 영어 단어를 이용한 독립적인 아침 학습 리포트."""
import html
import re
from datetime import datetime
from urllib.parse import urlencode

import requests

from .config import CFG
from .notify import escape


DEFAULT_URL = "https://wquiz.dict.naver.com/enkodict/today/words.dict"
NAVER_BASE_URL = "https://wquiz.dict.naver.com"
PRONUNCIATION_API = f"{NAVER_BASE_URL}/wquiz-api/pronunLink.dict"
TTS_API = f"{NAVER_BASE_URL}/wquiz-api/ttsNvoice.dict"


def _text(fragment: str) -> str:
    """작은 HTML 조각에서 태그를 제거하고 표시용 텍스트를 만든다."""
    value = re.sub(r"<[^>]+>", "", fragment)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def parse_words(page: str) -> list[dict]:
    """네이버 오늘의 단어 카드에서 단어, 뜻, 예문을 추출한다."""
    starts = list(re.finditer(r'<div\s+class="word_card"[^>]*>', page, re.I))
    words: list[dict] = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(page)
        card = page[match.start():end]

        word_match = re.search(r'data-sentence="([^"]+)"', card, re.I)
        meaning_match = re.search(
            r'<span\s+class="mean_text"[^>]*>(.*?)</span>', card, re.I | re.S
        )
        example_match = re.search(
            r'<div\s+class="example"[^>]*lang="en"[^>]*>(.*?)</div>',
            card,
            re.I | re.S,
        )
        example_mean_match = re.search(
            r'<div\s+class="example_mean"[^>]*>(.*?)</div>', card, re.I | re.S
        )
        if not (word_match and meaning_match and example_match):
            continue

        part_match = re.search(
            r'<span\s+class="part"[^>]*>(.*?)</span>', card, re.I | re.S
        )
        pron_match = re.search(r'data-pron="([^"]+)"', card, re.I)
        pron_file_match = re.search(r'data-pronFile="([^"]+)"', card, re.I)
        words.append({
            "word": _text(word_match.group(1)),
            "pronunciation": _text(pron_match.group(1)) if pron_match else "",
            "pronunciation_file": _text(pron_file_match.group(1)) if pron_file_match else "",
            "part": _text(part_match.group(1)) if part_match else "",
            "meaning": _text(meaning_match.group(1)),
            "example": _text(example_match.group(1)),
            "example_mean": _text(example_mean_match.group(1)) if example_mean_match else "",
        })
    return words


def _tts_url(text: str) -> str:
    query = urlencode({
        "speaker": "clara",
        "service": "wquiz",
        "from": "wquiz",
        "speech_fmt": "mp3",
        "text": text,
    })
    return f"{TTS_API}?{query}"


def _word_audio_url(session: requests.Session, item: dict, timeout: int) -> str:
    """원어민 MP3 주소를 조회하고, 실패하면 네이버 TTS 주소를 사용한다."""
    pron_file = item.get("pronunciation_file") or ""
    if pron_file:
        try:
            resp = session.post(
                PRONUNCIATION_API,
                data={"filePath": pron_file},
                timeout=timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("meta", {}).get("status") == 1:
                url = payload.get("data", {}).get("pronunLink")
                if url:
                    return str(url)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            pass
    return _tts_url(item["word"])


def fetch_words() -> list[dict]:
    """네이버에서 오늘의 영어 단어를 조회한다."""
    cfg = CFG.get("english_learning") or {}
    url = str(cfg.get("source_url") or DEFAULT_URL)
    timeout = int(cfg.get("timeout_sec", 15))
    session = requests.Session()
    resp = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; stock-catalyst/1.0)",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    words = parse_words(resp.text)
    if not words:
        raise ValueError("네이버 오늘의 영단어를 찾지 못했습니다")
    limit = int(cfg.get("word_limit", 5))
    words = words[:limit]
    if cfg.get("audio_enabled", True):
        for item in words:
            item["word_audio_url"] = _word_audio_url(session, item, timeout)
            item["example_audio_url"] = _tts_url(item["example"])
    return words


def build() -> str:
    """텔레그램 HTML 형식의 오늘의 영단어 학습 리포트를 만든다."""
    words = fetch_words()
    today = datetime.now().strftime("%Y-%m-%d (%a)")
    lines = [f"📚 <b>오늘의 영단어 — {today}</b>", ""]
    for number, item in enumerate(words, 1):
        label = escape(item["word"])
        if item["pronunciation"]:
            label += f" [{escape(item['pronunciation'])}]"
        lines.append(f"<b>{number}. {label}</b>")
        meaning = escape(item["meaning"])
        if item["part"]:
            meaning = f"({escape(item['part'])}) {meaning}"
        lines.append(f"뜻: {meaning}")
        audio_links = []
        if item.get("word_audio_url"):
            href = html.escape(item["word_audio_url"], quote=True)
            audio_links.append(f'<a href="{href}">🔊 단어 발음</a>')
        if item.get("example_audio_url"):
            href = html.escape(item["example_audio_url"], quote=True)
            audio_links.append(f'<a href="{href}">🔊 예문 발음</a>')
        if audio_links:
            lines.append(" | ".join(audio_links))
        lines.append(f"예문: {escape(item['example'])}")
        if item["example_mean"]:
            lines.append(f"해석: {escape(item['example_mean'])}")
        lines.append("")
    lines.append(f'<a href="{DEFAULT_URL}">네이버 오늘의 단어에서 학습하기</a>')
    return "\n".join(lines)
