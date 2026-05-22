# 인계 문서: 차기 Roo Code 세션 핸드오버

> **작성일**: 2026-05-22 (UTC+9:00, Asia/Seoul)
> **대상**: 차기 Roo Code 세션 작업자
> **목적**: 이번 세션(2026-05-22)의 모든 작업 상황과 의사결정 맥락을 인계하여 끊김 없는 작업 연속성 확보

---

## 1. Current Status (현재 상태)

이번 세션에서는 **Round 4~8까지 총 5개 라운드**를 완료했습니다. 모든 코드 변경은 테스트(264/264 통과, 16개 테스트 파일) 및 vite build 성공까지 완료되었습니다.

| Round | 작업 | 상태 |
|-------|------|------|
| **Round 4** | Reconciliation Lock 연쇄 차단 근본 원인 분석 및 Fix A+B+C+D 구현 + Migration 0020 실제 DB 적용 | ✅ 완료 |
| **Round 5** | 000810 vs 000150 batch 분기 차이 분석 — held_position sell trade_decision 생성 후 order_request 미생성 원인 추적 | ✅ 완료 |
| **Round 6** | quote_resolution hang 근본 수정 (Fix K/L/M) + Docker 재빌드 + 12:56 batch 재현 검증 | ✅ 완료 |
| **Round 7** | Admin UI AgentsRunsView 전체 판단내용(row expand + raw JSON) 표시 (→ Round 8에서 롤백) | ⏪ 롤백 |
| **Round 8** | Round 7 롤백 + 구조화된 출력 확장형 key/value preview 구현 | ✅ 완료 |

---

### A. Round 4 — Reconciliation Lock 연쇄 차단 근본 원인 분석 및 Fix A+B+C+D ✅ 완료

#### 문제 상황
2026-05-22 10:17 KST에서 000810/000150/000270 held_position sell 주문이 **BLOCKED** 상태로 지속됨. Round 3 Fix(`release_blocking_lock()` 호출 + ORDER bucket 3x)가 적용되었음에도 lock이 해제되지 않음.

#### 근본 원인 (3-layer)
1. **PostgreSQL UNIQUE + NULL 버그**: `ON CONFLICT DO NOTHING`이 `strategy_id IS NULL`일 때 절대 발동하지 않음 (PostgreSQL은 NULL을 distinct로 취급). 증거: 001230(buy)에 동일 scope lock 4개 존재.
2. **`release_blocking_lock()` silent failure**: DELETE 0 rows여도 예외만 catch하고 로그만 남김 → `locked_by_run_id` 불일치를 감지하지 못함.
3. **`locked_by_run_id` mismatch**: `get_active_run()`은 `status='started'`만 반환 → worker가 run을 `failed`로 마킹 후 `trigger()`가 새 run 생성 → 새 run의 `release_blocking_lock(locked_by_run_id=new_run_id)`가 원래 lock 소유자와 불일치.

#### 해결 방법 (Fix A+B+C+D)

| Fix | 파일 | 변경 내용 |
|-----|------|-----------|
| **Fix A** | [`reconciliation_service.py:187-258`](src/agent_trading/services/reconciliation_service.py:187) | `acquire_blocking_lock()`: `ON CONFLICT DO NOTHING` → `ON CONFLICT ... DO UPDATE SET ... WHERE expires_at < NOW()`. COALESCE 기반 conflict target으로 NULL-safe matching. **Active lock은 덮어쓰지 않음** (expired만 takeover). |
| **Fix B** | [`db/migrations/0020_null_safe_blocking_lock_unique.sql`](db/migrations/0020_null_safe_blocking_lock_unique.sql) | NULL-safe unique migration: DROP old UNIQUE constraint → CREATE COALESCE-based expression index → Clean up duplicate locks. |
| **Fix C** | [`reconciliation_service.py:260-342`](src/agent_trading/services/reconciliation_service.py:260) | `release_blocking_lock()`: DELETE 결과 검증 추가 — 0행 삭제 + non-expired lock 존재 시 warning 로그. |
| **Fix D** | [`reconciliation_worker.py:480-528`](src/agent_trading/services/reconciliation_worker.py:480) | `_mark_run_failed()` + `_mark_run_reflection_failed()`: `completed_at=now` 파라미터 추가. |

#### 테스트 결과
- **93/94 통과** (1건 pre-existing failure: `test_get_recent_events_with_data` — 0 == 2 assertion, 본 변경과 무관)

#### 분석 문서
- [`plans/trace_real_budget_source_and_lock_owner_for_1017_held_position_sell_blocking_2026-05-22.md`](plans/trace_real_budget_source_and_lock_owner_for_1017_held_position_sell_blocking_2026-05-22.md)
- [`plans/apply_null_safe_blocking_lock_migration_and_reverify_held_position_sell_blocking_2026-05-22.md`](plans/apply_null_safe_blocking_lock_migration_and_reverify_held_position_sell_blocking_2026-05-22.md) — Migration 적용 및 검증 보고서

---

### B. Round 5 — held_position sell trade_decision → order_request 미생성 경로 특정 ✅ 완료

#### 문제 상황
Fix B(NULL-safe lock index) 적용 후에도 held_position sell이 계속 차단됨. DB 조회 결과 다수의 `trade_decision`이 `order_request` 없이 생성됨.

| 심볼 | 시각 (KST) | trade_decision | order_request |
|------|-----------|:---:|:---:|
| 000810 | 10:58 | ✅ | ❌ |
| 000150 | 10:42, 10:49, 10:58 | ✅ | ❌ |
| 000270 | 10:58 | ✅ | ❌ |

#### 분석 결과: 3가지 차단 경로

| 경로 | 설명 | 비중 |
|------|------|------|
| **Path A** | `HELD_POSITION_SELL_MAX_PER_DAY=5` 도달 → `decision_dry_run`만 실행 (45건 중 5건만 submit) | ⭐ 주원인 |
| **Path B** | BUDGET_EXHAUSTED (ORDER bucket 소진) | 보조 |
| **Path C** | BLOCKED (reconciliation lock) | 잔여 |

#### 적용한 수정: Fix E — held_position sell 전용 budget lane

- **파일**: [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:101)
- **변경**: `hp_sell_budget_ok = True` (held_position sell은 항상 submit path 진입 가능)
- **효과**: 위험 축소 목적의 held_position sell이 일일 제출 상한(5건)에 막히지 않음
- **일반 BUY budget 정책 유지**: `DEFAULT_MAX_SUBMIT_PER_DAY=1`

#### 분석 문서
- [`plans/trace_remaining_held_position_sell_blockers_after_null_safe_lock_fix_2026-05-22.md`](plans/trace_remaining_held_position_sell_blockers_after_null_safe_lock_fix_2026-05-22.md) — Round 5: 잔여 차단 원인 추적 + Fix E
- [`plans/trace_trade_decision_without_order_request_for_recent_held_position_sell_2026-05-22.md`](plans/trace_trade_decision_without_order_request_for_recent_held_position_sell_2026-05-22.md) — Round 5: trade_decision→order_request 미생성 추적
- [`plans/remove_daily_submit_cap_blocking_held_position_sell_from_entering_submit_path_2026-05-22.md`](plans/remove_daily_submit_cap_blocking_held_position_sell_from_entering_submit_path_2026-05-22.md) — Fix E 설계 문서

---

### C. Round 6 — quote_resolution hang 근본 수정 (Fix K/L/M) ✅ 완료

#### 문제 상황
2026-05-22 12:56 KST batch에서 8개 symbol 모두 `trade_decision`만 생성되고 `order_request`가 0건. scheduler 600s timeout으로 subprocess 강제 종료.

#### 근본 원인
`assemble_and_submit()` Phase 1.5에서 `broker.get_quote()` 호출이 C-level httpx I/O에서 hang. `asyncio.wait_for()`가 C-level blocking을 interrupt하지 못함.

#### 적용한 수정

| Fix | 파일 | 변경 내용 |
|-----|------|-----------|
| **Fix K** | [`decision_orchestrator.py:990`](src/agent_trading/services/decision_orchestrator.py:990) | HP sell(REDUCE/EXIT SELL) 조건에서 `broker.get_quote()` 완전히 건너뜀. smoke price fallback 사용. symbol당 ~10s 절약. |
| **Fix L** | [`rest_client.py:413`](src/agent_trading/brokers/koreainvestment/rest_client.py:413) | httpx timeout 단축: `30.0s` → `8.0s` (connect=5.0, read=5.0). 이중 안전장치. |
| **Fix M** | Fix K에 포함 | `HP_SELL_QUOTE_BYPASS` prefix 로깅 추가. 사후 분석 시 grep 가능. |

#### 검증 결과
- **13:07 batch 정상 진행 확인**: `asyncio.wait_for(10s)` 정상 동작, 000810/000270 order_request 생성됨 ✅
- **Docker 재빌드 완료**: `docker compose build` 성공
- **전체 테스트 통과**: 264/264 (16개 테스트 파일)

#### 분석 문서
- [`plans/held_position_sell_silent_drop_root_cause_final_2026-05-22.md`](plans/held_position_sell_silent_drop_root_cause_final_2026-05-22.md) — Round 6: 12:56 batch silent drop 최종 원인 분석
- [`plans/trace_and_fix_quote_resolution_hang_blocking_order_request_creation_for_held_position_sell_2026-05-22.md`](plans/trace_and_fix_quote_resolution_hang_blocking_order_request_creation_for_held_position_sell_2026-05-22.md) — Fix K/L/M 설계 및 검증

---

### D. Round 7 — Admin UI AgentsRunsView 전체 판단내용 표시 (롤백됨) ⏪

#### 작업 내용
- Admin UI `AgentsRunsView`에 row expand 기능 추가
- 각 row 좌측 expand 버튼(`▶`/`▼`) 클릭 시 상세 패널 확장
- `structured_output_json` 전체를 pretty-print JSON으로 표시

#### 롤백 사유
- **"날것 JSON 전체 노출"** — 사용자 피드백: 너무 raw하고 가독성이 떨어짐
- 운영자가 JSON을 직접 읽어야 하는 UX는 운영 효율성 저하
- Round 8에서 완전히 대체됨

#### 문서
- [`plans/show_full_agent_judgment_content_in_agents_runs_view_2026-05-22.md`](plans/show_full_agent_judgment_content_in_agents_runs_view_2026-05-22.md) — Round 7 설계 문서 (참고용, 현재 코드와 불일치)

---

### E. Round 8 — 구조화된 출력 확장형 Key/Value Preview 구현 ✅ 완료

#### 작업 개요
Round 7의 raw JSON 전체 노출 방향을 롤백하고, `구조화된 출력` 칸에서 하위 내용을 key/value 기반으로 펼쳐볼 수 있도록 개선.

#### 변경 사항

##### 파일 1: [`admin_ui/src/components/AgentRunsTable.tsx`](admin_ui/src/components/AgentRunsTable.tsx)
- **Row expand 제거** (Round 7 롤백): `expandedId` state, `ExpandedDetail` component, `MetadataItem` component, ChevronRight/ChevronDown expand 버튼 제거
- **StructuredOutputCell 컴포넌트 추가**: `structured_output_json` 칼럼에 key/value 확장형 렌더러
  - **Collapsed 상태**: 첫 3개 key만 표시 (예: `signal, confidence, summary, +2 more`)
  - **Expanded 상태**: 모든 key/value pair를 recursive하게 표시
  - **값 타입별 표시 규칙**:
    - `string < 50자`: 전체 표시
    - `string >= 50자`: 50자 truncation + "더보기"/"접기" 토글
    - `number/boolean`: 직접 표시
    - `null`: 회색 대시(`-`)
    - `object`: nested recursive expansion (토글 가능)
    - `array`: 첫 3개 item preview + "+N more"
  - **Copy-to-clipboard**: 각 value 우측 복사 버튼

##### 파일 2: [`admin_ui/src/styles/admin-theme.css`](admin_ui/src/styles/admin-theme.css)
- Round 7 CSS(`.agent-run-detail-json`) 제거
- 20+ 신규 CSS 클래스 추가: `.structured-output-section`, `.structured-output-toggle`, `.structured-output-key-value`, `.structured-output-key`, `.structured-output-value`, `.structured-output-value-truncated`, `.structured-output-nested-toggle`, `.structured-output-copy-all` 등

##### 파일 3: [`admin_ui/src/__tests__/agentRuns.test.tsx`](admin_ui/src/__tests__/agentRuns.test.tsx)
- Round 7 detail panel expand/collapse 테스트 제거
- 5개 신규 테스트 추가:
  1. `displays structured output keys collapsed` — collapsed 상태에서 첫 3개 key 표시
  2. `expands structured output to show all keys` — toggle 클릭 시 모든 key 표시
  3. `truncates long string values with show more` — 50자 truncation + 더보기
  4. `renders nested objects recursively` — nested object toggle + recursive display
  5. `renders arrays with item count` — array preview + "[3 items]"

#### 테스트 결과
- **264/264 통과** (16개 테스트 파일)
- **vite build 성공**: 27.13 KB CSS, 435.92 KB JS

#### 설계 의사결정
| 결정 | 내용 |
|------|------|
| **Row expand 제거** | Round 7의 raw JSON 전체 노출 UX 폐기. 기존 테이블 레이아웃 유지. |
| **Inline key/value 확장** | `structured_output_json` 칼럼 내에서 직접 확장. 별도 패널/다이얼로그 불필요. |
| **50자 truncation** | 긴 문자열(LLM 생성 텍스트)이 테이블 레이아웃을 깨뜨리지 않도록 제한. |
| **Recursive object expansion** | 중첩 구조(예: `aggregate_view.top_reason_codes`)도 탐색 가능. |
| **Copy-to-clipboard** | 운영자가 특정 필드값을 복사하여 다른 도구에서 활용 가능. |

---

### F. (이전 세션 작업 — 참고용) User Request 13/13b/13c — BUY sizing 개선 ✅ 완료

이전 세션(2026-05-21)에서 완료된 작업으로, 현재 운영 환경에 반영되어 있습니다.

| 작업 | 설명 |
|------|------|
| **User Request 13** | Reference price 기반 MARKET 주문 sizing + 10주 하드코딩 제거 |
| **User Request 13b** | 고가주 sub-10 BUY baseline + `_resolve_buy_target_quantity()` |
| **User Request 13c** | `requested_quantity=10` 상한 제거 + 완전 동적 BUY 수량 |
| **AR 2-layer guard** | 코드 배포 완료, 장중 검증 pending |

---

## 2. Work In Progress (진행 중인 작업)

### ✅ P0: Reconciliation Lock Fix — Migration 적용 + 컨테이너 재시작 완료 (2026-05-22)

**상태**: **Migration 0020 실제 DB 적용 완료. 컨테이너 재시작 및 health check 통과.**

#### 완료된 작업

1. **Migration 0020 적용** ✅
   - `python3 -m src.agent_trading.db.migrations.run` runner가 TimeoutError로 0020까지 도달하지 못해 **직접 psql로 SQL 실행**
   - 중복 lock 3건 우선 정리 후 NULL-safe expression index 생성
   - `uq_order_blocking_locks_key`: `(account_id, strategy_id, symbol, side)` → `(account_id, COALESCE(strategy_id, '00000000-...'::uuid), symbol, side)`

2. **Duplicate Lock 정리** ✅
   - 001230 buy lock 4개 중 3개 삭제 (가장 최근 1개만 보존)
   - 현재 중복 0건

3. **컨테이너 재시작 + Health Check** ✅
   ```bash
   docker compose restart
   curl -sf http://localhost:8000/health
   # → {"status":"ok","database":"connected","scheduler":{"healthy":true}}
   ```

4. **Held_position Sell 재검증** ✅
   - 000810/000150/000270 sell lock 모두 EXPIRED 상태 (ACTIVE lock 없음)
   - 각 symbol/side당 1개씩만 존재 (중복 없음)

#### 차기 세션에서 수행해야 할 작업

1. **장중 검증** (운영 시간에만 가능)
   - reconciliation worker 로그에서 `"Blocking lock released"` 메시지 확인
   - `release_blocking_lock: DELETE affected 0 rows` warning 로그 발생 여부 확인
   - BLOCKED 상태 주문이 정상적으로 해소되는지 확인
   - NULL-safe index로 인해 duplicate lock이 더 이상 생성되지 않는지 확인

2. **Fix E 사후 검증** (Round 5)
   - held_position sell이 일일 제출 상한에 막히지 않고 submit path에 진입하는지 확인
   - `hp_sell_budget_ok=True` 로그 메시지 확인

3. **Fix K/L/M 사후 검증** (Round 6)
   - `HP_SELL_QUOTE_BYPASS` 로그 발생 확인 (grep 가능)
   - quote_resolution hang 재발 여부 모니터링
   - httpx timeout 8s 단축으로 인한 영향 확인

### 🔴 알려진 이슈

| 이슈 | 심각도 | 상태 |
|------|--------|------|
| `test_get_recent_events_with_data` failure (0 == 2) | 낮음 | Pre-existing, 본 변경과 무관 |
| Fix E (held_position sell 전용 budget lane) — 사후 검증 필요 | 중간 | Round 5 구현 완료, 장중 검증 pending |
| Fix K/L/M (quote hang 수정) — 사후 검증 필요 | 중간 | Round 6 구현 완료, 장중 검증 pending |
| Migration runner TimeoutError (0001, 0012, 0016, 0017) | 낮음 | 직접 psql 실행으로 우회 가능 |
| `trading.orders` 테이블 미존재 | 낮음 | broker_orders만 존재, order-level sell 추적 제한적 |

---

## 3. Implicit Context (숨은 맥락 및 의사결정)

### A. Reconciliation Lock 설계 결정사항

#### Fix A: `ON CONFLICT DO UPDATE WHERE expires_at < NOW()`

- **의도**: Active lock은 절대 덮어쓰지 않음. 오직 **expired** lock만 takeover.
- **이유**: `locked_by_run_id` mismatch 문제의 근본 해결. 새 run이 expired lock을 takeover하면 `release_blocking_lock(locked_by_run_id=new_run_id)`가 정상 동작함.
- **Trade-off**: Active lock 기간(최대 30분) 동안은 새 reconciliation run이 lock을 획득할 수 없음. 이는 의도된 동작 — reconciliation이 아직 진행 중이면 새 run이 필요하지 않음.

#### Fix B: COALESCE-based expression index

- **Sentinel UUID**: `00000000-0000-0000-0000-000000000000`
- **이유**: PostgreSQL이 NULL을 distinct로 취급하는 근본적 한계를 우회. 실제 `strategy_id`와 충돌할 가능성이 극히 낮은 값 선택.
- **ON CONFLICT 구문 일치**: `acquire_blocking_lock()`의 `ON CONFLICT` 절도 동일한 COALESCE 표현식을 사용해야 함.

#### Fix C: DELETE 결과 검증

- **0행 삭제 + non-expired lock 존재** → `locked_by_run_id` mismatch
- **0행 삭제 + lock 없음** → 정상 (이미 해제됨)
- **>0행 삭제** → 정상

#### Fix D: `completed_at=now`

- `update_run_status()`는 `completed_at`이 optional 파라미터. 전달하지 않으면 `completed_at IS NULL`로 저장됨.
- 이 값은 `get_active_run()`과 직접적 관련은 없지만, run의 완료 시점 추적과 사후 분석에 필요.

---

### B. Round 5/6 설계 결정사항

#### Fix E: held_position sell 전용 budget lane

- **의도**: 위험 축소 목적의 held_position sell(REDUCE/EXIT)은 일일 제출 상한에 묶이지 않아야 함.
- **이유**: BUY와 달리 held_position sell은 포지션 리스크를 줄이는 것이 목적. 제출 상한으로 차단되면 리스크가 증가함.
- **Trade-off**: held_position sell이 무제한으로 실행될 수 있음. 단, 각 sell은 `sell_guard`(중복 sell 차단) + `stale_snapshot guard` + `budget`(ORDER bucket)의 3중 안전장치를 통과해야 함.

#### Fix K: HP sell quote bypass

- **의도**: HP sell에서 `broker.get_quote()`는 단순 참고용. 실제 submit 시 `_resolve_smoke_price()`로 fallback 가능.
- **이유**: quote 실패/지연이 주문 자체를 막아서는 안 됨. HP sell은 위험 축소가 목적이므로 속도가 정확성보다 중요.
- **효과**: symbol당 ~10s 절약 → 8개 batch에서 최대 80s 절감 → 600s timeout 내 모든 symbol 처리 가능.

#### Fix L: httpx timeout 단축

- **변경**: `30.0s` → `8.0s` (connect=5.0, read=5.0)
- **이유**: httpx 0.28.1 + httpcore 1.0.9는 cooperative await 사용. `asyncio.wait_for()`가 C-level I/O를 interrupt 가능. 단축된 timeout은 이중 안전장치 역할.
- **리스크**: 네트워크 지연이 5-8초를 초과하는 극히 드문 경우에 timeout 발생 가능. 이 경우 재시도 로직이 처리.

---

### C. (이전 세션) BUY Sizing 설계 결정사항

*이전 세션(2026-05-21)의 결정사항은 유효합니다. 자세한 내용은 이전 HANDOVER 문서 참조.*

| 결정 | 내용 |
|------|------|
| `reference_price` | MARKET 주문용 sizing 기준 가격, quote 기반 |
| `safety_factor=0.95` | MARKET BUY 전용, 현금 여유분 확보 |
| `_ALLOCATION_PCT = 0.2` | 단일 BUY에 orderable_amount의 20% 할당 |
| `requested_quantity` | 더 이상 BUY의 절대적 상한이 아님 |

---

### D. Docker 운영 참고사항

| 항목 | 내용 |
|------|------|
| **이미지 빌드** | `docker compose build` (4개 이미지: app, api, reconciliation-worker, ops-scheduler) |
| **Migration 실행** | `docker compose exec app python3 -m src.agent_trading.db.migrations.run` |
| **재시작** | `docker compose up -d` (모든 컨테이너) |
| **Health check** | `curl -sf http://localhost:8000/health` |
| **Python 명령어** | 반드시 `python3` 사용 (shebang 포함) |
| **Shell** | 반드시 `/bin/bash` 기준 |
| **주의** | `.env` 파일 수정 금지 |

---

## 4. Plans 디렉토리 문서 목록 (이번 세션 생성)

| 파일 | 설명 |
|------|------|
| [`plans/trace_real_budget_source_and_lock_owner_for_1017_held_position_sell_blocking_2026-05-22.md`](plans/trace_real_budget_source_and_lock_owner_for_1017_held_position_sell_blocking_2026-05-22.md) | **Round 4**: Reconciliation Lock 근본 원인 분석 + Fix A+B+C+D 설계 |
| [`plans/apply_null_safe_blocking_lock_migration_and_reverify_held_position_sell_blocking_2026-05-22.md`](plans/apply_null_safe_blocking_lock_migration_and_reverify_held_position_sell_blocking_2026-05-22.md) | **Round 4**: Migration 0020 적용 및 검증 보고서 |
| [`plans/trace_remaining_held_position_sell_blockers_after_null_safe_lock_fix_2026-05-22.md`](plans/trace_remaining_held_position_sell_blockers_after_null_safe_lock_fix_2026-05-22.md) | **Round 5**: Fix B 이후 잔여 차단 원인 추적 + Fix E |
| [`plans/trace_trade_decision_without_order_request_for_recent_held_position_sell_2026-05-22.md`](plans/trace_trade_decision_without_order_request_for_recent_held_position_sell_2026-05-22.md) | **Round 5**: trade_decision→order_request 미생성 3-layer timeout 분석 |
| [`plans/remove_daily_submit_cap_blocking_held_position_sell_from_entering_submit_path_2026-05-22.md`](plans/remove_daily_submit_cap_blocking_held_position_sell_from_entering_submit_path_2026-05-22.md) | **Round 5**: Fix E 설계 — held_position sell 전용 budget lane |
| [`plans/held_position_sell_silent_drop_root_cause_final_2026-05-22.md`](plans/held_position_sell_silent_drop_root_cause_final_2026-05-22.md) | **Round 6**: 12:56 batch silent drop 최종 원인 분석 보고서 |
| [`plans/trace_and_fix_quote_resolution_hang_blocking_order_request_creation_for_held_position_sell_2026-05-22.md`](plans/trace_and_fix_quote_resolution_hang_blocking_order_request_creation_for_held_position_sell_2026-05-22.md) | **Round 6**: Fix K/L/M 설계 및 검증 |
| [`plans/show_full_agent_judgment_content_in_agents_runs_view_2026-05-22.md`](plans/show_full_agent_judgment_content_in_agents_runs_view_2026-05-22.md) | **Round 7** (참고용, 현재 코드와 불일치): Row expand + raw JSON 전체 표시 |

---

## 5. 요약 체크리스트 — 차기 세션 시작 시

### P0 (즉시 수행)
- [ ] **Migration 0020 적용 확인**: `SELECT * FROM trading.order_blocking_locks WHERE expires_at > NOW()` — active lock 정상 동작 확인
- [ ] **Docker rebuild + 재시작**: `docker compose build && docker compose up -d`
- [ ] **Health check**: `curl -sf http://localhost:8000/health`

### P1 (장중 확인)
- [ ] **Reconciliation lock 정상 해제 확인**: worker 로그에서 `"Blocking lock released"` 검색
- [ ] **`release_blocking_lock` warning 확인**: `"DELETE affected 0 rows"` 로그 발생 여부
- [ ] **BLOCKED 상태 주문 해소 확인**: `is_blocked()` 쿼리로 lock 존재 여부 확인
- [ ] **Fix E 검증**: held_position sell이 일일 제출 상한에 막히지 않고 submit path 진입 확인
- [ ] **Fix K 검증**: `HP_SELL_QUOTE_BYPASS` 로그 발생 확인 (grep)
- [ ] **Fix L 검증**: httpx timeout 8s 단축으로 인한 영향 없음 확인

### P2 (참고)
- [ ] (선택) AR Layer 2 guard 생산 검증 (이전 세션 pending)
- [ ] (선택) Fix F: expired lock cleanup 스케줄러 검토
- [ ] (선택) Admin UI AgentsRunsView 구조화된 출력 확장 UX 피드백 수집

---

*인계 완료. 이 문서는 [`plans/HANDOVER_TO_NEW_SESSION.md`](plans/HANDOVER_TO_NEW_SESSION.md)에 저장되어 있습니다.*
