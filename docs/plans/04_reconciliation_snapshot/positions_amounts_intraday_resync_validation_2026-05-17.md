# Position Snapshot Intraday 재수집 검증 — `purchase_amount` / `evaluation_amount`

**작성일**: 2026-05-17  
**검증 담당**: Phase O Validation  
**최종 분류**: ✅ **A. 완전 성공**

---

## 1. 왜 기존 값이 null이었는가

Phase N에서 [`snapshot.py`](../src/agent_trading/brokers/koreainvestment/snapshot.py:138)의
`KISSyncSnapshotProvider.fetch_snapshot()`에 `purchase_amount` / `evaluation_amount` 매핑 코드가 추가되고,
[`position_snapshots.py`](../src/agent_trading/repositories/postgres/position_snapshots.py:28-35)의
INSERT 쿼리에 해당 컬럼이 포함되었지만, **두 가지 이유로 DB 값이 모두 `null`이었다**:

1. **Phase N 이전에 수집된 데이터**: 기존 DB position 스냅샷은 필드 추가 이전에 저장되어
   당연히 `null`이었다.
2. **최근 snapshot-sync가 after-hours cash-only mode로 동작**: `snapshot-sync` 서비스가
   `after_hours=True`로 실행되어 positions fetch를 skip하고 cash balance만 수집했다.
   (`snapshot.py` 94-95행: `if after_hours: ... skipping positions fetch`)

이로 인해 새 필드가 추가된 이후에도 포지션이 재수집되지 않아 모든 row가 `null` 상태였다.

---

## 2. Intraday 재수집 실행 방법

### 사용 명령어

```bash
cd /workspace/agent_trading
python3 -c "
import subprocess, sys
from dotenv import load_dotenv
load_dotenv()
sys.exit(subprocess.run([sys.executable, 'scripts/run_snapshot_sync_loop.py', '--max-cycles', '1']).returncode)
"
```

### 파라미터 설명

| 파라미터 | 값 | 의미 |
|----------|-----|------|
| `--max-cycles` | `1` | 1회만 실행 후 종료 (무한 루프 방지) |
| `--after-hours` | 생략 (기본값 `False`) | Intraday mode: positions fetch 포함 |
| `--broker` | 생략 (기본값 `koreainvestment`) | KIS broker 사용 |

### 중요: `.env` 로딩

`scripts/run_snapshot_sync_loop.py`는 `load_dotenv()`를 호출하지 않으므로,
실행 전에 `python-dotenv`를 통해 `.env` 파일을 로드해야 한다. 위 명령어는
`load_dotenv()`를 호출한 후 subprocess로 스크립트를 실행하는 방식이다.

---

## 3. Raw payload에 값이 있었는가

**네, KIS API 응답의 `output` 배열에 `pchs_amt`와 `evlu_amt` 필드가 존재했다.**

임시 INFO 로그로 확인한 raw position 데이터:

```
TEMP_POS[0]: pdno=000880 pchs_amt='1454000' evlu_amt='1414000' ...
TEMP_POS[1]: pdno=005930 pchs_amt='2670000' evlu_amt='2705000' ...
```

| 종목코드 | 종목명 | `pchs_amt` (매입금액) | `evlu_amt` (평가금액) |
|----------|--------|-----------------------|-----------------------|
| `000880` | 한화 | 1,454,000 원 | 1,414,000 원 |
| `005930` | 삼성전자 | 2,670,000 원 | 2,705,000 원 |

KIS `inquire-balance` API 응답에서 `pchs_amt`와 `evlu_amt`는 항상 존재하는 표준 필드이므로,
paper 환경에서도 정상적으로 반환된다.

---

## 4. DB 저장 결과

```sql
SELECT position_snapshot_id, account_id, quantity, purchase_amount, evaluation_amount, snapshot_at
FROM trading.position_snapshots
ORDER BY snapshot_at DESC
LIMIT 4;
```

| snapshot_at (UTC) | 종목 | quantity | purchase_amount | evaluation_amount |
|-------------------|------|----------|----------------|-------------------|
| 2026-05-17 03:01:43 | 005930 | 10 | **2,670,000** | **2,705,000** |
| 2026-05-17 03:01:43 | 000880 | 10 | **1,454,000** | **1,414,000** |
| 2026-05-16 08:48:24 | 005930 | 10 | `null` | `null` |
| 2026-05-16 08:48:24 | 000880 | 10 | `null` | `null` |

- ✅ Intraday 수집: `purchase_amount` / `evaluation_amount` **정상 저장**
- ❌ After-hours 수집: `purchase_amount` / `evaluation_amount` **null** (positions fetch 안 함)

---

## 5. API 응답 결과

```bash
curl -s -H "Authorization: Bearer dev-token-123" \
  "http://localhost:8000/positions?account_id=a44a02d1-7f32-5a62-99f7-235abeb58284" \
  | python3 -m json.tool
```

최신 snapshot 응답 (2026-05-17 03:01:43 UTC):

```json
{
    "position_snapshot_id": "4418c04f-3e44-4462-aa69-d9ad24060bc3",
    "account_id": "a44a02d1-7f32-5a62-99f7-235abeb58284",
    "symbol": "005930",
    "quantity": 10.0,
    "average_price": 267000.0,
    "market_price": 270500.0,
    "unrealized_pnl": 35000.0,
    "purchase_amount": 2670000.0,
    "evaluation_amount": 2705000.0,
    "source_of_truth": "broker",
    "snapshot_at": "2026-05-17T03:01:43.771009Z"
},
{
    "position_snapshot_id": "9ae359b6-1784-4e4d-a666-16a03b90e013",
    "account_id": "a44a02d1-7f32-5a62-99f7-235abeb58284",
    "symbol": "000880",
    "quantity": 10.0,
    "average_price": 145400.0,
    "market_price": 141400.0,
    "unrealized_pnl": -40000.0,
    "purchase_amount": 1454000.0,
    "evaluation_amount": 1414000.0,
    "source_of_truth": "broker",
    "snapshot_at": "2026-05-17T03:01:43.771009Z"
}
```

이전 after-hours 데이터 (2026-05-16 08:48:24 UTC):

```json
{
    "symbol": "005930",
    "purchase_amount": null,
    "evaluation_amount": null,
    ...
}
```

- ✅ **최신 intraday 수집 데이터**: `purchase_amount` / `evaluation_amount` **정상 반환**
- ❌ **이전 after-hours 데이터**: `null`

---

## 6. 최종 분류

### ✅ **A. 완전 성공**

| 검증 항목 | 상태 |
|-----------|------|
| Raw KIS 응답에 `pchs_amt` / `evlu_amt` 존재 | ✅ (1,454,000 / 1,414,000 등) |
| DB `position_snapshots`에 값 저장 | ✅ (두 row 모두 채워짐) |
| API `GET /positions` 응답에 값 반영 | ✅ (purchase_amount, evaluation_amount 필드 정상 출력) |
| Intraday mode (`after_hours=False`) 확인 | ✅ ("After-hours mode — skipping positions fetch" 메시지 없음) |
| Positions fetch 수행 확인 | ✅ (HTTP 200, 2개 position 수집) |

**Phase N의 코드 수정이 완전히 올바르게 동작함을 검증했다.**
코드 저장 경로(`snapshot.py` → `position_snapshots.py` → API schema) 전 구간이
정상적으로 연결되어 있다.

---

## 7. 남은 Follow-up

| # | 항목 | 우선순위 | 설명 |
|---|------|----------|------|
| 1 | **Cash balance rate limit 문제** | 중간 | paper 환경 REST RPS=1로 인해 cash balance fetch가 rate limit에 걸림. 하나의 sync cycle에서 `get_positions()` + `get_cash_balance()`를 모두 호출하면 budget 초과. `KIS_PAPER_REST_RPS`를 2로 올리거나 budget 분배 로직 조정 필요. |
| 2 | **과거 스냅샷 null 데이터** | 낮음 | Phase N 이전 데이터는 여전히 `null`. 백필(backfill)이 필요하면 별도 마이그레이션으로 처리 가능. 현재는 최신 데이터만 사용하므로 문제되지 않음. |
| 3 | **스크립트에 `load_dotenv()` 부재** | 낮음 | `run_snapshot_sync_loop.py`가 `load_dotenv()`를 호출하지 않아 별도의 래퍼가 필요. Docker 서비스로 실행 시 환경변수가 컨테이너에 직접 주입되므로 실제 운영 환경에서는 문제되지 않음. |
