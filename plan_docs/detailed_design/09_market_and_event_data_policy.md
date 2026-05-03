# 시장 및 이벤트 데이터 정책 v1

## 1. 목적

이 문서는 시세 외부의 이벤트성 데이터와 비시세 데이터를 어떻게 수집, 정규화, 중복 제거, 저장, 재현할지 정의한다.

대상 범위:

- OpenDART 공시
- KRX KIND 공시/거래정지/관리종목/투자주의 이벤트
- 뉴스
- 증권사/리서치 리포트
- 거시경제 일정 및 지표
- 섹터/테마 이벤트

핵심 목표:

- AI 판단 계층에 유용한 이벤트만 공급
- stale event, duplicate event, low-trust source로 인한 오판 방지
- paper/live/replay에서 같은 이벤트 해석이 재현 가능하도록 저장

## 2. 데이터 소스 분류

### 2.1 Tier 1: 규제/공식 소스

- OpenDART
- KRX KIND
- 한국거래소 장 운영 공지
- 정부/중앙은행/통계청 등 공식 거시 발표

특징:

- 신뢰도 가장 높음
- 법적/규제 이벤트 해석의 기준 소스
- 지연보다 정확성이 중요

### 2.2 Tier 2: 준공식/기관 소스

- 증권사 리포트
- 거래소/예탁결제원/금융투자협회 유관 데이터
- 기관 배포 캘린더/산업 자료

특징:

- 정제된 해석에 유리
- bias와 시차를 감안해야 함

### 2.3 Tier 3: 뉴스/미디어/스크리너

- 일반 뉴스
- 경제 매체
- 시장 속보
- 외부 스크리너/랭킹 정보

특징:

- 속도는 빠르지만 noise가 큼
- duplicate, rewrite, rumor 가능성이 높음

## 3. Source Reliability Policy

각 source는 신뢰도 등급을 가진다.

```text
T1 = regulatory / official
T2 = institutional / research
T3 = media / aggregator
T4 = low-confidence / experimental
```

원칙:

- T1 이벤트는 사실 판단 기준 소스다.
- T3는 단독으로 hard action을 만들지 않는다.
- T3 이벤트는 T1/T2 corroboration 또는 시장 반응 확인 후 강화한다.
- T4는 live 주문 판단 입력으로 직접 사용하지 않는다.

## 4. Polling / Fetch 정책

### 4.1 공시

- 장중: 짧은 주기 polling
- 장외: 완화된 주기 polling
- 장 개시 직전과 직후에는 polling 강도를 높인다.

### 4.2 뉴스

- 속보 피드는 짧은 주기 ingestion
- 본문 full fetch는 후보 이벤트에 한해 수행
- 동일 종목/동일 헤드라인 군집은 dedup 후 본문 확장

### 4.3 리포트

- 분/초 단위 polling보다 배치성 수집이 적합하다.
- 종목 커버리지 변경, 목표주가 변경, rating 변경 이벤트를 별도 추출한다.

### 4.4 거시 데이터

- 경제 캘린더는 사전 적재
- 발표 시점에는 해당 이벤트를 실시간 태깅
- 발표값/예상값/이전값을 같이 저장한다.

## 5. Dedup 정책

### 5.1 이벤트 dedup 기준

- source event id
- issuer/corp code
- symbol
- event type
- published timestamp window
- normalized headline hash

### 5.2 뉴스 dedup 기준

- 원문 source id 우선
- 없으면 headline normalization hash
- 1차 제목 해시 + 2차 본문 유사도 기반 dedup

### 5.3 공시 정정 처리

- correction/amendment 여부를 별도 필드로 저장
- 원문 이벤트를 덮어쓰지 않고 supersede relation을 유지

## 6. Event Classification

모든 이벤트는 최소한 아래 필드를 가져야 한다.

- `event_type`
- `entity_type`
- `entity_id`
- `source_name`
- `source_reliability_tier`
- `published_at`
- `ingested_at`
- `effective_at`
- `severity`
- `direction`
- `novelty_score`
- `confidence`

권장 event type:

- earnings
- disclosure_material
- disclosure_correction
- trading_halt
- investment_warning
- management_issue
- capital_change
- governance
- macro_release
- sector_policy
- broker_report_change
- news_breaking

## 7. Event-to-Decision Policy

- 모든 이벤트가 주문 판단으로 직결되면 안 된다.
- 이벤트는 먼저 분류되고, 그 다음 strategy/risk layer에서 해석된다.

필수 원칙:

- trading halt / management issue / investment warning은 hard block 후보
- earnings / policy / large contract / guidance change는 전략별 alpha event 후보
- rumor / low-confidence media는 watchlist 강화 용도로만 사용 가능

## 8. RAG Storage Policy

- 원문 기사/공시/리포트는 object storage 또는 document store에 저장
- embedding/RAG 인덱스는 원문 전체가 아니라 정제된 chunk 기준으로 생성
- chunk에는 source tier, timestamp, symbol, issuer, event type 메타데이터를 붙인다

필수 메타데이터:

- document_id
- source_name
- source_reliability_tier
- published_at
- ingested_at
- symbols
- issuer identifiers
- event_type
- checksum
- language

## 9. Licensing and Usage Policy

- 상용 뉴스/리포트는 사용 권한 범위를 명확히 관리한다.
- 라이선스가 불명확한 source는 live 운영 입력으로 사용하지 않는다.
- 원문 재배포 금지 조건이 있는 경우 요약 결과와 참조 메타데이터만 저장한다.
- 라이선스 정책은 source registry에 기록한다.

## 10. Data Freshness Policy

- 이벤트성 데이터는 freshness budget을 가진다.
- freshness는 source published time과 ingest time 둘 다 기준으로 본다.

예:

- breaking news: 분 단위 freshness
- official disclosure: 수 분 이내 ingestion 목표
- macro release: 발표 시점 기준 즉시 태깅
- broker reports: 시의성은 낮지만 버전 추적은 필수

정책:

- freshness budget 초과 시 event를 stale로 표시
- stale event는 신규 진입 근거에서 제외 가능
- replay에서는 당시 stale 여부도 같이 재현해야 한다

## 11. Data Quality Checks

- duplicate event ratio
- source outage detection
- headline/body mismatch
- symbol tagging failure
- timestamp skew
- unsupported language
- parse failure
- stale ingest
- correction chain inconsistency

## 12. Storage and Replay Requirements

저장해야 할 것:

- raw payload reference
- normalized event record
- classification result
- source reliability tier
- dedup decision
- parser version
- classifier version
- RAG chunk version

replay 시점에는 다음이 재현 가능해야 한다.

- 당시 어떤 이벤트가 들어왔는지
- 어떤 이벤트가 dedup/제외되었는지
- 어떤 classifier/version으로 해석되었는지

## 13. 운영 원칙

- T1 source 장애는 severity가 높다.
- 장중 뉴스 폭주 시 universe gatekeeper가 분석 대상을 더 축소할 수 있어야 한다.
- 이벤트 입력이 불안정하면 신규 진입을 보수적으로 줄인다.
- 이벤트 해석은 AI가 하더라도 source reliability와 freshness는 deterministic rule로 먼저 평가한다.

## 14. v1 권장 범위

- OpenDART
- KRX KIND
- 1개 이상 신뢰 가능한 뉴스 피드
- 기본 거시 캘린더

v1에서는 source 수를 무리하게 늘리지 않고, **신뢰도 높은 이벤트 소스 + 재현 가능한 저장 구조**를 먼저 확보한다.
