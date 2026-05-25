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
| `KIS_APP_KEY` / `KIS_API_KEY` | ✅ | `PS...` | KIS paper API key (preferred/legacy fallback) |
| `KIS_APP_SECRET` / `KIS_API_SECRET` | ✅ | `...` | KIS paper API secret (preferred/legacy fallback) |
| `KIS_ACCOUNT_NO` / `KIS_ACCOUNT_NUMBER` | ✅ | `50186448` | KIS paper 계좌번호 (preferred/legacy fallback) |
| `KIS_ACCOUNT_PRODUCT_CODE` | ✅ | `01` | KIS paper 계좌상품코드 (=01) |
| `DEEPSEEK_API_KEY` | ✅ | `sk-...` | DeepSeek LLM API key |
| `DEEPSEEK_BASE_URL` | ✅ | `https://api.deepseek.com` | DeepSeek LLM endpoint |
| `DEEPSEEK_MODEL_ID` | ✅ | `deepseek-chat` | `deepseek-chat` smoke 재현에 더 안정적; `deepseek-v4-pro`도 동작 가능하나 timeout/품질 편차 가능 |
| `DEEPSEEK_TIMEOUT_SECONDS` | 권장 | `120` | 기본 60초 → FDC ReadTimeout 방지 |
| `KIS_PAPER_REST_RPS` | ✅ | `1` (canonical) | ⚠️ 과거 RPS=1에서 snapshot sync 실패 이력이 있었으나, budget 분배 로직 개선으로 RPS=1에서 정상 동작 |
| `KIS_DEV_TOKEN_CACHE_ENABLED` | 권장 | `true` | Token cache 활성화 (paper 전용) |
| `ENABLE_KIS_PAPER_SUBMIT_SMOKE` | 권장 | `true` | 운영상 opt-in safety flag (현재 스크립트 자체 필수 조건은 아님) |
| `KIS_SMOKE_PRICE` | Smoke 전용 | `267000` (시장가) | Submit smoke용 price override (Phase 2.5에서 설정). **반드시 실제 시장가와 일치**해야 함. 모의투자 API가 가격 검증을 수행하므로 부정확한 값은 `msg_cd=40270000` 실패. |

### 2-C. 필수 env vars 누락 확인

```bash
echo "=== === Env Check === ==="
echo "KIS_ENV=${KIS_ENV:-<MISSING>}"
echo "DATABASE_URL=${DATABASE_URL:+set (length ${#DATABASE_URL})}/${DATABASE_URL:-<MISSING>}"
echo "KIS_APP_KEY=${KIS_APP_KEY:+set}/${KIS_APP_KEY:-<MISSING>}  /  KIS_API_KEY=${KIS_API_KEY:+set}/${KIS_API_KEY:-<MISSING>}"
echo "KIS_APP_SECRET=${KIS_APP_SECRET:+set}/${KIS_APP_SECRET:-<MISSING>}  /  KIS_API_SECRET=${KIS_API_SECRET:+set}/${KIS_API_SECRET:-<MISSING>}"
echo "KIS_ACCOUNT_NO=${KIS_ACCOUNT_NO:-<MISSING>}  /  KIS_ACCOUNT_NUMBER=${KIS_ACCOUNT_NUMBER:-<MISSING>}"
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
> 이 UUID는 [`scripts/run_orchestrator_once.py`](scripts/run_orchestrator_once.py:64)의 `ACCOUNT_ID` 상수와 일치해야 함.

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
        # ⚠️ 날짜 범위는 실행 시점에 맞게 조정 필요
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

# KIS_PAPER_REST_RPS=1 (canonical; Phase 1-C에서 RPS=1 실패 경험이 있었으나 budget 분배 로직 개선으로 해소)
export KIS_PAPER_REST_RPS="${KIS_PAPER_REST_RPS:-1}"

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
| `positions_synced=0, errors: RateLimit` | `KIS_PAPER_REST_RPS=1` → Global REST cap 소진 (과거) | budget 분배 로직 개선으로 RPS=1에서 해소 |
| Token 관련 에러 | Token cache 만료 또는 API key 오류 | `.cache/kis_token.json` 삭제 후 재시도 |
| `Account not found` | DB에 paper account 미등록 | `run_orchestrator_once.py` 1회 실행 (seed 자동) 후 재시도 |

### ⚠️ 실수 포인트 #3 (과거): `KIS_PAPER_REST_RPS=1`로 snapshot sync 실패

[`kis_paper_order_phase1_execution.md`](plans/kis_paper_order_phase1_execution.md:42) 참조. Phase 1-C 당시 RPS=1은 Global REST cap을 순간적으로 소진하여 snapshot sync가 실패했으나, 이후 budget 분배 로직 및 pacing 개선으로 RPS=1(canonical)에서 정상 동작한다.

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
| `EventInterpretationAgent failed` | DeepSeek API key 오류 또는 model ID 불안정 | `DEEPSEEK_MODEL_ID=deepseek-chat` 권장, API key 재설정 |
| `FinalDecisionComposer timed out` | `DEEPSEEK_TIMEOUT_SECONDS` 부족 | 120s 이상으로 증가 |
| HOLD/WATCH만 반복 | Synthetic seed 부족 | Phase 1.5 Seed 실행 후 재시도 |
| `decision_context_id` 없음 | DB FK chain 미존재 | 자동 seed가 수행되므로 1회 더 시도 |

### ⚠️ 실수 포인트 #5: `DEEPSEEK_MODEL_ID` 선택

`deepseek-chat`이 smoke 재현에 더 안정적이어서 권장. [`kis_paper_order_phase1_execution.md`](plans/kis_paper_order_phase1_execution.md:94) 참조. `deepseek-v4-pro`도 동작 가능하지만 timeout/품질 편차가 있을 수 있음.

---

## 7. Phase 2.5: KIS_SMOKE_PRICE 설정 (필수)

> **목적**: KIS paper broker가 accept 가능한 LIMIT price 설정.
> **상태**: **권장 → 필수** (2026-05-13 운영 기준 정리). near-real submit 전 반드시 설정해야 함.
> **참고**: [`paper_nearreal_ops_cleanup_plan.md`](plans/paper_nearreal_ops_cleanup_plan.md:68) 참조.

### 7-A. Price 설정

```bash
export KIS_SMOKE_PRICE=267000
```

> **실증 결과 (2026-05-13)**: KIS paper mock은 `inquire-price` 가격 검증을 수행하며, 실제 시장가와 다른 price는 `msg_cd=40270000`(모의투자 상/하한가 오류)으로 거절함.
>
> | 시도 | Price | 결과 |
> |------|-------|------|
> | 1차 | 26850 (임의값) | ❌ `msg_cd=40270000` |
> | 2차 | 50000 (기본값) | ❌ `msg_cd=40270000` |
> | 3차 | **267000** (KIS API 현재가) | ✅ SUBMITTED |
>
> **설정 방법**: KIS API로 현재가 조회 후 설정. 예: 005930 현재가는 KIS REST API `stck_prpr` 필드.
> **⚠️ 주의**: 전일종가가 아닌 **당일 현재가**를 사용해야 함. KIS paper 상/하한가(전일종가 ±30%) 이내여야 함.

### 7-B. Price 결정 로직 (필수 — 기본값 의존 금지)

[`_resolve_smoke_price()`](scripts/run_orchestrator_once.py:80)의 우선순위:

```
1. KIS_SMOKE_PRICE env var → 해당 Decimal (시장가와 일치 필수)
2. fallback → Decimal("50000") → KIS price validation error (msg_cd=40270000) → 사용 불가
```

> **운영 규칙 (2026-05-13 확정)**: `KIS_SMOKE_PRICE` env var는 near-real submit 전 **필수 설정** 항목이다. 기본값 50000에 의존하는 것은 허용되지 않는다. 설정값은 KIS API `inquire-price`로 조회한 당일 현재가와 일치해야 한다.

### 7-C. KIS API로 현재가 조회 명령어

```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && python3 -c "
import asyncio
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.repositories.container import RepositoryContainer
async def main():
    async with postgres_runtime() as runtime:
        repos: RepositoryContainer = runtime[\"repositories\"]
        inst = await repos.instruments.get_by_symbol(\"005930\", \"KRX\")
        if inst:
            print(f\"Symbol: {inst.symbol}, Name: {inst.name}\")
        else:
            print(\"Instrument 005930/KRX not found\")
asyncio.run(main())
"
```

> 현재가 확인 후 export: `export KIS_SMOKE_PRICE=<현재가>`

### 7-D. 경고: env 미설정 시

`KIS_SMOKE_PRICE`가 설정되지 않으면 기본값 `50000`이 사용되며, 이는 KIS 하한가를 크게 밑돌아 `msg_cd=40270000` 에러 발생. [`run_orchestrator_once.py`](scripts/run_orchestrator_once.py:330)에서 경고 로그 출력.

### ⚠️ 실수 포인트 #6: `KIS_SMOKE_PRICE` 미설정 또는 시장가 불일치

env var를 설정하지 않고 `--submit` 실행 시, default price=50000으로 submit되어 `msg_cd=40270000`(price validation error) 발생. 또한 설정값이 실제 시장가와 다르면 동일 에러 발생. **반드시 KIS API로 현재가를 확인 후 설정**할 것.

---

## 8. Phase 3: Submit Smoke 실행

> **목적**: Full pipeline (assemble → validate → create_order → submit_order) 실행.  
> **opt-in 조건**: `ENABLE_KIS_PAPER_SUBMIT_SMOKE=true` 권장 (운영상 safety flag. 현재 스크립트 자체 필수 조건은 아님).

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

### 8-E. AI 결정 품질과 입력 이벤트 품질의 상관관계

**실증 결과 (2026-05-13)**: AI의 decision_type은 입력 이벤트 품질에 직접 비례함.

| 입력 상태 | AI 결정 | 원인 |
|-----------|---------|------|
| stale (published_at=2일전) + synthetic + headline=NULL | HOLD | `risk_flags: ["synthetic_data", "stale"]` → FDC "신뢰도 낮음" |
| fresh (published_at=NOW) + headline=구체적 + severity=high + direction=positive + importance=high | **APPROVE** (confidence=0.70) | EI가 긍정적 신호로 해석, FDC가 BUY 결정 |

**시사점**:
- 이벤트 품질 개선 없이 AI 결정 개선 불가
- OpenDART importance 분류(`metadata.importance=high`)가 EI prompt에서 우선 검토되어 APPROVE에 기여
- `severity`/`direction` 값이 EI 추론에 직접적 영향

### 8-F. Smoke Event 데이터 조정 기법 (검증 전용)

> ⚠️ **이 기법은 검증용 임시 조치이며, 운영 절차가 아님**

APPROVE 유도를 위해 smoke event의 DB 데이터를 직접 수정한 사례:

| 조정 항목 | 적용값 | 목적 |
|-----------|--------|------|
| `published_at` → `NOW()` | stale 플래그 제거 | AI가 `stale` risk_flag를 제거하도록 유도 |
| `metadata.synthetic` → 제거 | synthetic 플래그 제거 | AI가 `synthetic_data` risk_flag를 제거하도록 유도 |
| `headline` → 구체적 텍스트 | EI 해석 가능한 입력 제공 | AI 추론 품질 향상 |
| `metadata.importance` → `"high"` | 중요도 정렬 우선 | EI가 이벤트를 먼저 검토하도록 유도 |

**제약**:
- 운영 환경에서 이 기법을 사용하면 안 됨 (데이터 무결성 훼손)
- Live 환경에서는 실제 OpenDART 공시 데이터가 자연스럽게 높은 품질을 제공할 것으로 예상
- 이 기법은 **Paper mock의 이벤트 부족 현상을 우회하기 위한 임시 수단**

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

### 9-C. 성공 기준 (Paper 검증 완료 — 2026-05-13 실증 기준)

| 테이블 | 항목 | 기준 | 검증 상태 |
|--------|------|------|----------|
| `order_requests` | `status` | `SUBMITTED` → `reconcile_required` | ✅ Paper 실증 완료 |
| `order_requests` | `price` | 설정한 KIS_SMOKE_PRICE (시장가) | ✅ Paper 실증 완료 |
| `order_requests` | `side` | `BUY` | ✅ Paper 실증 완료 |
| `order_requests` | `requested_quantity` | `> 0` (sizing 적용) | ✅ Paper 실증 완료 |
| `broker_orders` | `broker_native_order_id` | **ODNO 발급** (숫자 문자열) | ✅ Paper 실증 완료 |
| `broker_orders` | `broker_status` | `submitted` → `reconcile_required` | ✅ Paper 실증 완료 (mock 한계) |
| `broker_orders` | `last_synced_at` | **Post-submit sync 실행 후 갱신** | ✅ Paper 실증 완료 |
| `order_state_events` | 상태 전이 이력 | `draft→validated→pending_submit→submitted→reconcile_required` | ✅ Paper 실증 완료 |
| `broker_orders` | `broker_status` 최종 수렴 | `FILLED` / `CANCELLED` / `REJECTED` | ❌ **Live 전용** (paper mock 한계) |

### 9-D. Paper Mock 한계 (검증 범위)

> **중요**: KIS paper mock (`openapivts`)은 `inquire-daily-ccld` 엔드포인트에서 체결 데이터를 반환하지 않는 한계가 있습니다.
> 따라서 paper 환경에서 post-submit sync의 broker_status는 `RECONCILE_REQUIRED`로 수렴하는 것이 정상이며,
> 이는 **코드 버그가 아닌 테스트 인프라 제약**입니다. 자세한 분석은
> [`inquire_daily_ccld_payload_capture_report.md`](plans/inquire_daily_ccld_payload_capture_report.md) 참조.

| 항목 | Paper 허용 여부 | Live 기대 |
|------|----------------|-----------|
| `broker_status=reconcile_required` | ✅ **허용 (정상)** | ❌ 비정상 — 원인 분석 필요 |
| `last_synced_at` 갱신 | ✅ **필수 성공 기준** | ✅ 필수 |
| `order_state_events` 기록 | ✅ **필수 성공 기준** | ✅ 필수 |
| FILLED / CANCELLED / REJECTED 수렴 | ❌ **Paper mock에서 기대 불가** | ✅ **필수 성공 기준** |
| 실제 체결 내역 조회 | ❌ **Paper mock에서 기대 불가** | ✅ 가능 |

### 9-E. Post-Submit Sync 확인 (Phase 5.5 연동)

Post-submit sync 실행 후 아래 항목을 추가 확인합니다:

```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && python3 -c "
import asyncio
from agent_trading.db.connection import create_pool
async def main():
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch('SELECT broker_order_id, broker_native_order_id, broker_status, last_synced_at FROM broker_orders ORDER BY submitted_at DESC LIMIT 10')
        for r in rows:
            print(f'ID: {r[\"broker_order_id\"]}  native: {r[\"broker_native_order_id\"]}  status: {r[\"broker_status\"]}  synced: {r[\"last_synced_at\"]}')
        cnt = await conn.fetchval('SELECT COUNT(*) FROM order_state_events')
        print(f'order_state_events count: {cnt}')
    await pool.close()
asyncio.run(main())
"
```

### 9-F. 제약 사항 (미구현 항목)

| 항목 | 상태 | 비고 |
|------|------|------|
| `reconciliation_locks` 테이블 | ❌ 미존재 | v1 스펙 범위 외 |
| Post-submit sync (Phase 5.5) | ✅ 구현 | 스케줄러 루프 + WS 이벤트 트리거 |

### ⚠️ 실수 포인트 #8: `SubmitOrderResult` 생성자 버그 (과거, 이미 수정)

`rest_client.py:submit_order()`에서 `SubmitOrderResult` 생성자 불일치 버그가 있었으나, [`rest_client.py:797-802`](src/agent_trading/brokers/koreainvestment/rest_client.py:797)에서 수정 완료. Price 에러가 먼저 발생하여 가려져 있던 버그가 price 수정 후 처음 노출되었음.

---

## 10. Phase 5: Cleanup (옵션)

> **목적**: (1) Phase 1.5에서 주입한 synthetic seed 데이터 제거, (2) stale `pending_submit` 주문 정리.

### 10-A. Seed Cleanup

```bash
cd /workspace/agent_trading

python3 scripts/seed_smoke_test.py --cleanup
```

### 10-B. Stale PENDING_SUBMIT Cleanup (운영 정리)

> **운영 기준 (2026-05-13 확정)**: 24시간 이상 `pending_submit` 상태로 broker 미제출된 주문은 `stale_cleanup`으로 정리한다.

**대상 조건**:
1. `status = 'pending_submit'`
2. `created_at < NOW() - INTERVAL '24 hours'`
3. `broker_orders` 연결 없음 (broker에 미제출)

**처리 방법**: `PENDING_SUBMIT → REJECTED` (reason_code=`stale_cleanup`)

```bash
cd /workspace/agent_trading
python3 _cleanup_pending_submit.py
```

> **실행 결과 (2026-05-13)**: 15건 정리 완료. `order_state_events`에 15건 증적 기록. `reconcile_required` 주문(6건)은 영향 없음.

**Cleanup 스크립트** [`_cleanup_pending_submit.py`](_cleanup_pending_submit.py)가 수행하는 작업:
1. 대상 주문 조회 및 출력
2. `order_requests` UPDATE: `status='rejected', status_reason_code='stale_cleanup'`
3. `order_state_events` INSERT: 상태전이 증적 기록
4. 결과 검증: rejected count, order_state_events 증가, reconcile_required 영향 없음 확인

### 10-C. Cleanup 범위

| 구분 | 대상 | 조건 | 비고 |
|------|------|------|------|
| Seed Cleanup | `external_events` | `metadata->>'purpose' = 'smoke_test'` | Synthetic event만 삭제 |
| Seed Cleanup | `instruments` | `metadata->>'purpose' = 'smoke_test'` | 정식 005930/KRX는 대상 아님 |
| Stale Cleanup | `order_requests` | `status='pending_submit' AND created_at < 24h AND no broker_orders` | 상태전이만 수행 (DELETE 아님) |

### 10-D. Cleanup하지 않는 항목

| 항목 | 이유 |
|------|------|
| `broker_orders` / `trade_decisions` / `agent_runs` | 검증의 증적이므로 **의도적으로 보존**. 재현 및 audit 용도 |
| 정상 `order_requests` (SUBMITTED/RECONCILE_REQUIRED) | 정상 운영 데이터, 보존 |
| Snapshot sync 데이터 | 정상 market data이므로 보존 |
| Token cache (`.cache/kis_token.json`) | 재사용 가능, 보존 |

### ⚠️ 실수 포인트 #9: 불필요한 Full DB Cleanup

`order_requests`나 `broker_orders`를 DELETE하지 말 것. 이 데이터는 검증의 **증적**이며, 재현성 확인과 Post-submit 검증에 필요. Stale `pending_submit`은 DELETE가 아닌 상태전이(`REJECTED`)로 처리한다.

---

## 11. 실수하기 쉬운 포인트 — Checklist

> 아래는 Phase 1-C 실행 경험과 10회 submit smoke 실행 경험에서 도출된 **실수 포인트** 목록.

| # | 체크항목 | 위반 시 증상 | 심각도 |
|---|---------|-------------|--------|
| □ | `KIS_ENV=paper` 확인 | ⚠️ **Live 계좌 오발송 위험** | 🔴 CRITICAL |
| □ | `DATABASE_URL` shell export (`.env`에 없을 경우) | DB 연결 실패, 전체 pipeline 중단 | 🔴 BLOCKER |
| □ | `KIS_PAPER_REST_RPS=1` 설정 (canonical) | budget 분배 로직 개선으로 RPS=1에서 정상 동작 | ✅ 확인 |
| □ | `DEEPSEEK_MODEL_ID=deepseek-chat` 권장 (v4-pro는 timeout/품질 편차 가능) | AI Agent 응답 불안정 | 🟡 HIGH |
| □ | `DEEPSEEK_TIMEOUT_SECONDS=120` (기본 60→부족) | FDC ReadTimeout → HOLD 결정 | 🟡 HIGH |
| □ | `KIS_SMOKE_PRICE` 설정 (기본 50000→에러) | `msg_cd=40270000` price validation error | 🔴 BLOCKER |
| □ | `ENABLE_KIS_PAPER_SUBMIT_SMOKE=true` 설정 (운영 권장) | Safety flag 미설정 시 운영상 불안 | 🟡 HIGH |
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
    A[RPS 부족 / token 만료] --> B[RPS=1(canonical) 확인 / token 재발급]
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
| Phase 1-C (초기) | 2026-05-10 | 🚦 보류 | `DEEPSEEK_MODEL_ID=deepseek-v4-pro` timeout/품질 편차 |
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
export KIS_PAPER_REST_RPS="${KIS_PAPER_REST_RPS:-1}"   # canonical=1

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
