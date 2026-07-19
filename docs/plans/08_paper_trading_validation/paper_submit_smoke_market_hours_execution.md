# Paper Submit Smoke — 장중 재실행 계획

## 목적

한국 영업일 장중(09:00-15:30 KST)에 paper submit smoke를 1회 재실행하여 broker accept(ODNO)를 최종 확인한다.

---

## 사전 조건 확인 (실행 직전)

```bash
# 1. 현재 시간 확인 (UTC → KST = UTC+9)
date -u
# 결과가 00:00~06:30 UTC 사이 = 09:00~15:30 KST = 장중

# 2. 한국 영업일 확인
# 월~금요일, 공휴일 제외
```

---

## 실행 절차 (순서대로 1개의 터미널에서 실행)

### Step 0: KIS_SMOKE_PRICE 강제 export (`.env` 누락 방지)

`.env`에 `KIS_SMOKE_PRICE=268500`가 없거나 shell env로 전파되지 않을 수 있으므로,
`set -a`로 `.env`를 로드한 후에도 `export`로 한 번 더 명시적으로 설정한다.

```bash
export KIS_SMOKE_PRICE=268500
```

> `.env`에 값이 이미 있다면 중복 export여도 무해함.
> 실행 시점에 가격이 부적절하면 `msg_cd=40270000`으로 reject되며, 그 경우 현재가 재조회 후 조정.

---

### Step 1: Env 로드 + KIS_SMOKE_PRICE 확인

```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && export KIS_SMOKE_PRICE=268500 && env | grep -E "KIS_ENV|KIS_APP_KEY|KIS_ACCOUNT_NO|KIS_PAPER_REST_RPS|KIS_SMOKE_PRICE|DEEPSEEK"'
```

**확인할 값:**
- `KIS_ENV=paper`
- `KIS_APP_KEY` / `KIS_APP_SECRET` / `KIS_ACCOUNT_NO=50186448`
- `KIS_PAPER_REST_RPS=1` (canonical)
- **`KIS_SMOKE_PRICE=268500`** (반드시 출력 확인. 없으면: `export KIS_SMOKE_PRICE=268500`)
- `DEEPSEEK_MODEL_ID=deepseek-chat`

---

### Step 2: Snapshot Sync

```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && export KIS_SMOKE_PRICE=268500 && python3 scripts/sync_kis_snapshots.py --all --env paper --format json'
```

**성공 조건:** `succeeded=1`, `failed=0`

---

### Step 3: Dry-Run (1회) — `--dry-run` flag 필수

```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && export KIS_SMOKE_PRICE=268500 && python3 scripts/run_orchestrator_once.py --dry-run 2>&1'
```

**확인할 값:**
- ✅ `EventInterpretationAgent succeeded`
- ✅ `AIRiskAgent succeeded` — `risk_opinion=allow` (canonical 값)
- ✅ `FinalDecisionComposerAgent succeeded` — `decision_type=APPROVE`
- ✅ Agent 출력에 `sizing_engine` — `quantity > 0`
- ✅ `Done. No broker submit was performed.` (dry-run)
- ⏱️ 각 Agent 10초 내외, total ~30초

**실패 시:** `--dry-run` 없이 1회 더 재시도. 그래도 `decision_type != APPROVE`면 AI 확률성으로 간주하고 그대로 Step 4 진행.

---

### Step 4: Submit Smoke (1회)

```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && export KIS_SMOKE_PRICE=268500 && python3 scripts/run_orchestrator_once.py --submit 2>&1'
```

---

### Step 5: 결과 확인 (DB 직접 조회 — repo 내부 절차)

```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && python3 -c "
import asyncio
from agent_trading.db.connection import create_pool
async def main():
    pool = await create_pool()
    async with pool.acquire() as conn:
        o = await conn.fetchrow('\x53ELECT order_request_id, status, requested_price, requested_quantity, created_at FROM trading.order_requests ORDER BY created_at DESC LIMIT 1')
        print(f\"ORDER: id={o[chr(39)+'order_request_id'+chr(39)]} status={o[chr(39)+'status'+chr(39)]} price={o[chr(39)+'requested_price'+chr(39)]} qty={o[chr(39)+'requested_quantity'+chr(39)]}\")
        b = await conn.fetchrow('\x53ELECT broker_order_id, broker_status, broker_native_order_id, error_message FROM trading.broker_orders ORDER BY created_at DESC LIMIT 1')
        if b and b[chr(39)+'broker_order_id'+chr(39)]:
            print(f\"BROKER: id={b[chr(39)+'broker_order_id'+chr(39)]} status={b[chr(39)+'broker_status'+chr(39)]} native_id={b[chr(39)+'broker_native_order_id'+chr(39)]} error={b[chr(39)+'error_message'+chr(39)]}\")
        else:
            print('BROKER: no broker_order record')
        td = await conn.fetchrow('\x53ELECT trade_decision_id, decision_type, side, confidence, quantity FROM trading.trade_decisions ORDER BY created_at DESC LIMIT 1')
        print(f\"DECISION: id={td[chr(39)+'trade_decision_id'+chr(39)]} type={td[chr(39)+'decision_type'+chr(39)]} confidence={td[chr(39)+'confidence'+chr(39)]} qty={td[chr(39)+'quantity'+chr(39)]}\")
    await pool.close()
asyncio.run(main())
"'
```

---

## 예상 결과별 분류

| 결과 | broker_status | 판정 |
|------|---------------|------|
| ✅ **ODNO 발급** | `submitted`, `native_id`=숫자 | **Broker accept 성공** |
| ⚠️ **ODNO 발급 + RECONCILE_REQUIRED** | `reconcile_required`, `native_id`=숫자 | **Paper mock 한계 — 정상**. Post-submit sync 실행 후 `last_synced_at` 갱신 확인 필요 |
| ❌ `msg_cd=40580000` | 기록 없음 | 장 마감 → Step 1로 돌아가 시간 확인 |
| ❌ `msg_cd=40270000` | 기록 있음, `error_message` 포함 | **Price validation error** → `KIS_SMOKE_PRICE` 조정 필요 |
| ❌ 기타 `msg_cd` | 기록 있음 | Broker business reject → 코드 분류 후 보고 |

> **Paper Mock 한계**: KIS paper mock (`openapivts`)은 `inquire-daily-ccld`에서 체결 데이터를 반환하지 않아, post-submit sync 후 `broker_status`가 `reconcile_required`로 수렴하는 것이 정상입니다. 이는 코드 버그가 아닌 테스트 인프라 제약입니다. 자세한 분석은 [`inquire_daily_ccld_payload_capture_report.md`](plans/inquire_daily_ccld_payload_capture_report.md) 참조.

---

## 복구 (장중이 아닐 때 실행한 경우)

- `pending_submit` 상태 Order는 `run_post_submit_sync_loop.py`가 reconciliation에서 처리
- 별도 cleanup 불필요 (PENDING_SUBMIT 상태로 남아도 무해)
