# Paper Submit Smoke 직전 Preflight Plan (v2)

## 현재 상태 요약

| 구분 | 상태 | 비고 |
|------|------|------|
| sizing_hint blocker | ✅ 해결 | `_coerce_nested_json_strings()` dict→dataclass 변환 추가 |
| correlation_id duplicate | ✅ 해결 | uuid4 + savepoint |
| DeepSeek structured-output | ✅ 해결 | `typing.get_type_hints` + `__post_init__` |
| Dry-run 2회 연속 | ✅ exit 0 | 모두 통과 |
| AI ReadTimeout (deepseek-v4-pro) | ⚠️ 존재 | Fallback 정상 작동, dry-run에는 영향 없음 |
| Service tests (338개) | ✅ 통과 | 모두 통과 |

## 변경 사항 반영

- **접근법**: C안 (postgres_runtime에서 PaperGateService 직접 호출)
- **Account UUID**: Step 0 선행 조회
- **평가 해석**: filled order 부족 WARN ≠ submit smoke 절대 blocker
- **Submit smoke**: 명령 확정만 (실행 금지)
- **기술적 진입 조건**: snapshot freshness / reconciliation lock / KIS endpoint / token cache / DB 연결 별도 묶음

---

## 실행 순서

### Step 0: 환경 재확인 (Code Mode)

**0-A. Paper 계정 UUID 조회** (최우선)
```bash
python3 -c "
import asyncio
from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import create_pool, get_pool
from agent_trading.db.transaction import transaction
from agent_trading.domain.enums import Environment

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

**0-B. 환경 변수 확인**
```bash
echo "KIS_ENV=${KIS_ENV:-<unset>}"
echo "DATABASE_URL=${DATABASE_URL:+set (length ${#DATABASE_URL})} / ${DATABASE_URL:-<unset>}"
echo "DEEPSEEK_MODEL_ID=${DEEPSEEK_MODEL_ID:-<unset>}"
echo "LLM_PROVIDER=${LLM_PROVIDER:-<unset>}"
echo "KIS_PAPER_REST_RPS=${KIS_PAPER_REST_RPS:-<unset>}"
echo "KIS_DEV_TOKEN_CACHE_ENABLED=${KIS_DEV_TOKEN_CACHE_ENABLED:-<unset>}"
echo "KIS_ACCOUNT_NO=${KIS_ACCOUNT_NO:-<unset>}"
```

**0-C. Token cache 확인**
```bash
ls -la .cache/kis_token.json 2>&1 || echo "Token cache not found"
```

**0-D. KIS endpoint connectivity**
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

**0-E. DB connectivity**
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

### Step 1: Paper Gate / Exit 평가 (postgres_runtime)

PaperGateService를 postgres_runtime 안에서 직접 호출하는 스크립트 실행:

```bash
python3 -c "
import asyncio, json
from datetime import date, datetime, timezone
from uuid import UUID
from agent_trading.config.settings import AppSettings
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.paper_gate import PaperGateService

ACCOUNT_ID = UUID('{0-A에서_조회한_UUID}')

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
        print(f'Checks: {len(result.checks)}')
        for c in result.checks:
            print(f'  [{c.status.value}] {c.code}: {c.message} (val={c.measured_value}, thr={c.threshold})')

asyncio.run(evaluate())
"
```

### Step 2: Submit Smoke 진입 조건 판정

**기술적 진입 조건** (별도 그룹)

| # | 항목 | 확인 방법 |
|---|------|----------|
| 1 | KIS_ENV=paper | Step 0-B |
| 2 | DATABASE_URL 연결 가능 | Step 0-E |
| 3 | Token cache 존재/유효 | Step 0-C |
| 4 | KIS endpoint reachable | Step 0-D |
| 5 | Snapshot freshness 정상 | Step 1에서 PaperGate 결과 확인 |
| 6 | Reconciliation lock 없음 | 추가 조회 필요 |
| 7 | KIS_PAPER_REST_RPS 설정 | Step 0-B (기본 1, override 필요 시 2) |

**기술적 Blocker**

| # | 항목 | 상태 | 근거 |
|---|------|------|------|
| 1 | sizing_hint dict→dataclass | ✅ 해결 | Dry-run 2회 연속 exit 0 |
| 2 | correlation_id duplicate | ✅ 해결 | uuid4 + savepoint |
| 3 | DeepSeek structured-output | ✅ 해결 | typing.get_type_hints + __post_init__ |
| 4 | AI ReadTimeout (deepseek-v4-pro) | ⚠️ Fallback 정상 | dry-run 영향 없음 |
| 5 | `--output json` UUID 직렬화 | ❌ 해결 안 함 | --output text로 우회 가능 |

**정책적 Blocker**

| # | 항목 | 상태 |
|---|------|------|
| 1 | `ENABLE_KIS_PAPER_SUBMIT_SMOKE=true` | ✅ opt-in env var만 설정 |
| 2 | Paper Gate 평가 결과 | ⏳ Step 1 후 판정 |
| 3 | Dry-run 성공 | ✅ 충족 (2회 연속 exit 0) |
| 4 | Snapshot sync freshness | ⏳ Step 1에서 확인 |
| 5 | Filled order 부족 WARN | ⚠️ submit smoke 자체의 절대 blocker 아님 |

### Step 3: Submit Smoke 실행 명령 확정 (실행 금지, 확정만)

```bash
# === Submit Smoke Command (확정본, 실제 실행은 다음 턴) ===

# 선행 조건
export ENABLE_KIS_PAPER_SUBMIT_SMOKE=true

# Step 3-A: Snapshot sync (최신 상태 보장)
export KIS_PAPER_REST_RPS=2
python3 scripts/sync_kis_snapshots.py --all --format json

# Step 3-B: Dry-run 재확인
python3 scripts/run_orchestrator_once.py --dry-run --output text

# Step 3-C: Submit smoke (opt-in)
python3 scripts/run_orchestrator_once.py \
    --submit \
    --account-id {ACCOUNT_UUID} \
    --output text
```

**필요 env vars checklist**
- `KIS_ENV=paper` ✅ (기본값)
- `DATABASE_URL` 필요
- `KIS_PAPER_REST_RPS=2` (snapshot sync용, Phase 1-C 경험)
- `ENABLE_KIS_PAPER_SUBMIT_SMOKE=true` (opt-in)
- `DEEPSEEK_API_KEY` (설정됨)
- `DEEPSEEK_BASE_URL` (설정됨)
- `KIS_DEV_TOKEN_CACHE_ENABLED=true` (paper 전용)

## 유지 원칙

| 원칙 | 적용 |
|------|------|
| 실제 live 주문 금지 | ✅ paper env만 사용 |
| Paper/Live는 config/env 차이만 유지 | ✅ 코드 변경 없음 |
| Broker submit semantics 변경 금지 | ✅ 변경 계획 없음 |
| Hard guardrail / reconciliation 경계 변경 금지 | ✅ 변경 계획 없음 |
| Admin UI 변경 금지 | ✅ 변경 계획 없음 |
| 과도한 리팩터링 금지 | ✅ 최소 경로 C안 |
| Preflight + smoke 진입 조건 확정까지만 | ✅ submit 실행은 다음 턴 |

## 보고 형식 (완료 시)

1. Step 0 환경 재확인 결과
2. 실제 paper account UUID
3. Paper Gate / Exit 평가 결과
4. 기술적 blocker 존재 여부
5. 정책적 blocker 존재 여부
6. submit smoke 진입 가능 여부
7. 실제 submit smoke 명령 확정본
8. 남은 리스크 1개
9. 다음 직접 액션 1개
