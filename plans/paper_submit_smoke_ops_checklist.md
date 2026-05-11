# Paper Submit Smoke — 운영 체크리스트 / 실행 절차

> **목적**: KIS paper broker 대상 `submit_order()` 경로 검증을 위한 재현 가능한 운영 절차 문서.
> **대상 독자**: Roo / Codex / 사람 운영자
> **원칙**: Paper와 Live는 동일 시스템의 실행 모드 차이(`config/env` 스위치)이며, 본 문서는 **paper mode** 전용 절차를 다룸.

---

## 목차

1. [전체 실행 맵](#1-전체-실행-맵)
2. [사전 준비: 환경 변수 일괄 로드](#2-사전-준비-환경-변수-일괄-로드)
3. [Phase 0: Pre-Flight Check](#3-phase-0-pre-flight-check)
4. [Phase 1: Snapshot Sync](#4-phase-1-snapshot-sync)
5. [Phase 1.5: Synthetic Seed (옵션)](#5-phase-15-synthetic-seed-옵션)
6. [Phase 2: Dry-Run 검증](#6-phase-2-dry-run-검증)
7. [Phase 2.5: KIS_SMOKE_PRICE 설정](#7-phase-25-kis_smoke_price-설정)
8. [Phase 3: Submit Smoke 실행](#8-phase-3-submit-smoke-실행)
9. [Phase 4: Post-Submit 검증](#9-phase-4-post-submit-검증)
10. [Phase 5: Cleanup (옵션)](#10-phase-5-cleanup-옵션)
11. [실수하기 쉬운 포인트 — Checklist](#11-실수하기-쉬운-포인트--checklist)
12. [성공/실패 기준](#12-성공실패-기준)
13. [Failure Branch 정리](#13-failure-branch-정리)
14. [참고: 과거 실행 이력](#14-참고-과거-실행-이력)

---

## 1. 전체 실행 맵

```mermaid
flowchart TD
    A[사전 준비: env vars 로드] --> B[Phase 0: Pre-Flight Check]
    B --> C{env 정상?}
    C -->|No| D[수동 env 재설정]
    D --> B
    C -->|Yes| E[Phase 1: Snapshot Sync]
    E --> F[Phase 1.5: Synthetic Seed<br>옵션]
    F --> G[Phase 2: Dry-Run 검증]
    G --> H{KIS_SMOKE_PRICE 설정?}
    H -->|No| I[Phase 2.5: KIS_SMOKE_PRICE 설정]
    I --> H
    H -->|Yes| J[Phase 3: Submit Smoke]
    J --> K{AI 결정 APPROVE?}
    K -->|HOLD/WATCH/REJECT<br>~40%| L[재시도 1회]
    L --> K
    K -->|APPROVE ~60%| M{snapshot fresh?}
    M -->|No| N[Snapshot Sync 재실행]
    N --> J
    M -->|Yes| O[Broker Submit 실행]
    O --> P{ODNO 발급?}
    P -->|No| Q[Phase 4 에러 분석]
    P -->|Yes| R[Phase 4: Post-Submit 검증]
    R --> S[Phase 5: Cleanup<br>옵션]
```

---

## 2. 사전 준비: 환경 변수 일괄 로드

### 2-A. `.env` 파일에서 로드 (권장)

```bash
set -a; source /workspace/agent_trading/.env; set +a
```

### 2-B. 필수 env vars 목록

| 변수명 | 필수 | 값 예시 | 용도 |
|--------|------|---------|------|
| `KIS_ENV` | ✅ | `paper` | KIS API endpoint 결정 (paper/live) |
| `DATABASE_URL` | ✅ | `postgresql://...` | Postgres 연결 (`.env`에 없으면 shell export) |
| `KIS_API_KEY` | ✅ | `PS...` | KIS paper API key |
| `KIS_API_SECRET` | ✅ | `...` | KIS paper API secret |
| `KIS_ACCOUNT_NUMBER` | ✅ | `50186448` | KIS paper 계좌번호 |
| `KIS_ACCOUNT_PRODUCT_CODE` | ✅ | `01` | KIS paper 계좌상품코드 (=01) |
| `DEEPSEEK_API_KEY` | ✅ | `sk-...` | DeepSeek LLM API key |
| `DEEPSEEK_BASE_URL` | ✅ | `https://api.deepseek.com` | DeepSeek LLM endpoint |
| `DEEPSEEK_MODEL_ID` | ✅ | `deepseek-chat` | ⚠️ `deepseek-v4-pro`는 **사용 금지** (empty response) |
| `DEEPSEEK_TIMEOUT_SECONDS` | 권장 | `120` | 기본 60초 → FDC ReadTimeout 방지 |
| `KIS_PAPER_REST_RPS` | ✅ | `2` | ⚠️ `1`이면 snapshot sync **실패** (Global REST cap 소진) |
| `KIS_DEV_TOKEN_CACHE_ENABLED` | 권장 | `true` | Token cache 활성화 (paper 전용) |
| `ENABLE_KIS_PAPER_SUBMIT_SMOKE` | ✅ | `true` | Submit smoke opt-in gate |
| `KIS_SMOKE_PRICE` | Smoke 전용 | `268500` | Submit smoke용 price override (Phase 2.5에서 설정) |

### 2-C. 필수 env vars 누락 확인

```bash
echo "=== === Env Check === ==="
echo "KIS_ENV=${KIS_ENV:-<MISSING>}"
echo "DATABASE_URL=${DATABASE_URL:+set (length ${#DATABASE_URL})}/${DATABASE_URL:-<MISSING>}"
echo "KIS_API_KEY=${KIS_API_KEY:+set (length ${#KIS_API_KEY})}/${KIS_API_KEY:-<MISSING>}"
echo "KIS_API_SECRET=${KIS_API_SECRET:+set (length ${#KIS_API_SECRET})}/${KIS_API_SECRET:-<MISSING>}"
echo "KIS_ACCOUNT_NUMBER=${KIS_ACCOUNT_NUMBER:-<MISSING>}"
echo "KIS_ACCOUNT_PRODUCT_CODE=${KIS_ACCOUNT_PRODUCT_CODE:-<MISSING>}"
echo "DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:+set}/${DEEPSEEK_API_KEY:-<MISSING>}"
echo "DEEPSEEK_BASE_URL=${DEEPSEEK_BASE_URL:-<MISSING>}"
echo "DEEPSEEK_MODEL_ID=${DEEPSEEK_MODEL_ID:-<MISSING>}"
echo "DEEPSEEK_TIMEOUT_SECONDS=${DEEPSEEK_TIMEOUT_SECONDS:-<MISSING>}"
echo "KIS_PAPER_REST_RPS=${KIS_PAPER_REST_RPS:-<MISSING>}"
echo "KIS_DEV_TOKEN_CACHE_ENABLED=${KIS_DEV_TOKEN_CACHE_ENABLED:-<MISSING>}"
echo "ENABLE_KIS_PAPER_SUBMIT_SMOKE=${ENABLE_KIS_PAPER_SUBMIT_SMOKE:-<MISSING>}"
echo "KIS_SMOKE_PRICE=${KIS_SMOKE_PRICE:-<MISSING>}"
echo "=== === End === ==="
```

### ⚠️ 실수 포인트 #1: `DATABASE_URL` shell scope

`.env` 파일에 `DATABASE_URL`이 **없을 수 있음**. 이 경우 `.env` 로드만으로는 설정되지 않으므로, **shell export가 필요**:

```bash
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/agent_trading"
```

또는 `.env`에 명시적으로 추가.

---

## 3. Phase 0: Pre-Flight Check

### 3-A. Paper 계정 UUID 조회

```bash
cd /workspace/agent_trading
python3 -c "
import asyncio
from agent_trading.db.connection import create_pool

async def find_paper_accounts():
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            \"SELECT account_id, account_alias, environment, account_masked FROM accounts WHERE environment = 'paper'\"
        )
        for r in rows:
            print(f'UUID: {r[\"account_id\"]}  alias: {r[\"account_alias\"]}  env: {r[\"environment\"]}  masked: {r[\"account_masked\"]}')
    await pool.close()

asyncio.run(find_paper_accounts())
"
```

> **예상 출력**: `UUID: a44a02d1-7f32-5a62-99f7-235abeb58284  alias: Entrypoint Paper  env: paper  masked: ****6448`
> 이 UUID는 [`scripts/run_orchestrator_once.py`](scripts/run_orchestrator_once.py:63)의 `ACCOUNT_ID` 상수와 일치해야 함.

### 3-B. KIS endpoint connectivity

```bash
python3 -c "
import socket
host, port = 'openapivts.koreainvestment.com', 29443
try:
    s = socket.create_connection((host, port), timeout=5)
    s.close()
    print(f'{host}:{port} ✅ reachable')
except Exception as e:
    print(f'{host}:{port} ❌ {e}')
"
```

### 3-C. DB connectivity

```bash
python3 -c "
import asyncio
from agent_trading.db.connection import create_pool

async def check_db():
    pool = await create_pool()
    async with pool.acquire() as conn:
        ver = await conn.fetchval('SELECT version()')
        print(f'DB connected: {ver[:30]}...')
    await pool.close()

asyncio.run(check_db())
"
```

### 3-D. Token cache 확인

```bash
ls -la /workspace/agent_trading/.cache/kis_token.json 2>&1 || echo "Token cache not found"
```

> 없어도 KISRestClient가 자동 발급하므로 **blocker 아님**. 단, 첫 실행 시 token 발급에 1회 API call이 추가됨.

### 3-E. Paper Gate 평가 (옵션 — submit smoke의 절대 blocker 아님)

```bash
# ACCOUNT_ID는 3-A에서 조회한 값으로 대체
python3 -c "
import asyncio, json
from datetime import date
from uuid import UUID
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.paper_gate import PaperGateService

ACCOUNT_ID = UUID('a44a02d1-7f32-5a62-99f7-235abeb58284')

async def evaluate():
    async with postgres_runtime() as runtime:
        repos = runtime['repositories']
        settings = runtime['settings']
        gate = PaperGateService(repos=repos, settings=settings)
        result = await gate.evaluate(
            account_id=ACCOUNT_ID,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 5, 10),
        )
        print(f'Overall: {result.overall_status.value}')
        for c in result.checks:
            print(f'  [{c.status.value}] {c.code}: {c.message} (val={c.measured_value}, thr={c.threshold})')

asyncio.run(evaluate())
"
```

> **참고**: `filled order 부족 WARN`은 예상된 현상이며 submit smoke의 절대 blocker가 아님.

### ⚠️ 실수 포인트 #2: Pre-Flight 생략

Pre-Flight Check은 **건너뛰면 안 됨**. 특히 `KIS_ENV=live` 상태에서 실행 시 **실제 계좌로 오발송** 위험이 있음. `KIS_ENV=paper`를 반드시 확인할 것.

---

## 4. Phase 1: Snapshot Sync

### 4-A. 단발 실행 (smoke 전용)

```bash
cd /workspace/agent_trading

# KIS_PAPER_REST_RPS=2 필수 (Phase 1-C에서 RPS=1 실패 경험)
export KIS_PAPER_REST_RPS=2

python3 scripts/sync_kis_snapshots.py --all --env paper --format json
```

### 4-B. 성공 기준

| 항목 | 기준 |
|------|------|
| Exit code | `0` |
| `failed` | `0` |
| `total_positions_synced` | `>= 0` (계좌 상황에 따라 0 가능) |
| `total_cash_synced` | `>= 0` |

### 4-C. 실패 시 대응

| 증상 | 원인 | 조치 |
|------|------|------|
| `positions_synced=0, errors: RateLimit` | `KIS_PAPER_REST_RPS=1` → Global REST cap 소진 | `KIS_PAPER_REST_RPS=2`로 재실행 |
| Token 관련 에러 | Token cache 만료 또는 API key 오류 | `.cache/kis_token.json` 삭제 후 재시도 |
| `Account not found` | DB에 paper account 미등록 | `run_orchestrator_once.py` 1회 실행 (seed 자동) 후 재시도 |

### ⚠️ 실수 포인트 #3: `KIS_PAPER_REST_RPS=1`로 snapshot sync 실패

[`kis_paper_order_phase1_execution.md`](plans/kis_paper_order_phase1_execution.md:42) 참조. RPS=1은 Global REST cap(2 RPS)을 순간적으로 소진하여 snapshot sync가 실패함. **반드시 RPS=2로 설정**.

---

## 5. Phase 1.5: Synthetic Seed (옵션)

> **목적**: AI Agent가 Actionable Decision을 내리기에 충분한 데이터가 없을 경우, synthetic instrument + event를 주입.
> **필요 조건**: Snapshot sync로도 AI가 HOLD/WATCH만 반복할 때 사용.
> **참고 문서**: [`paper_submit_smoke_scenario.md`](plans/paper_submit_smoke_scenario.md:731)

### 5-A. Seed 실행

```bash
cd /workspace/agent_trading

# env vars 로드 후
python3 scripts/seed_smoke_test.py
```

### 5-B. Seed가 INSERT하는 데이터

| 테이블 | 건수 | 식별자 |
|--------|------|--------|
| [`instruments`](db/migrations/0001_initial_schema.sql) | 1 row | `symbol=005930, market=KRX` |
| [`external_events`](db/migrations/0006_add_external_event_data.sql) | 1 row | `event_type=technical_setup, direction=bullish, purpose=smoke_test` |

### 5-C. 재시도 안전성

`seed_smoke_test.py`는 `symbol + market` 기준으로 **중복 체크 후 SKIP**하므로, 여러 번 실행해도 UniqueViolation이 발생하지 않음.

### 5-D. Cleanup (Phase 5에서 설명)

`metadata->>'purpose' = 'smoke_test'` 조건으로 DELETE하므로, seed와 동일 metadata를 가진 row만 안전하게 삭제됨.

### ⚠️ 실수 포인트 #4: Seed 후 cleanup 누락

Synthetic 데이터가 production DB에 영구 남지 않도록, smoke 종료 후 반드시 `--cleanup` 실행할 것. 단, `instruments`의 005930/KRX는 정식 instrument일 경우 삭제되지 않음 (`is_active=true`인 정식 데이터는 metadata 조건과 무관하게 유지).

---

## 6. Phase 2: Dry-Run 검증

> **목적**: 3개 AI Agent (EI, AR, FDC)가 정상 동작하고 decision_type이 `APPROVE`인지 확인. Broker submit은 수행하지 않음.

### 6-A. Dry-run 실행

```bash
cd /workspace/agent_trading

python3 scripts/run_orchestrator_once.py --dry-run --output text
```

### 6-B. 성공 기준

| 항목 | 기준 |
|------|------|
| Exit code | `0` |
| `decision_type` | `APPROVE` (HOLD/WATCH는 sizing skip) |
| `sizing_quantity` | `> 0` (sizing skip이 아닐 것) |
| AI Agent 에러 없음 | 각 agent가 정상 응답 반환 |
| `UniqueViolationError` 없음 | `correlation_id` 중복 없음 (uuid4 + savepoint로 해소) |

### 6-C. 2회 연속 확인 (권장)

AI 결정에는 **확률성**이 있으므로, dry-run을 2회 실행하여 일관성을 확인:

```bash
python3 scripts/run_orchestrator_once.py --dry-run
echo "--- 2nd run ---"
python3 scripts/run_orchestrator_once.py --dry-run
```

### 6-D. Dry-run 실패 시 진단

| 증상 | 원인 | 조치 |
|------|------|------|
| `EventInterpretationAgent failed` | DeepSeek API key 오류 또는 model ID 오류 | `DEEPSEEK_MODEL_ID=deepseek-chat` 확인, API key 재설정 |
| `FinalDecisionComposer timed out` | `DEEPSEEK_TIMEOUT_SECONDS` 부족 | 120s 이상으로 증가 |
| HOLD/WATCH만 반복 | Synthetic seed 부족 | Phase 1.5 Seed 실행 후 재시도 |
| `decision_context_id` 없음 | DB FK chain 미존재 | 자동 seed가 수행되므로 1회 더 시도 |

### ⚠️ 실수 포인트 #5: `DEEPSEEK_MODEL_ID=deepseek-v4-pro`

**절대 사용 금지**. [`kis_paper_order_phase1_execution.md`](plans/kis_paper_order_phase1_execution.md:94) 참조. `deepseek-v4-pro`는 HTTP 200을 반환하지만 **empty response**를 반환하여 `JSONDecodeError` 발생. 반드시 `deepseek-chat` 사용.

---

## 7. Phase 2.5: KIS_SMOKE_PRICE 설정

> **목적**: KIS paper broker가 accept 가능한 LIMIT price 설정.  
> **참고**: [`paper_submit_smoke_cleanup.md`](plans/paper_submit_smoke_cleanup.md:68) 참조.

### 7-A. Price 설정

```bash
export KIS_SMOKE_PRICE=268500
```

> `268500` = 005930 삼성전자 **전일종가**(`prdy_clpr`). KIS paper 상/하한가 이내에서 broker accept가 검증된 유일한 값.

### 7-B. Price 결정 로직

[`_resolve_smoke_price()`](scripts/run_orchestrator_once.py:80)의 우선순위:

```
1. KIS_SMOKE_PRICE env var → 해당 Decimal (smoke 검증 완료)
2. fallback → Decimal("50000") → KIS price validation error (msg_cd=40270000)
```

### 7-C. 경고: env 미설정 시

`KIS_SMOKE_PRICE`가 설정되지 않으면 기본값 `50000`이 사용되며, 이는 KIS 하한가(`187,950`)를 크게 밑돌아 `msg_cd=40270000` 에러 발생. [`run_orchestrator_once.py`](scripts/run_orchestrator_once.py:330)에서 경고 로그 출력.

### ⚠️ 실수 포인트 #6: `KIS_SMOKE_PRICE` 미설정

env var를 설정하지 않고 `--submit` 실행 시, default price=50000으로 submit되어 `msg_cd=40270000`(price validation error) 발생. 반드시 `KIS_SMOKE_PRICE`를 설정할 것.

---

## 8. Phase 3: Submit Smoke 실행

> **목적**: Full pipeline (assemble → validate → create_order → submit_order) 실행.  
> **opt-in 조건**: `ENABLE_KIS_PAPER_SUBMIT_SMOKE=true` 필요.

### 8-A. Submit 실행

```bash
cd /workspace/agent_trading

# 필수: KIS_SMOKE_PRICE 설정
export KIS_SMOKE_PRICE=268500

python3 scripts/run_orchestrator_once.py --submit --output text
```

### 8-B. 성공 기준

| 항목 | 기준 |
|------|------|
| Exit code | `0` |
| `status` | `SUBMITTED` |
| `broker_native_order_id` (ODNO) 발급 | UUID 형식의 broker 주문번호 |
| `order_status` | `SUBMITTED` |

### 8-C. AI 결정 확률성 인지

**과거 실행 통계** ([`kis_paper_submit_price_fix_report.md`](plans/kis_paper_submit_price_fix_report.md:65) 참조):

| 결정 | 비율 | 액션 |
|------|------|------|
| `APPROVE` → SUBMITTED | ~60% | ✅ 성공 |
| `HOLD` | ~10% | ⏳ 재시도 |
| `WATCH` | ~20% | ⏳ 재시도 |
| `REJECT` | ~10% | ⏳ 재시도 |

> AI 결정 확률성으로 인해 1회 시도에서 APPROVE가 나오지 않을 수 있음. **최대 3회 재시도 정책** 적용.

### 8-D. 재시도 정책

1. 1회 시도: `--submit` 실행
2. `APPROVE` → 성공, 종료
3. `HOLD/WATCH/REJECT` → **최대 2회 추가 재시도** (총 3회)
4. 그래도 실패 → AI Agent 입력 데이터 문제 진단 (Phase 1.5 Seed 고려)

> **주의**: 각 시도마다 새로운 `correlation_id`로 broker submit이 발생하여, 실제 주문이 생성됨 (paper 환경이므로 무해). 과거 실행에서 10회 시도 중 6회 SUBMITTED (총 5건 order_request + broker_order 생성됨).

### ⚠️ 실수 포인트 #7: Stale Snapshot Blocker

Submit 시도 시 `stale_snapshot`으로 SKIPPED될 수 있음. 이 경우 Phase 1 Snapshot Sync를 재실행한 후 재시도. [`kis_paper_submit_price_fix_report.md`](plans/kis_paper_submit_price_fix_report.md:57) 참조.

---

## 9. Phase 4: Post-Submit 검증

> **목적**: Broker가 실제로 주문을 accept했는지 DB에서 확인.

### 9-A. Order Requests 확인

```bash
python3 -c "
import asyncio
from agent_trading.db.connection import create_pool

async def check():
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            \"SELECT order_request_id, status, price, side, requested_quantity, created_at FROM order_requests ORDER BY created_at DESC LIMIT 10\"
        )
        for r in rows:
            print(f'ID: {r[\"order_request_id\"]}  status: {r[\"status\"]}  price: {r[\"price\"]}  side: {r[\"side\"]}  qty: {r[\"requested_quantity\"]}  at: {r[\"created_at\"]}')
    await pool.close()

asyncio.run(check())
"
```

### 9-B. Broker Orders 확인

```bash
python3 -c "
import asyncio
from agent_trading.db.connection import create_pool

async def check():
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            \"SELECT broker_order_id, broker_native_order_id, broker_status, submitted_at FROM broker_orders ORDER BY submitted_at DESC LIMIT 10\"
        )
        for r in rows:
            print(f'ID: {r[\"broker_order_id\"]}  native_id: {r[\"broker_native_order_id\"]}  status: {r[\"broker_status\"]}  at: {r[\"submitted_at\"]}')
    await pool.close()

asyncio.run(check())
"
```

### 9-C. 성공 기준

| 테이블 | 항목 | 기준 |
|--------|------|------|
| `order_requests` | `status` | `SUBMITTED` |
| `order_requests` | `price` | `268500` (설정한 KIS_SMOKE_PRICE) |
| `broker_orders` | `broker_native_order_id` | **ODNO 발급** (숫자 문자열, 예: `0000027326`) |
| `broker_orders` | `broker_status` | `submitted` |

### 9-D. 제약 사항 (미구현 항목)

| 항목 | 상태 | 비고 |
|------|------|------|
| `order_state_events` 기록 | ❌ 미구현 | 상태 전환 이벤트 미기록 (v1 스펙 범위 외) |
| `reconciliation_locks` 테이블 | ❌ 미존재 | v1 스펙 범위 외 |
| Post-submit sync (Phase 5.5) | ✅ 구현 | 스케줄러 루프 + WS 이벤트 트리거 |

### ⚠️ 실수 포인트 #8: `SubmitOrderResult` 생성자 버그 (과거, 이미 수정)

`rest_client.py:submit_order()`에서 `SubmitOrderResult` 생성자 불일치 버그가 있었으나, [`rest_client.py:797-802`](src/agent_trading/brokers/koreainvestment/rest_client.py:797)에서 수정 완료. Price 에러가 먼저 발생하여 가려져 있던 버그가 price 수정 후 처음 노출되었음.

---

## 10. Phase 5: Cleanup (옵션)

> **목적**: Phase 1.5에서 주입한 synthetic seed 데이터를 DB에서 제거.

### 10-A. Seed Cleanup

```bash
cd /workspace/agent_trading

python3 scripts/seed_smoke_test.py --cleanup
```

### 10-B. Cleanup 범위

| 테이블 | 조건 | 비고 |
|--------|------|------|
| `external_events` | `metadata->>'purpose' = 'smoke_test'` | Synthetic event만 삭제 |
| `instruments` | `metadata->>'purpose' = 'smoke_test'` | 정식 005930/KRX는 대상 아님 (별도 metadata) |

### 10-C. Cleanup하지 않는 항목

| 항목 | 이유 |
|------|------|
| `order_requests` / `broker_orders` / `trade_decisions` / `agent_runs` | 검증의 증적이므로 **의도적으로 보존**. 재현 및 audit 용도 |
| Snapshot sync 데이터 | 정상 market data이므로 보존 |
| Token cache (`.cache/kis_token.json`) | 재사용 가능, 보존 |

### ⚠️ 실수 포인트 #9: 불필요한 Full DB Cleanup

`order_requests`나 `broker_orders`를 DELETE하지 말 것. 이 데이터는 검증의 **증적**이며, 재현성 확인과 Post-submit 검증에 필요.

---

## 11. 실수하기 쉬운 포인트 — Checklist

> 아래는 Phase 1-C 실행 경험과 10회 submit smoke 실행 경험에서 도출된 **실수 포인트** 목록.

| # | 체크항목 | 위반 시 증상 | 심각도 |
|---|---------|-------------|--------|
| □ | `KIS_ENV=paper` 확인 | ⚠️ **Live 계좌 오발송 위험** | 🔴 CRITICAL |
| □ | `DATABASE_URL` shell export (`.env`에 없을 경우) | DB 연결 실패, 전체 pipeline 중단 | 🔴 BLOCKER |
| □ | `KIS_PAPER_REST_RPS=2` 설정 (1→실패) | Snapshot sync 실패 (RateLimit) | 🔴 BLOCKER |
| □ | `DEEPSEEK_MODEL_ID=deepseek-chat` (v4-pro→empty) | AI Agent empty response → JSONDecodeError | 🔴 BLOCKER |
| □ | `DEEPSEEK_TIMEOUT_SECONDS=120` (기본 60→부족) | FDC ReadTimeout → HOLD 결정 | 🟡 HIGH |
| □ | `KIS_SMOKE_PRICE` 설정 (기본 50000→에러) | `msg_cd=40270000` price validation error | 🔴 BLOCKER |
| □ | `ENABLE_KIS_PAPER_SUBMIT_SMOKE=true` 설정 | Submit smoke gate 차단 | 🔴 BLOCKER |
| □ | Pre-Flight Check 생략 | Env 오류 조기 발견 실패 | 🟡 HIGH |
| □ | Stale Snapshot 상태에서 submit | `stale_snapshot` SKIPPED | 🟡 HIGH |
| □ | Synthetic seed cleanup 누락 | 불필요한 test data DB 잔류 | 🟢 LOW |
| □ | 필요 이상의 재시도 (3회 초과) | 중복 order_request/broker_order 다량 생성 | 🟢 LOW |
| □ | `--output json` UUID 직렬화 문제 | JSON serialize 실패 (known issue) | 🟢 LOW |

---

## 12. 성공/실패 기준

### 3단계 Success Criteria

| 단계 | 기준 | 판정 |
|------|------|------|
| **1단계**: Price validation | KIS paper 상/하한가 이내의 price로 submit | ✅ `price=268500` (전일종가) → PASS |
| **2단계**: Broker accept | KIS가 ODNO(broker_native_order_id) 발급 | ✅ 5건 모두 발급 완료 (과거 실행 기준) |
| **3단계**: Order status | DB `order_requests.status=SUBMITTED` + `broker_orders.broker_status=submitted` | ✅ 정상 기록 확인 |

### 최종 판정

```
✅ SUCCESS: KIS paper broker가 검증된 price로 제출된 주문을 정상 accept
⚠️ PARTIAL: AI decision 확률성으로 APPROVE는 나왔으나 일부 시도에서 실패
❌ FAILURE: price validation 또는 broker reject 발생 시
```

---

## 13. Failure Branch 정리

### Branch A: Env/Credential 실패

```mermaid
flowchart LR
    A[env var 누락] --> B[shell export 또는 .env 보강]
    B --> C[Phase 0 재실행]
```

### Branch B: Snapshot Sync 실패

```mermaid
flowchart LR
    A[RPS 부족 / token 만료] --> B[RPS=2 확인 / token 재발급]
    B --> C[Phase 1 재실행]
```

### Branch C: Dry-Run 실패 (AI Agent)

```mermaid
flowchart LR
    A[HOLD/WATCH 반복] --> B{Seed 필요?}
    B -->|Yes| C[Phase 1.5 Seed]
    B -->|No| D[DeepSeek 모델/타임아웃 확인]
    C --> D
    D --> E[Phase 2 재실행]
```

### Branch D: Submit 실패 (Broker)

```mermaid
flowchart LR
    A[Submit SKIPPED/ERROR] --> B{사유?}
    B -->|stale_snapshot| C[Phase 1 Snapshot Sync]
    B -->|AI HOLD/WATCH| D[재시도 최대 3회]
    B -->|price error| E[KIS_SMOKE_PRICE 확인]
    B -->|broker reject| F[KIS 에러코드 분석]
    C --> G[Phase 3 재실행]
    D --> G
    E --> G
```

---

## 14. 참고: 과거 실행 이력

| 실행 | 일시 | 결과 | 비고 |
|------|------|------|------|
| Phase 1-C (초기) | 2026-05-10 | 🚦 실행 금지 | `DEEPSEEK_MODEL_ID=deepseek-v4-pro` 오류 |
| Phase 1-C (재시도) | 2026-05-10 | ✅ Dry-run 성공 | `deepseek-chat` + 120s timeout |
| Submit Smoke #1-#10 | 2026-05-11 | ✅ 6/10 SUBMITTED | `KIS_SMOKE_PRICE=268500` 적용 |
| Price fix | 2026-05-11 | ✅ 수정 완료 | `_resolve_smoke_price()` + `rest_client.py` 버그 수정 |

---

## 부록 A: 명령어 요약 (Copy-Paste용)

### 전체 실행 (모든 Phase 연속)

```bash
# 0. Env 로드
set -a; source /workspace/agent_trading/.env; set +a
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/agent_trading"
export KIS_SMOKE_PRICE=268500
export KIS_PAPER_REST_RPS=2

# 1. Pre-Flight
python3 -c "import asyncio; from agent_trading.db.connection import create_pool; ... (계정조회)"

# 2. Snapshot Sync
python3 scripts/sync_kis_snapshots.py --all --env paper

# 3. Dry-Run (2회)
python3 scripts/run_orchestrator_once.py --dry-run
python3 scripts/run_orchestrator_once.py --dry-run

# 4. Submit Smoke
python3 scripts/run_orchestrator_once.py --submit

# 5. Post-Submit 검증
python3 -c "import asyncio; from agent_trading.db.connection import create_pool; ... (order_requests 조회)"

# 6. Cleanup (옵션)
python3 scripts/seed_smoke_test.py --cleanup
```

## 부록 B: 관련 문서 링크

| 문서 | 내용 |
|------|------|
| [`paper_submit_smoke_preflight_check.md`](plans/paper_submit_smoke_preflight_check.md) | Pre-Flight 체크 상세 |
| [`paper_submit_smoke_scenario.md`](plans/paper_submit_smoke_scenario.md) | HOLD 결정 분석 및 접근 방안 비교 |
| [`kis_paper_submit_price_fix_report.md`](plans/kis_paper_submit_price_fix_report.md) | Price fix 실행 보고 (10회 submit 결과) |
| [`paper_submit_smoke_cleanup.md`](plans/paper_submit_smoke_cleanup.md) | Smoke 후속 cleanup 설계 |
| [`kis_paper_order_readiness.md`](plans/kis_paper_order_readiness.md) | KIS paper 주문 Readiness 분석 (4축) |
| [`kis_paper_order_phase1_execution.md`](plans/kis_paper_order_phase1_execution.md) | Phase 1-C 실행 보고서 |
| [`mode_boundary_paper_live.md`](plans/mode_boundary_paper_live.md) | Paper/Live Mode Boundary 정리 |
| [`run_orchestrator_once.py`](scripts/run_orchestrator_once.py) | 실행 엔트리포인트 |
| [`sync_kis_snapshots.py`](scripts/sync_kis_snapshots.py) | KIS snapshot sync CLI |
| [`seed_smoke_test.py`](scripts/seed_smoke_test.py) | Synthetic seed 스크립트 |
