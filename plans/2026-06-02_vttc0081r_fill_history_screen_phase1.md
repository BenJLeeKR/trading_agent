# VTTC0081R 체결내역 화면 + 주기 동기화 1차 구현

## 우선순위 판정

이 작업은 **상위 우선순위**로 분류한다.

이유:

1. `paper_truth_missing` 운영 해석을 주문 추론/포지션 델타에만 의존하지 않도록 바꿔준다.
2. 주문 상태 복구 이후 남은 핵심 리스크가 “체결 근거 관측성 부족”이므로, 별도 체결 원장 화면이 가장 직접적인 개선이다.
3. 기존 `fill_events`는 우리 주문과 연결된 체결만 보여주기 때문에, 운영자가 KIS 원본 체결내역을 독립적으로 확인할 수 있는 화면이 필요하다.
4. 기존 `snapshot_sync_runs` / `post-submit-sync` 구조를 재사용할 수 있어 구현 대비 효과가 크다.

따라서 시스템 장애성 이슈 바로 아래, 운영 안정화 기능 중에서는 **다음 주요 작업**으로 진행하는 것이 맞다.

## 1차 구현 범위

### 백엔드 저장 모델

- `trading.fill_sync_runs`
  - VTTC0081R 체결내역 동기화 실행 이력 저장
- `trading.broker_fill_snapshots`
  - KIS 체결내역 원본 스냅샷 저장
  - `fill_events`와 별도 유지
  - `dedupe_key`로 중복 방지

### 동기화 배치

- 신규 스크립트: `scripts/run_fill_sync_loop.py`
- 내부 서비스: `src/agent_trading/services/fill_history_sync.py`
- 기본 정책:
  - KST 오늘 날짜 기준 조회
  - 장중 주기 실행
  - `ops-scheduler`에서 one-shot subprocess로 호출
  - 기본 cadence:
    - 장중 `10분`
    - EOD 1회 추가

### 조회 API

- `GET /fill-history?date=YYYY-MM-DD`
- `GET /fill-sync-runs`
- `GET /fill-sync-runs/summary`

### Admin UI

- 신규 메뉴: `체결내역`
- 신규 화면: `/fills`
- 표시 내용:
  - 오늘 체결 건수
  - 마지막 동기화 시각/상태
  - 동기화 stale 여부
  - 체결 테이블
    - 계좌
    - 종목
    - BUY/SELL
    - ODNO
    - 체결번호
    - 주문수량
    - 체결수량
    - 체결가
    - 주문상태
    - 주문/체결 시각

## 구현 시 판단한 설계 포인트

### 왜 `fill_events` 재사용만 하지 않았는가

`fill_events`는 내부 `broker_orders`와 연결된 체결만 저장한다.  
운영자는 “우리 주문과 연결되지 않았더라도 KIS 원본 체결내역이 무엇인지”를 봐야 하므로, 조회 전용 원장 테이블이 별도로 필요했다.

### 왜 `ops-scheduler`에 붙였는가

별도 워커를 추가하는 것보다 기존 운영 subprocess 패턴을 재사용하는 편이 리스크가 낮다.  
`snapshot_sync`, `post_submit_sync`와 같은 방식으로 `fill_sync`를 추가하면 cadence와 timeout 관리가 일관된다.

### 왜 기본 cadence를 10분으로 잡았는가

체결내역은 주문 제출 자체보다 낮은 실시간성을 가져도 된다.  
`VTTC0081R`는 quota를 아껴야 하므로, 장중 10분 cadence가 1차 운영 기준으로 적절하다고 판단했다.

## 검증 결과

### 백엔드 테스트

- `tests/api/test_fill_history.py`
- `tests/api/test_snapshot_sync_runs.py`
- `tests/scripts/test_run_ops_scheduler.py`

결과:

- `135 passed`

### 프론트엔드 테스트

- `admin_ui/src/__tests__/fillHistory.test.tsx`

결과:

- `1 passed`

### 타입/빌드

- `cd admin_ui && npx tsc --noEmit` 통과
- `cd admin_ui && npm run build` 통과

### 런타임 검증

- `api` healthy
- `ops-scheduler` healthy
- DB migration 적용 후 테이블 생성 확인:
  - `trading.fill_sync_runs`
  - `trading.broker_fill_snapshots`
- `docker compose exec -T app python3 scripts/run_fill_sync_loop.py --once`
  - VTTC0081R 호출 200 OK 확인
  - 실행 이력 저장 확인

## 현재 한계

1. 1차 구현은 `.env` 기준 단일 KIS 계좌 credential 가정이다.
2. 현재 화면은 기본적으로 KST 오늘 체결내역 중심이다.
3. `broker_fill_snapshots`는 KIS 원본 체결 관측용이고, 아직 주문 상세 화면과 직접 cross-link 하지 않았다.
4. 이번 수동 실행에서는 체결 0건, 비체결 3건으로 들어와 저장 건수는 0이었다.

## 다음 단계

1. 체결내역 화면에서 `order_request_id` 연계 링크 추가
2. `paper_truth_missing` 주문 상세에서 해당 ODNO 체결내역으로 바로 점프
3. 날짜 범위 조회 지원
4. fill sync stale 상태를 운영 대시보드 경고와 연계
