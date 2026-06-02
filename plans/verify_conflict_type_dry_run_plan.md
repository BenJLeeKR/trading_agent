# Conflict Type Dry-Run 검증 계획

## 1. 기존 로그 분석 결과

### 1.1. 분석 파일
- [`logs/backfill_container_dry_run_v4_20260531.log`](../logs/backfill_container_dry_run_v4_20260531.log)

### 1.2. 발견된 문제: `conflict_type` / `conflict_type_breakdown` 부재

기존 dry-run 로그를 분석한 결과, 다음과 같은 항목이 **전혀 출력되지 않음**:

| 항목 | 존재 여부 | 설명 |
|------|-----------|------|
| 각 order record의 `conflict_type` 필드 | ❌ | JSON orders 배열의 각 record에 `conflict_type` 키 없음 |
| JSON summary의 `conflict_type_breakdown` | ❌ | JSON summary 객체에 해당 키 없음 |
| human summary의 `Conflict Type:` 라인 | ❌ | human-readable 출력에 없음 |
| human summary의 `types:` 집계 라인 | ❌ | summary 섹션에 없음 |

### 1.3. 원인 분석

기존 로그는 `conflict_type` 관련 기능이 **구현되기 전** 버전의 코드로 실행되었음.

**증거:**
- 로그 timestamp: `2026-05-31 08:36:38 KST` (현재 시각: `2026-05-31 17:33 KST`)
- JSON output의 각 record 필드: `order_request_id`, `symbol`, `side`, `requested_qty`, `classification`, `target_status`, `verdict`, `match_method`, `reason` — **`conflict_type` 없음**
- JSON summary: `date_range`, `dry_run`, `total`, `auto_fix_safe`, `truth_probe_conflict`, `manual`, `applied`, `orders` — **`conflict_type_breakdown` 없음**

**현재 코드 상태: 모두 구현 완료 ✅**

[`scripts/backfill_expired_odno_orders.py`](../scripts/backfill_expired_odno_orders.py) 분석 결과:

| 기능 | 위치 | 상태 |
|------|------|------|
| `_classify()` 4-tuple 반환 `(classification, target_status, reason, conflict_type)` | L238 | ✅ 구현됨 |
| record dict에 `"conflict_type": conflict_type` | L555 | ✅ 구현됨 |
| human summary `Conflict Type:` 라인 | L663-L665 | ✅ 구현됨 |
| human summary `types:` 집계 라인 | L700-L707 | ✅ 구현됨 |
| JSON summary `"conflict_type_breakdown"` | L743 | ✅ 구현됨 |

---

## 2. 실행 계획

### 2.1. 사전 확인 (Docker 컨테이너 상태)

Code mode에서 다음 명령어로 Docker 컨테이너가 실행 중인지 확인:

```bash
docker ps | grep agent_trading-app-1
```

**예상:** `agent_trading-app-1` 컨테이너가 실행 중이어야 함 (기존 로그가 Docker 내부에서 생성되었으므로).

### 2.2. Dry-Run 명령어

> **중요:** 타임스탬프를 `TS` 변수로 먼저 고정하여 JSON과 LOG 파일명이 일치하도록 함.
> stderr를 완전히 버리지 않고 별도 디버그 로그로 보존 (`2>` 리다이렉션).

#### Step 1: 타임스탬프 변수 설정 (모든 명령어의 기준)

```bash
TS=$(date +%Y%m%d_%H%M%S)
echo "Timestamp: $TS"
```

#### Step 2: JSON 출력 저장 (stdout → .json, stderr → .debug.log)

```bash
docker exec agent_trading-app-1 python3 scripts/backfill_expired_odno_orders.py \
  --dry-run \
  --from-date 2026-05-28 \
  --to-date 2026-05-29 \
  --json \
  > /workspace/agent_trading/logs/backfill_dry_run_conflict_type_${TS}.json \
  2>/workspace/agent_trading/logs/backfill_dry_run_conflict_type_${TS}.debug.log
```

**설명:**
- `--dry-run`: 변경 없이 분류만 수행
- `--from-date 2026-05-28 --to-date 2026-05-29`: 기존 로그와 동일한 기간 (비교 가능)
- `--json`: JSON 형식으로 summary + orders 출력
- `> .json`: stdout(JSON)을 파일로 저장
- `2> .debug.log`: stderr(logging INFO)을 별도 디버그 파일로 저장 (실패 시 원인 분석 가능)
- 타임스탬프 `$TS`를 고정 변수로 사용 → JSON/DEBUG 파일명 일치 보장

#### Step 3: Human-readable 출력 저장 (stdout + stderr 모두 로그 파일에)

```bash
docker exec agent_trading-app-1 python3 scripts/backfill_expired_odno_orders.py \
  --dry-run \
  --from-date 2026-05-28 \
  --to-date 2026-05-29 \
  2>&1 | tee /workspace/agent_trading/logs/backfill_dry_run_conflict_type_${TS}.log
```

**설명:**
- `--json` 없음 → human-readable 출력
- `2>&1 | tee ...`: stderr(logging)과 stdout(human summary)을 모두 터미널과 파일에 기록
- 출력 파일: `logs/backfill_dry_run_conflict_type_${TS}.log` (같은 `$TS` 사용)

---

### 2.3. 검증 항목 (Checklist)

#### 2.3.1. 각 conflict order record의 `conflict_type` 필드

JSON 파일에서 각 `truth_probe_conflict` record를 검증:

```bash
# conflict_type이 설정된 record 개수 확인
python3 -c "
import json
with open('logs/backfill_dry_run_conflict_type_<TIMESTAMP>.json') as f:
    data = json.load(f)
conflicts = [o for o in data['orders'] if o['classification'] == 'truth_probe_conflict']
has_ct = [o for o in conflicts if o.get('conflict_type') is not None]
print(f'Total conflict orders: {len(conflicts)}')
print(f'With conflict_type:    {len(has_ct)}')
print(f'Without conflict_type: {len(conflicts) - len(has_ct)}')
if has_ct:
    types = set(o['conflict_type'] for o in has_ct)
    print(f'Unique conflict_types: {types}')
"
```

**예상 결과:**
- `Total conflict orders: 75` (기존 로그와 동일)
- `With conflict_type: 75` (모든 conflict record에 `conflict_type` 존재)
- `Unique conflict_types`: `{'position_delta_partial', 'position_delta_filled'}` (기존 로그 기준 position_verdict에 따라)

#### 2.3.2. JSON summary의 `conflict_type_breakdown` 객체

```bash
python3 -c "
import json
with open('logs/backfill_dry_run_conflict_type_<TIMESTAMP>.json') as f:
    data = json.load(f)
print('conflict_type_breakdown:', json.dumps(data.get('conflict_type_breakdown', {}), indent=2))
"
```

**예상 결과:**
```json
{
  "position_delta_partial": 71,
  "position_delta_filled": 4
}
```
(기존 로그 기준: `position_delta_partial` 71건, `position_delta_filled` 4건)

#### 2.3.3. human summary의 `Conflict Type:` 라인

로그 파일에서 다음 패턴 검색:
```
Conflict Type: position_delta_partial
```

#### 2.3.4. human summary의 `types:` 집계 라인

로그 파일에서 다음 패턴 검색:
```
types: position_delta_filled=4, position_delta_partial=71
```

---

### 2.4. 예상 출력 예시

#### Human summary (stdout)

```
=== ODNO Expired Orders Backfill Report ===
Date Range: 2026-05-28 ~ 2026-05-29
Mode: DRY-RUN

Order Summary:
  Total expired + ODNO: 92
  auto_fix_safe:        17  → FILLED(0), PARTIALLY_FILLED(0)
  truth_probe_conflict: 75
  manual:               0

Details:
  ...
  [truth_probe_conflict] a3616426-...
    Symbol: 004000, Side: buy, Qty: 36
    Verdict: position_delta_partial
    Reason: position_verdict=position_delta_partial
    Conflict Type: position_delta_partial    ← NEW!
    KIS: ODNO=0000035537 | ord_stat=02 | ccld=0/36
    → SKIP (conflict)
  ...

Summary:
  Would apply: 0 orders → FILLED
  Would apply: 0 orders → PARTIALLY_FILLED
  truth_probe_conflict: 75, delta range: -41~0
    types: position_delta_filled=4, position_delta_partial=71    ← NEW!
  Skipped (manual): 0 orders
```

#### JSON summary (stdout with `--json`)

```json
{
  "date_range": {
    "from": "2026-05-28",
    "to": "2026-05-29"
  },
  "dry_run": true,
  "total": 92,
  "auto_fix_safe": 17,
  "truth_probe_conflict": 75,
  "manual": 0,
  "applied": {
    "filled": 0,
    "partially_filled": 0
  },
  "conflict_type_breakdown": {           ← NEW!
    "position_delta_partial": 71,
    "position_delta_filled": 4
  },
  "orders": [
    {
      "order_request_id": "a3616426-...",
      "symbol": "004000",
      "side": "buy",
      "requested_qty": "36.00000000",
      "classification": "truth_probe_conflict",
      "target_status": null,
      "verdict": "position_delta_partial",
      "match_method": "direct_odno",
      "reason": "position_verdict=position_delta_partial",
      "conflict_type": "position_delta_partial",    ← NEW!
      "broker_native_order_id": "0000035537",
      "kis_ord_stat": "02",
      ...
    }
  ]
}
```

---

## 3. 로그 파일 저장 위치

| 출력 형식 | 경로 | 설명 |
|-----------|------|------|
| JSON (stdout) | `logs/backfill_dry_run_conflict_type_${TS}.json` | `--json` 옵션 stdout 리다이렉션 |
| Debug (stderr) | `logs/backfill_dry_run_conflict_type_${TS}.debug.log` | JSON 실행 시 stderr(logging) 저장 |
| Human-readable | `logs/backfill_dry_run_conflict_type_${TS}.log` | `2>&1 \| tee` |

**기준 디렉토리:** `/workspace/agent_trading/logs/` (스크립트 내 `LOGS_DIR` 상수와 동일)

**파일명 일치:** `$TS` 변수를 한 번 설정하여 모든 명령어에서 동일한 타임스탬프 사용

---

## 4. 완료 조건 답변

### Q1. 기존 로그에 `conflict_type`이 없었던 이유는 무엇인가?

**답변:** 기존 dry-run 로그(`backfill_container_dry_run_v4_20260531.log`)는 `conflict_type` 관련 기능이 **코드에 추가되기 전**에 실행되었기 때문입니다. 현재 [`scripts/backfill_expired_odno_orders.py`](../scripts/backfill_expired_odno_orders.py)에는 `_classify()`의 4-tuple 반환, record dict의 `conflict_type` 필드, human summary의 `Conflict Type:` 라인, JSON summary의 `conflict_type_breakdown`이 **모두 구현되어 있습니다**. 따라서 새로 실행하는 dry-run에는 정상적으로 출력될 것으로 예상됩니다.

### Q2. 새 dry-run 실행 명령어는 무엇인가?

**답변:**
```bash
# 1. 타임스탬프 고정 (JSON/LOG/DEBUG 파일명 일치)
TS=$(date +%Y%m%d_%H%M%S)

# 2. JSON 출력 저장 (stdout → .json, stderr → .debug.log)
docker exec agent_trading-app-1 python3 scripts/backfill_expired_odno_orders.py \
  --dry-run --from-date 2026-05-28 --to-date 2026-05-29 --json \
  > logs/backfill_dry_run_conflict_type_${TS}.json \
  2>logs/backfill_dry_run_conflict_type_${TS}.debug.log

# 3. Human-readable 출력 저장 (stdout + stderr → .log)
docker exec agent_trading-app-1 python3 scripts/backfill_expired_odno_orders.py \
  --dry-run --from-date 2026-05-28 --to-date 2026-05-29 \
  2>&1 | tee logs/backfill_dry_run_conflict_type_${TS}.log
```

### Q3. 새 로그는 어디에 저장할 것인가?

**답변:** `/workspace/agent_trading/logs/` 디렉토리. 파일명 패턴:
- JSON: `backfill_dry_run_conflict_type_YYYYMMDD_HHMMSS.json`
- Human: `backfill_dry_run_conflict_type_YYYYMMDD_HHMMSS.log`

### Q4. 검증 항목은 무엇인가?

**답변:** 4가지 검증 포인트:
1. 각 conflict order의 JSON record에 `"conflict_type"` 필드 존재 (75건 모두)
2. JSON summary에 `"conflict_type_breakdown"` 객체 존재 (예: `{"position_delta_partial": 71, "position_delta_filled": 4}`)
3. human summary에 `"Conflict Type:"` 라인 출력 (각 conflict order detail에)
4. human summary에 `"types:"` 집계 라인 출력 (summary 섹션에)

---

## 5. Mermaid: 검증 워크플로우

```mermaid
flowchart TD
    A[시작] --> B[Docker 컨테이너 확인<br/>docker ps | grep agent_trading-app-1]
    B --> C{컨테이너 실행 중?}
    C -->|Yes| D[Dry-run 실행<br/>--json + --dry-run]
    C -->|No| E[Docker Compose로 컨테이너 시작]
    E --> D
    
    D --> F[JSON 파일 저장<br/>logs/backfill_dry_run_conflict_type_*.json]
    D --> G[Human 로그 저장<br/>logs/backfill_dry_run_conflict_type_*.log]
    
    F --> H[검증 1: 각 record에 conflict_type 필드 확인]
    F --> I[검증 2: JSON summary에 conflict_type_breakdown 확인]
    G --> J[검증 3: human summary에 Conflict Type: 라인 확인]
    G --> K[검증 4: human summary에 types: 집계 라인 확인]
    
    H --> L{모든 검증 통과?}
    I --> L
    J --> L
    K --> L
    
    L -->|Yes| M[✅ 검증 완료]
    L -->|No| N[❌ 버그 리포트 작성]
```

---

## 6. 파일 수정 사항

**이 단계에서는 파일 수정이 없음.** 기존 코드는 이미 `conflict_type` 관련 기능이 모두 구현되어 있으므로, dry-run 실행과 출력 검증만 수행하면 됨.

---

*Plan version: 1.0*
*Generated: 2026-05-31 17:33 KST*
