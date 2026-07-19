# Reconciliation Worker KIS BrokerAdapter 통합 보고서

**작성일**: 2026-05-16  
**대상 파일**: [`src/agent_trading/services/reconciliation_worker.py`](../src/agent_trading/services/reconciliation_worker.py)  
**관련 이슈**: Worker가 실제 Broker Adapter 없이 mock `_get_broker()`만 사용하여 Reconciliation Run을 처리하지 못함

---

## 1. 배경

기존 [`ReconciliationRunProcessor`](../src/agent_trading/services/reconciliation_worker.py:43)는 `_get_broker()` 메서드가 단순히 `self.broker_cache.get(account_id)`를 반환했으며, 이는 항상 `None`이었다. 따라서 `_process_order_link()`가 실제 Broker API를 호출하지 못하고 Reconciliation Run의 상태를 정확히 판단할 수 없었다.

해결 방안: 실제 [`KoreaInvestmentAdapter`](../src/agent_trading/brokers/koreainvestment/adapter.py:50)를 생성하고 [`KISRestClient`](../src/agent_trading/brokers/koreainvestment/rest_client.py:220)를 통해 Broker의 오더 상태를 조회하여 Run을 Resolve/Converge하도록 개선.

---

## 2. 변경 사항 상세

### 2.1. [`src/agent_trading/repositories/contracts.py`](../src/agent_trading/repositories/contracts.py:84) — `BrokerAccountRepository` 프로토콜 확장

```python
async def list_by_account_id(self, account_id: UUID) -> Sequence[BrokerAccountEntity]: ...
```

- **목적**: Account → BrokerAccount 조회를 위한 메서드 추가
- **구현체**: [`PostgresBrokerAccountRepository`](../src/agent_trading/repositories/postgres/broker_accounts.py:88) (SQL JOIN), [`InMemoryBrokerAccountRepository`](../src/agent_trading/repositories/memory.py:845) (in-memory)

### 2.2. [`src/agent_trading/services/reconciliation_worker.py`](../src/agent_trading/services/reconciliation_worker.py:42) — `ReconciliationRunProcessor` 재구성

| 변경 항목 | 설명 |
|----------|------|
| `settings` 파라미터 추가 | [`AppSettings`](../src/agent_trading/config/settings.py:224)를 주입받아 KIS API 키/시크릿/계좌번호 등 설정 사용 |
| `_broker_cache: dict[UUID, Any]` | Account-level 캐시 — 동일 Account에 대해 Adapter 재사용 (인증 재사용) |
| `_get_broker_account(account_id)` | Account → `broker_account_id` → [`BrokerAccountEntity`](../src/agent_trading/domain/entities.py:34) 조회; `broker_name == "koreainvestment"` 검증 |
| `_get_or_create_broker(account_id, broker_account)` | 캐시 조회 → 없으면 `_build_adapter_for_broker_account()` 호출 |
| `_build_adapter_for_broker_account(broker_account_id, broker_name)` | Factory: [`KISRestClient`](../src/agent_trading/brokers/koreainvestment/rest_client.py:220) 생성 → [`KoreaInvestmentAdapter`](../src/agent_trading/brokers/koreainvestment/adapter.py:50) 생성 → `authenticate()` → [`BrokerSession`](../src/agent_trading/brokers/koreainvestment/adapter.py:118) 반환; 생성/인증 실패 시 `None` |
| `_process_order_link(run, link, adapter, account_ref)` | `adapter.resolve_unknown_state()` 호출 → 반환된 `status`가 FILLED/CANCELLED/REJECTED/EXPIRED/ACKNOWLEDGED 중 하나이면 resolved 처리, 아니면 failed 처리 |
| `process_run(run)` | `_get_broker_account()` → `_get_or_create_broker()` → 각 Order Link 처리 → run 상태 마킹; 예외 발생 시 **graceful degradation** (retained) |

#### 예외 처리 전략 (Graceful Degradation)

- **Broker Account 미존재**: try/except로 감싸서 `run`을 `retained` 상태로 유지 (다음 사이클에서 재시도)
- **Broker Name이 koreainvestment가 아님**: `retained` 처리
- **Adapter 생성 실패**: `retained` 처리 (자원 부족/일시적 오류)
- **Adapter 인증 실패**: `retained` 처리 (토큰 만료 등)
- **`resolve_unknown_state()` 호출 실패**: 해당 Order Link를 failed로 마킹
- **Broker Truth를 확인할 수 없는 상태 (SUBMITTED 등)**: 해당 Order Link를 failed로 마킹

### 2.3. [`scripts/run_reconciliation_worker.py`](../scripts/run_reconciliation_worker.py:170) — Script 업데이트

```python
# _run_loop() 내부
settings = AppSettings()
await _run_one_cycle(repos, ..., settings=settings)
```

- `AppSettings` 생성 후 `_run_one_cycle()`에 전달
- `_run_one_cycle()` 시그니처에 `settings: AppSettings` 추가
- `ReconciliationRunProcessor(repos=repos, ..., settings=settings)`로 전달

---

## 3. 테스트

### 3.1. 신규 테스트 11종 ([`tests/services/test_reconciliation_worker.py`](../tests/services/test_reconciliation_worker.py))

| # | 테스트명 | 설명 | 검증 포인트 |
|---|---------|------|-----------|
| 1 | `test_build_adapter_for_broker_account` | Adapter 생성 및 인증 | `KISRestClient` → `KoreaInvestmentAdapter` → `authenticate()` → `BrokerSession` 반환 |
| 2 | `test_build_adapter_for_broker_account_not_found` | BrokerAccount 조회 실패 | `None` 반환 |
| 3 | `test_build_adapter_for_broker_name_not_kis` | KIS 이외 Broker | `None` 반환 (retained 처리) |
| 4 | `test_account_level_auth_reuse` | 동일 Account Adapter 재사용 | 두 번째 호출 시 `_build_adapter_for_broker_account()` 재호출 없이 캐시 반환 |
| 5 | `test_resolve_unknown_state_success` | FILLED → resolved | `adapter.resolve_unknown_state()` → terminal status → link resolved |
| 6 | `test_resolve_unknown_state_truth_unavailable` | SUBMITTED → failed | `resolve_unknown_state()`가 SUBMITTED 반환 → link failed |
| 7 | `test_resolve_unknown_state_inquiry_failure` | Exception → failed | Exception 발생 시 link failed |
| 8 | `test_authenticate_failure_worker_continues` | Auth 실패 → retained | 인증 실패 시 run retained, worker 계속 동작 |
| 9 | `test_broker_adapter_creation_failure_graceful` | 생성 예외 → retained | Adapter 생성 중 예외 → run retained |
| 10 | `test_process_run_with_broker_adapter` | 전체 Run 처리 | Mock adapter로 전체 Process 검증 |
| 11 | `test_process_cycle_summary` | ProcessingResult Summary | resolved/failed/skipped/retained 카운트 정확성 |

### 3.2. 기존 테스트 수정

- **`worker` / `dry_worker` fixture**: `settings: AppSettings` 파라미터 추가
- **6개 테스트**: `TEST_BROKER` → `koreainvestment` 변경, `service.resolve_and_mark` mock → `_build_adapter_for_broker_account` mock으로 전환

### 3.3. 실행 결과

```
28 passed in 0.73s
```

모든 기존 테스트 + 신규 테스트 통과.

---

## 4. Docker 배포

```bash
# Image 재빌드
docker compose build app
# → Layer cache hit, 0.0s 소요

# Container 재시작
docker compose up -d reconciliation-worker
# → Container Recreated, Started
```

### 4.1. /health 확인

```json
{"status":"ok","database":"connected","runtime_mode":"postgres",...}
```

### 4.2. Worker 로그 확인

```
Starting reconciliation worker loop (interval=30s, limit=10, ...)
=== Cycle 1 ===
Found 1 pending reconciliation run(s) to process.
Processing reconciliation run: run_id=... trigger_type=requires_reconciliation
started run without order links, skipping. run_id=... account_id=...
cycle-complete  runs=1 (resolved=0 skipped=1 failed=0 retained=0)  orders=0  elapsed=0.0s
Cycle 1 complete (took 0.0s). Next cycle in 30s ...
```

Worker 정상 기동 확인. Pending Run이 존재하나 Order Link가 없어 Skipped 처리 (정상 동작).

---

## 5. 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────────────────┐
│                       ReconciliationRunProcessor                     │
│                                                                     │
│  process_run(run)                                                   │
│    │                                                                │
│    ├─ _get_broker_account(account_id)                               │
│    │    ├─ account_repo.get(account_id)                             │
│    │    ├─ broker_account_repo.get(account.broker_account_id)       │
│    │    └─ broker_name == "koreainvestment" 확인                    │
│    │                                                                │
│    ├─ _get_or_create_broker(account_id, broker_account)             │
│    │    ├─ _broker_cache[account_id] 확인                           │
│    │    └─ _build_adapter_for_broker_account(...)                   │
│    │         ├─ KISRestClient(api_key, api_secret, ...) 생성        │
│    │         ├─ KoreaInvestmentAdapter(rest_client) 생성            │
│    │         ├─ adapter.authenticate()                              │
│    │         └─ adapter 반환 / None 반환 (실패 시)                  │
│    │                                                                │
│    └─ 각 Order Link에 대해 _process_order_link(...)                 │
│         ├─ adapter.resolve_unknown_state(account_ref, ...)          │
│         ├─ terminal status 확인 (FILLED/CANCELLED 등)               │
│         ├─ resolved → update_link_status(resolved)                  │
│         └─ failed → attach_order_mismatch(failed)                  │
│                                                                     │
│    결과: run status = resolved / failed / reflection_failed         │
│         예외 시: retained (다음 사이클에서 재시도)                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 6. 잠재적 리스크 및 향후 개선 사항

### 6.1. KIS 계정 정보 환경 변수 의존성
- `KIS_API_KEY`, `KIS_API_SECRET`, `KIS_ACCOUNT_NUMBER`, `KIS_ACCOUNT_PRODUCT_CODE` 등이 `.env`에 설정되어야 함
- 설정되지 않으면 `AppSettings()` 생성 시 `ValidationError` 발생 가능
- Worker 시작 전 Pre-flight 검증 로직 추가 고려

### 6.2. Multi-Broker 지원
- 현재 `broker_name == "koreainvestment"`만 지원
- 향후 다른 Broker Adapter 추가 시 `_build_adapter_for_broker_account()`에 분기 로직 필요

### 6.3. Rate Limit Budget 관리
- [`build_kis_budget_manager()`](../src/agent_trading/brokers/rate_limit.py:397)를 통해 Budget Manager 생성 가능하나, 현재 Worker에서는 미사용
- Reconciliation 전용 Budget 할당 고려 (다른 API 호출과의 경합 방지)

### 6.4. Token Cache
- [`KISRestClient`](../src/agent_trading/brokers/koreainvestment/rest_client.py:321)는 `_load_dev_token_cache()` / `_save_dev_token_cache()` 지원
- Worker 재시작 시 Token Cache를 활용하여 불필요한 인증 방지 가능

---

## 7. 결론

KIS BrokerAdapter 통합으로 Reconciliation Worker가 실제 Broker API를 통해 Order 상태를 조회하고 Reconciliation Run을 Resolve/Converge할 수 있게 되었습니다. 모든 테스트 통과, Docker 배포 완료, Worker 정상 기동 확인 완료.
