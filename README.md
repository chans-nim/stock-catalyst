# stock-catalyst

한국 주식 시장 **재료(주가를 움직이는 뉴스·공시·이벤트) 수집·분석 시스템**.

- **수집**: DART 전자공시 + 네이버 뉴스(특징주·재료성 키워드) 폴링, 한국투자증권(KIS) API 시세
- **분석**: OpenAI 로 요약, 테마 분류, 관련주 추출, 중요도(1~5) 평가 → SQLite 적재
- **실시간 알림**: 중요도 높은 재료를 텔레그램으로 즉시 푸시
- **아침 브리핑**: 매일 지정 시각에 핵심 재료 + 테마별 동향 + 관심 종목 시세를 텔레그램으로 발송

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## API 키 설정

`.env.example` 을 `.env` 로 복사한 뒤 각 키를 채웁니다.

| 키 | 발급처 | 비고 |
|---|---|---|
| `DART_API_KEY` | [opendart.fss.or.kr](https://opendart.fss.or.kr) | 무료, 일 20,000건 |
| `NAVER_CLIENT_ID/SECRET` | [developers.naver.com](https://developers.naver.com) | "검색" API 사용 설정 |
| `KIS_APP_KEY/SECRET` | [KIS Developers](https://apiportal.koreainvestment.com) | 한국투자증권 계좌 필요 |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) | gpt-4o-mini 기본 |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 @BotFather | `/newbot` 으로 생성 |
| `TELEGRAM_CHAT_ID` | @userinfobot 등 | 알림 받을 채팅 ID |

## 사용법

```powershell
python main.py collect   # 1회: 수집 → 분석 → 중요 재료 알림
python main.py watch     # 상시 실행: 주기 수집 + 실시간 알림 + 아침 브리핑 자동 발송
python main.py brief     # 아침 브리핑 즉시 발송
python main.py status    # 수집·분석 현황 확인
```

장중 상시 감시는 `python main.py watch` 를 켜두면 됩니다 (기본 5분 주기, `config.yaml` 에서 조정).

## 설정 (`config.yaml`)

- `collect.news_keywords`: 뉴스 검색 키워드
- `collect.dart_exclude`: 노이즈 공시 제외 키워드
- `analysis.alert_min_importance`: 실시간 알림 최소 중요도 (기본 4)
- `briefing.time`: 아침 브리핑 발송 시각 (기본 08:00)
- `watchlist`: 브리핑에 시세를 포함할 종목코드

## 구조

```
main.py                    # CLI (collect / watch / brief / status)
stock_catalyst/
  config.py                # .env + config.yaml 로딩
  db.py                    # SQLite 저장 레이어 (items 통합 테이블)
  analysis.py              # OpenAI 요약·테마·중요도 분석
  notify.py                # 텔레그램 발송
  briefing.py              # 아침 브리핑 생성
  collectors/
    dart.py                # DART 공시 수집
    naver_news.py          # 네이버 뉴스 수집
    kis.py                 # KIS 시세 조회 (토큰 캐시 포함)
```
