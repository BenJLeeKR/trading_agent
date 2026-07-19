# `reconcile_required` 잔존 주문 재진단 및 Authoritative Transition 복구 — 2026-05-19

## 1. 실제 DB 현황 (수정 전)

| 테이블 | 상태 | 건수 |
|--------|------|------|
| `order_requests` | `reconcile_required` | **25건** |
| `broker_orders` | `reconcile_required` | **26건** (1건 차이 = 고아 레코드) |

### 잔존 분류
| 구분 | 건수 | 주문일 | 상세 |
|------|------|--------|------|
| 매도(sell) | 7건 | 2026-05-19 | `000810`, `000660`, `000150` 등 |
| 매수(buy) | 18건 | 2026-05-18 | KIS paper 매수 주문 |
| 고아(orphan) | 1건 | - | order_request=rejected, broker_order=reconcile_required |

## 2. Root Cause — 3중 장애

### 장애 1: `_sync_reconcile_required_orders()` 데드 코드
[`order_sync_service.py:510`](src/agent_trading/services/order_sync_service.py:510)에 `_sync_reconcile_required_orders()` 메서드가 존재했지만, **어디에서도 호출되지 않음**.
[`PostSubmitSyncRunner.run_sync_cycle()`](src/agent_trading/services/order_sync_service.py:780)은 `sync_order_post_submit()`만 호출하고 reconcile_required 해소 로직은 실행하지 않음.

**영향**: RECONCILE_REQUIRED 상태를 자동 해소하는 경로가 아예 존재하지 않음.

### 장애 2: `transition_to_authoritative()`의 `order.symbol` 참조 버그
[`transition_to_authoritative()`](src/agent_trading/services/order_sync_service.py:617)가 `order.symbol`을 참조하지만, [`OrderRequestEntity`](src/agent_trading/domain/entities.py:250)에는 `symbol` 필드가 없고 `instrument_id: UUID`만 존재.

**영향**: 설사 `_sync_reconcile_required_orders()`가 호출되어도 `AttributeError`로 즉시 crash.

### 장애 3: `get_order_status()` 오늘 날짜만 조회
[`get_order_status()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1051) → `inquire_daily_ccld()`가 `strt_dt=None` (기본값 = 오늘 KST)로 호출되어 5/18 주문 18건 조회 불가.

**영향**: 정상 경로(`sync_order_post_submit()`)로도 5/18 주문 해소 불가.

## 3. 적용한 수정 (4가지)

### 수정 1: `_sync_reconcile_required_orders()` sync cycle 통합
[`order_sync_service.py:862`](src/agent_trading/services/order_sync_service.py:862)
- `PostSubmitSyncRunner.run_sync_cycle()` 메서드末尾에 `self.sync_service._sync_reconcile_required_orders()` 호출 추가
- 모든 pending order 처리 후 RECONCILE_REQUIRED 해소 로직 실행

### 수정 2: `transition_to_authoritative()` symbol 조회 버그 수정
[`order_sync_service.py:617`](src/agent_trading/services/order_sync_service.py:617)
- `order.symbol` → `order.instrument_id`로부터 `InstrumentRepository.find_one()`을 통해 symbol 조회
- `InstrumentEntity` import 추가

### 수정 3: `get_order_status()` 7일 범위 조회
[`rest_client.py:1061`](src/agent_trading/brokers/koreainvestment/rest_client.py:1061)
- `strt_dt=(KST_now - 7일).strftime("%Y%m%d")` 적용
- 5/18 주문 18건이 조회 범위에 포함됨

### 수정 4: 고아 레코드 정리 스크립트
[`scripts/cleanup_orphan_reconcile_required.py`](scripts/cleanup_orphan_reconcile_required.py)
- `order_request`가 terminal state(`rejected`/`cancelled`)인데 `broker_order`가 `reconcile_required`로 남아있는 고아 레코드 정리
- 실행 결과: `broker_order_id=da6abaa2...` → `rejected`로 업데이트

## 4. 전후 Count 비교

| 항목 | 수정 전 | 수정 후 (현재) | 비고 |
|------|---------|---------------|------|
| `order_requests` | 25건 | **25건** | sync cycle 실행 전이므로 아직 동일 |
| `broker_orders` | 26건 | **25건** ✅ | 고아 1건 정리 완료 |
| 차이 | 1건 | **0건** ✅ | order_requests와 broker_orders 일치 |

> 향후 sync cycle이 실행되면 `_sync_reconcile_required_orders()`가 25건을 순차 처리하여 감소 예상.

## 5. 테스트 결과

| 테스트 스위트 | 결과 |
|--------------|------|
| `tests/services/test_order_sync_service.py` | **36 passed ✅** |
| `tests/brokers/koreainvestment/` | **120 passed ✅** |

## 6. 배포 결과

| 단계 | 상태 |
|------|------|
| `docker compose build --no-cache app api ops-scheduler` | ✅ Build 성공 |
| `docker compose up -d --force-recreate app api ops-scheduler` | ✅ 3개 컨테이너 재생성 |
| Health check (`GET /health`) | ✅ HTTP 200 — `status: "ok"`, `database: "connected"` |

## 7. 파일 변경 요약

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| `src/agent_trading/services/order_sync_service.py` | 수정 | `run_sync_cycle()`에 `_sync_reconcile_required_orders()` 호출 추가 + `transition_to_authoritative()` symbol 조회 버그 수정 |
| `src/agent_trading/brokers/koreainvestment/rest_client.py` | 수정 | `get_order_status()` 7일 범위 조회로 확장 |
| `scripts/cleanup_orphan_reconcile_required.py` | **신규** | 고아 broker_orders 레코드 정리 스크립트 |

## 8. 운영 검증 결과

1. **고아 레코드 정리**: ✅ `broker_orders` RECONCILE_REQUIRED 26→25건 (order_requests와 일치)
2. **Sync cycle 통합**: ✅ 배포 완료, 다음 sync cycle 실행 시 25건 순차 처리 시작
3. **Symbol 조회 버그 수정**: ✅ `transition_to_authoritative()` 정상 동작 가능
4. **날짜 범위 확장**: ✅ 5/18 주문 18건 조회 가능해짐
