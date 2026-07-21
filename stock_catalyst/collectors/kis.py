"""한국투자증권 KIS Developers REST API - 관심 종목 현재가 조회.

접근 토큰은 유효기간(24h)이 있어 data/ 에 캐시한다.
"""
import json
import time
from pathlib import Path

import requests

from ..config import DATA_DIR, KIS_APP_KEY, KIS_APP_SECRET

BASE_URL = "https://openapi.koreainvestment.com:9443"
TOKEN_CACHE = DATA_DIR / "kis_token.json"


def _get_token() -> str:
    if TOKEN_CACHE.exists():
        cached = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
        if cached.get("expires_at", 0) > time.time() + 60:
            return cached["access_token"]

    resp = requests.post(f"{BASE_URL}/oauth2/tokenP", json={
        "grant_type": "client_credentials",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    TOKEN_CACHE.write_text(json.dumps({
        "access_token": token,
        "expires_at": time.time() + int(data.get("expires_in", 86400)),
    }), encoding="utf-8")
    return token


def fetch_price(stock_code: str) -> dict:
    """국내주식 현재가 조회. {name, price, change_rate, volume} 반환."""
    if not (KIS_APP_KEY and KIS_APP_SECRET):
        raise RuntimeError("KIS_APP_KEY / KIS_APP_SECRET 이 설정되지 않았습니다 (.env 확인)")

    resp = requests.get(
        f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
        headers={
            "authorization": f"Bearer {_get_token()}",
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
            "tr_id": "FHKST01010100",
        },
        params={"fid_cond_mrkt_div_code": "J", "fid_input_iscd": stock_code},
        timeout=15,
    )
    resp.raise_for_status()
    out = resp.json()["output"]
    return {
        "code": stock_code,
        "price": int(out["stck_prpr"]),
        "change_rate": float(out["prdy_ctrt"]),
        "volume": int(out["acml_vol"]),
    }


def fetch_watchlist(codes: list[str]) -> list[dict]:
    results = []
    for code in codes:
        try:
            results.append(fetch_price(code))
        except Exception as e:  # 개별 종목 실패가 전체를 막지 않도록
            results.append({"code": code, "error": str(e)})
        time.sleep(0.2)  # 초당 호출 제한 여유
    return results
