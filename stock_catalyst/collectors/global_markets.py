"""Yahoo Finance 차트 API를 이용한 해외 주요 지수 종가 조회."""
from datetime import datetime, timezone

import requests


BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"


def fetch_index(symbol: str, name: str, timeout: int = 10) -> dict:
    """최근 두 거래일 종가와 등락률을 반환한다."""
    resp = requests.get(
        f"{BASE_URL}/{symbol}",
        params={"interval": "1d", "range": "10d", "events": "history"},
        headers={"User-Agent": "stock-catalyst/1.0"},
        timeout=timeout,
    )
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []
    points = [(ts, close) for ts, close in zip(timestamps, closes) if close is not None]
    if len(points) < 2:
        raise ValueError("등락률 계산에 필요한 종가 데이터가 부족합니다")

    previous = float(points[-2][1])
    latest = float(points[-1][1])
    change_rate = (latest - previous) / previous * 100
    # 일봉 타임스탬프는 거래소 현지 거래일과 같은 UTC 날짜로 제공된다.
    market_date = datetime.fromtimestamp(points[-1][0], timezone.utc).strftime("%m/%d")
    return {
        "symbol": symbol,
        "name": name,
        "price": latest,
        "change_rate": change_rate,
        "market_date": market_date,
    }


def fetch_markets(markets: list[dict], timeout: int = 10) -> list[dict]:
    """개별 지수 실패를 격리해 설정된 해외 지수를 순서대로 조회한다."""
    results = []
    for market in markets:
        symbol = str(market["symbol"])
        name = str(market.get("name") or symbol)
        try:
            results.append(fetch_index(symbol, name, timeout=timeout))
        except Exception as exc:
            results.append({"symbol": symbol, "name": name, "error": str(exc)})
    return results
