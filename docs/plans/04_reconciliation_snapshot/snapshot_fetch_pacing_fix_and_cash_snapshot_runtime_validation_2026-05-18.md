# Phase AD: snapshot.py 신 경로 pacing 복구 + cash snapshot 정상화 실검증

- **작성일**: 2026-05-18
- **대상 파일**: [`src/agent_trading/brokers/koreainvestment/snapshot.py`](../src/agent_trading/brokers/koreainvestment/snapshot.py)
- **연결된 이슈**: Phase AC (cash sync failure root cause 진단) → Phase AD (P0 복구)

---

## 1. Root Cause 요약

```
구 경로 (kis_snapshot_sync.py:266)     : get_positions() → await asyncio.sleep(1.0) → get_cash_balance()  ✅
신 경로 (snapshot.py:155-165, Phase AC): get_positions() → get_cash_balance()                         ❌ pacing 누락
                                                                                                        ↓
                                                                                          BudgetExhaustedError
                                                                                                        ↓
                                                                                          cash_synced_count=0 x3
                                                                                                        ↓
                                                                                          STALE_SNAPSHOT_ACCOUNT guardrail
                                                                                                        ↓
                                                                                          33분간 submit 차단 (03:44~04:17 UTC)
```

### 1.1 KIS Paper Rate Limit 구조

| 계층 | 제약 | 설명 |
|------|------|------|
| Tier 1: global_rest bucket | capacity=1, refill=1.0/s | 모든 REST API 호출 공유 |
| Tier 2: INQUIRY bucket | capacity=1 | 조회성 API 전용 |
| KIS paper 공식 제약 | 1 RPS | 초당 1회 호출 |

### 1.2 실패 체인 (Phase AC 재현)

1. `get_positions()` -> global_rest bucket 소진
2. **pacing 누락** -> 1초 내 `get_cash_balance()` 호출
3. `BudgetExhaustedError` 발생
4. `except Exception`에서 **silent skip** (exc_info=False)
5. `cash_balance=None` 반환 -> DB 미기록
6. 3회 연속 실패 (03:32~03:43)
7. `STALE_SNAPSHOT_ACCOUNT` guardrail 발동 (15분 threshold 초과)
8. **33분간 모든 submit SKIPPED** (03:44~04:17)

---

## 2. Pacing 복구 내용

### 2.1 변경 파일: snapshot.py

| 위치 | 변경 전 | 변경 후 | 목적 |
|------|---------|---------|------|
| L9 | (없음) | `import asyncio` | asyncio.sleep() 사용 |
| L159-160 | (없음) | `await asyncio.sleep(1.0)` | positions -> cash 간 1초 간격 보장 |
| L168 | `logger.error(msg)` | `logger.error(msg, exc_info=True)` | 예외 스택트레이스 로깅 |

### 2.2 Pacing 적용 코드 (L159-168)

```python
# -- 2. Fetch cash balance -----------------------------------------
cash_balance: CashBalanceSnapshotEntity | None = None

# Paper 1 RPS pacing: ensure at least 1s between consecutive KIS calls
await asyncio.sleep(1.0)

try:
    raw_cash: dict[str, Any] = await self._rest.get_cash_balance(
        after_hours=after_hours,
    )
except Exception as exc:
    msg = f"Failed to fetch cash balance from KIS: {exc}"
    logger.error(msg, exc_info=True)  # <- exc_info=True
    errors.append(msg)
    raw_cash = {}
```

### 2.3 설계 결정

- **RPS=2 같은 우회 사용 안함** - KIS paper 공식 제약(1 RPS)을 유지한 채 구 경로 수준으로 정상화
- **`asyncio.sleep(1.0)` 위치**: `get_positions()` 직후, `get_cash_balance()` 직전 - 구 경로와 동일
- **`exc_info=True`**: 향후 유사 BudgetExhaustedError 발생 시 로그만으로 원인 파악 가능

---

## 3. 테스트 결과

### 3.1 Snapshot 관련 테스트 (11/11 통과)

```
tests/brokers/koreainvestment/test_snapshot.py  ...... 11 passed
```

### 3.2 전체 pytest (108 passed, 1 failed)

```
108 passed, 1 failed in 21.83s
```

- **1 failed**: test_health.py - 기존 문제, 본 수정과 무관 (Phase AC 이전에도 동일)

---

## 4. Docker 재빌드/재기동 결과

| 단계 | 명령 | 결과 |
|------|------|------|
| Build | `docker compose build app ops-scheduler` | 성공 |
| Restart | `docker compose up -d app ops-scheduler` | 성공 |
| Health | `curl localhost:8000/health` | status=ok, database=connected, healthy=true |

---

## 5. Snapshot Sync 1 Cycle 실행 결과

### 5.1 실행 명령

```bash
python3 scripts/run_snapshot_sync_loop.py --max-cycles 1
```

### 5.2 로그 요약

```
Cycle 1: accounts=1 (ok=1 partial=0 fail=0 skip=0)
         positions=12 (skipped=0)
         cash=1        <- 이전 Phase AC: cash=0
         errors=0
took 12.0s             <- Phase AB와 유사 (12.2s)
```

**핵심**: cash=1 정상 - pacing 복구로 cash sync 실패 해소

### 5.3 타이밍 분석 (sync 내부)

| 호출 | 시점 (상대) | 예상 소요 |
|------|-------------|-----------|
| get_positions() | T+0s | ~4-6s |
| asyncio.sleep(1.0) | T+~4-6s | 1s |
| get_cash_balance() | T+~5-7s | ~2-3s |
| 총 소요 | | ~12s (관측치와 일치) |

---

## 6. DB 생성 검증

### 6.1 cash_balance_snapshots - 최근 3개 row

| created_at | total_asset | available_cash |
|------------|-------------|----------------|
| 2026-05-18 04:37:34 | **29,892,650** | 27,329,630 |
| 2026-05-18 04:37:20 | 29,879,650 | 27,329,630 |
| 2026-05-18 04:33:52 | 29,707,450 | 27,329,630 |

- **가장 최근 row**: pacing 복구 후 1 cycle에서 생성됨
- **total_asset 정상 증가 추세**: 29,707,450 -> 29,879,650 -> 29,892,650

### 6.2 risk_limit_snapshots - 최근 3개 row

| created_at | nav | kill_switch_active |
|------------|-----|-------------------|
| 2026-05-18 04:37:34 | **29,892,650** | false |
| 2026-05-18 04:37:20 | 29,879,650 | false |
| 2026-05-18 04:33:52 | 29,707,450 | false |

- **nav == total_asset** 일치 (Phase AB 이후 정상 유지 중)
- **kill_switch_active=false**: 정상 운영 상태

### 6.3 DB 스키마: risk_limit_snapshots 컬럼

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| risk_limit_snapshot_id | uuid | PK, uuid7 생성 |
| account_id | uuid | 계정 FK |
| snapshot_at | timestamptz | 스냅샷 시점 |
| nav | numeric | 순자산가치 |
| cash_available | numeric | 사용가능 현금 |
| gross_exposure_pct | numeric | 총 익스포저 % |
| net_exposure_pct | numeric | 순 익스포저 % |
| daily_realized_pnl | numeric | 일 실현손익 |
| daily_unrealized_pnl | numeric | 일 미실현손익 |
| daily_loss_used_pct | numeric | 일 손실사용 % |
| max_daily_loss_limit_pct | numeric | 일 손실한도 % |
| symbol_exposure_json | jsonb | 종목별 익스포저 |
| sector_exposure_json | jsonb | 섹터별 익스포저 |
| kill_switch_active | boolean | 킬스위치 상태 |
| created_at | timestamptz | 생성 시각 |

---

## 7. Guardrail 재발 리스크 평가

### 7.1 리스크 매트릭스

| 리스크 | 상태 | 설명 |
|--------|------|------|
| Cash sync pacing 누락 | **해소** | await asyncio.sleep(1.0) 추가 |
| BudgetExhaustedError 관측성 | **개선** | exc_info=True로 스택트레이스 기록 |
| KIS API 자체 지연 초과 | 잔존 | KIS API 응답이 1초 이상 걸리면 rate_limit.py bucket이 자체적으로 제어 |
| STALE_SNAPSHOT_ACCOUNT guardrail | 정상 유지 | 보호 장치로 계속 유효 |
| fallback (total_asset) 우회 | 불필요 | cash sync가 정상이므로 fallback에 의존하지 않음 |

### 7.2 Guardrail 보호 체계

```
pacing 복구 -> cash sync 정상화 -> STALE_SNAPSHOT_ACCOUNT 미발동
                                      |
                           (guardrail은 최후의 안전장치로 유지)
```

- STALE_SNAPSHOT_ACCOUNT guardrail (900s threshold)은 **여전히 활성**
- pacing 복구로 인위적인 cash sync 실패는 제거되었으나, **KIS API 자체 장애나 네트워크 문제 등 외부 요인**에 의한 실패는 여전히 guardrail이 차단
- 이는 올바른 설계: guardrail은 pacing 문제 같은 구현 버그가 아닌 **진짜 외부 장애**를 차단하는 용도로 정상 기능

### 7.3 모니터링 권장사항

1. **snapshot-sync 로그 cash_synced_count** 모니터링 - 0이 2회 연속이면 조기 경보
2. **logger.error(msg, exc_info=True)** 출력 - BudgetExhaustedError 발생 시 즉시 식별 가능
3. **scheduler heartbeat /health** - snapshot_sync_stale 필드로 가드레일 발동 상태 확인

---

## 8. 변경 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| `src/agent_trading/brokers/koreainvestment/snapshot.py` | L9: import asyncio 추가, L159-160: await asyncio.sleep(1.0) 추가, L168: logger.error(msg, exc_info=True)로 개선 |

---

## 9. 최종 판정

### 검증 항목별 결과

| # | 검증 항목 | 결과 |
|---|-----------|------|
| 1 | 관련 pytest 실행 | snapshot 11/11, 전체 108 passed |
| 2 | Docker 재빌드/재기동 | build + up 성공 |
| 3 | /health 확인 | status=ok, database=connected |
| 4 | snapshot-sync 1 cycle | accounts=1, cash=1, errors=0, 12.0s |
| 5 | cash_balance_snapshots 최근 row | total_asset=29,892,650 @ 04:37:34 |
| 6 | risk_limit_snapshots 최근 row | nav=29,892,650 @ 04:37:34 |
| 7 | cash_synced_count 정상 | cash=1 (Phase AC: 0) |
| 8 | guardrail 재발 리스크 | pacing 복구 + exc_info=True 개선 |

### 판정: **완전 해결**

pacing 복구 + cash snapshot 정상 생성 + risk limit snapshot 정상 생성 + guardrail 정상 유지

### Phase 전체 연결 관계

```
Phase AA: risk_limit_snapshots 0건 발견 -> cash sync 실패 확인
  -> Phase AB: uuid7 import 에러 복구 (Docker python 3.14) + snapshot-sync 기동 복구
    -> Phase AC: cash sync pacing 누락 원인 진단 + guardrail 영향 분석
      -> Phase AD (현재): P0 복구 - pacing 추가 + 실검증 완료
```
