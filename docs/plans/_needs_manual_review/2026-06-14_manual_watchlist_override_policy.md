# Manual Watchlist / Override Policy

## 목적
- `Universe Selection`의 `manual` 계층을 운영자가 안전하게 사용할 수 있도록 정책을 고정한다.
- 아직 전용 admin CRUD나 DB 테이블을 만들기 전 단계에서, 최소 입력 경로와 우선순위를 명확히 한다.

## 현재 입력 경로
- `GET /instruments/trading-universe/preview`
  - `manual_symbols=005930,000660:KRX`
- decision loop
  - `TRADING_UNIVERSE_MANUAL_SYMBOLS=005930,000660:KRX`

## 정책

### 1. 기본값은 비활성
- `manual` 계층은 기본적으로 비어 있다.
- 운영자가 명시적으로 symbol을 넣었을 때만 동작한다.

### 2. 목적은 `watchlist`, not hard bypass
- `manual`은 “오늘 꼭 보고 싶은 종목을 universe에 올리는 기능”이다.
- 브로커 제약, liquidity filter, cap, pre-AI gate, submit gate를 우회하지 않는다.

### 3. 우선순위
- `held_position` > `event_overlay` > `market_overlay` > `manual` > `core`
- 즉:
  - 보유 종목/이벤트/시장 신호가 이미 강하면 그것이 `manual`보다 우선한다.
  - `manual`은 `core`보다만 높다.

### 4. cap / filter 정책
- `manual` 심볼도 최종 liquidity filter를 통과해야 한다.
- `exclude_held_from_cap=True`일 때 held만 cap 제외이고, `manual`은 일반 cap 대상이다.
- 따라서 `manual`은 “무조건 판단”이 아니라 “후보 승격”이다.

### 5. 운영 용도
- 다음과 같은 경우에만 사용하는 것을 권장한다.
  - 장중 특이 공시/뉴스/수급이 감지됐는데 아직 자동 source에 반영 전
  - 운영자가 당일 집중 모니터링이 필요한 종목을 임시 추가
  - 신규 universe 정책 검증을 위한 한시적 관찰

### 6. 금지/비권장
- 상시 대량 등록
- 자동 submit 보장을 기대하는 사용
- held_position/event_overlay/market_overlay 품질 문제를 `manual`로 덮는 운영

## 향후 단계
- 전용 DB 테이블 또는 admin UI CRUD는 후속 과제로 미룬다.
- 그 전까지는 env/query 기반의 최소 deterministic 입력만 허용한다.
