# stock-catalyst

한국 주식 시장 **재료(주가를 움직이는 뉴스·공시·이벤트) 수집·분석 시스템**.

- **수집**: DART 전자공시 + 언론사 뉴스 RSS 피드(키워드 필터) 폴링, 한국투자증권(KIS) API 시세
- **분석**: 온디바이스 AI(Ollama `qwen2.5:3b`)로 요약·중요도, `bge-m3`로 기사 그룹화·섹터 분류 → SQLite 적재 (OpenAI 전환 가능)
- **실시간 알림**: 중요도 높은 재료를 텔레그램으로 즉시 푸시
- **아침 브리핑**: 매일 지정 시각에 해외 주요 지수·미국 지수 선물 + 핵심 재료 + 테마별 동향 + 관심 종목 시세를 텔레그램으로 발송
- **오늘의 영단어**: 네이버 오늘의 영어 단어 5개를 뜻·발음·영문 예문·해석과 함께 별도 발송하고 단어·예문 음원 링크 제공

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 온디바이스 AI (Ollama)

분석은 기본적으로 로컬 Ollama 를 사용합니다 (무료, API 키 불필요, telenews 와 동일 방식).

```powershell
# https://ollama.com 에서 설치 후
ollama pull qwen2.5:3b
ollama pull bge-m3
ollama serve    # 서버가 떠 있지 않은 경우
```

## API 키 설정

`.env.example` 을 `.env` 로 복사한 뒤 각 키를 채웁니다.

| 키 | 발급처 | 비고 |
|---|---|---|
| `DART_API_KEY` | [opendart.fss.or.kr](https://opendart.fss.or.kr) | 무료, 일 20,000건 |
| `KIS_APP_KEY/SECRET` | [KIS Developers](https://apiportal.koreainvestment.com) | 한국투자증권 계좌 필요 |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) | `analysis.provider: openai` 사용 시에만 필요 |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 @BotFather | `/newbot` 으로 생성 |
| `TELEGRAM_CHAT_ID` | @userinfobot 등 | 알림 받을 채팅 ID |

## 사용법

```powershell
python main.py           # 기본: 10분 주기 상시 실행 (watch)
python main.py watch     # 상시 실행: 주기 수집 + 실시간 알림 + 아침 브리핑 자동 발송
python main.py collect   # 1회: 수집 → 분석 → 리포트/중요 재료 알림
python main.py report    # 전체 기사 요약+중요도 리포트 즉시 발송
python main.py brief     # 아침 브리핑 즉시 발송
python main.py words     # 오늘의 영단어 학습 리포트 즉시 발송
python main.py status    # 수집·분석 현황 확인
```

`python main.py` 만 실행하면 10분 주기(`collect.poll_interval_sec: 600`)로 동작합니다. 주기는 `config.yaml` 에서 조정할 수 있습니다.

## 설정 (`config.yaml`)

- `collect.news_feeds`: 수집할 언론사 RSS 피드 목록 (name / url)
- `collect.news_keywords`: 기사 필터 키워드 (제목+요약 매칭, 비우면 전체 수집)
- `collect.dart_exclude`: 노이즈 공시 제외 키워드
- `analysis.provider`: AI 공급자 — `ollama`(온디바이스, 기본) 또는 `openai`
- `analysis.ollama`: Ollama chat 설정 (base_url / model / timeout_sec / batch_size)
- `embedding`: bge-m3 임베딩·클러스터·섹터 (`similarity_threshold` 기본 0.62)
- `analysis.alert_min_importance`: 실시간 알림 최소 중요도 (기본 4)
- `report.lookback_hours`: 리포트에 포함할 수집 범위 (기본 18시간)
- `report.min_importance`: 리포트 포함 최소 중요도 (기본 3)
- `report.max_chars`: 리포트 최대 글자 수 (기본 4000, 초과 분은 생략)
- `report.after_collect`: 수집·분석 후 리포트 자동 발송 (기본 true)
- `report.related_limit`: 동일 종목 기전송 연관 기사 최대 표시 수 (기본 3)
- 이미 보낸 기사는 재전송하지 않음. 같은 종목의 새 기사가 오면 연관 기사로만 첨부
- `briefing.time`: 아침 브리핑 발송 시각 (기본 08:00)
- `briefing.global_markets`: 브리핑에 표시할 해외 지수 이름과 Yahoo Finance 심볼
- `briefing.global_futures`: 브리핑에 표시할 미국 지수 선물 이름과 Yahoo Finance 심볼
- `briefing.global_market_timeout_sec`: 해외 지수 개별 조회 제한 시간 (기본 10초)
- `watchlist`: 브리핑에 시세를 포함할 종목코드
- `english_learning`: 영단어 리포트 활성화, 발송 시각, 단어 수, 음원 링크, 조회 제한 시간 설정

## 구조

```
main.py                    # CLI (collect / watch / brief / status)
stock_catalyst/
  config.py                # .env + config.yaml 로딩
  db.py                    # SQLite 저장 레이어 (items 통합 테이블)
  analysis.py              # AI 요약·테마·중요도 분석 (Ollama 기본 / OpenAI 선택)
  embedding.py             # bge-m3 임베딩 + 섹터 프로토타입 분류
  cluster.py               # 유사도 기반 기사 그룹화
  notify.py                # 텔레그램 발송
  report.py                # 전체 기사 요약+중요도 리포트 (종목·클러스터 연관)
  briefing.py              # 아침 브리핑 생성
  english_learning.py      # 네이버 오늘의 영단어 학습 리포트
  collectors/
    dart.py                # DART 공시 수집
    rss_news.py            # 언론사 RSS 뉴스 수집 (키워드 필터)
    kis.py                 # KIS 시세 조회 (토큰 캐시 포함)
    global_markets.py      # 해외 주요 지수 최근 종가 조회
```
