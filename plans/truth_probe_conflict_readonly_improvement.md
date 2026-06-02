# Phase: truth_probe_conflict Read-Only Observability 개선

## 1. 현황 분석

### 현재 truth_probe_conflict 상태

| 항목 | 상태 | 상세 |
|------|------|------|
| `TruthProbeReason` enum | ✅ 존재 | `order_sync_service.py`: 7개 subtype |
| `verify_order_truth.py` | ✅ 존재 | CLI 진단 스크립트 |
| `backfill_expired_odno_orders.py` | ✅ 존재 | 3분류(auto_fix_safe/truth_probe_conflict/manual) |
| conflict 유형 구조화 | ❌ 없음 | reason이 자유문자열로만 출력됨 |

### 문제점

1. `_classify()` 함수가 `reason`을 자유문자열로만 반환 → 유형별 집계/필터링 불가
2. "75건 conflict"가 있지만, 운영자가 "QTY_MISMATCH가 몇 건인지"를 알 수 없음
3. JSON 출력에도 `conflict_type` 구조화 필드가 없어 기계적 분석이 어려움

---

## 2. 선택한 read-only 개선안

### 핵심 아이디어

**`backfill_expired_odno_orders.py`의 `_classify()` 함수에 `conflict_type` 구조화 필드 추가**

- ✅ **변경 범위 최소화** — 1개 파일만 수정
- ✅ **Pure read-only** — DB 쓰기/API 변경 없음
- ✅ **기존 출력 호환** — JSON에 새 필드만 추가, 기존 필드 제거 없음
- ✅ **즉시 효과** — 운영자가 conflict 유형을 한눈에 파악 가능

### 추가할 `conflict_type` 종류

`_classify()` 함수 내 5가지 conflict 조건 각각에 대응:

| conflict_type | 조건 (backfill_expired_odno_orders.py 기준) | 설명 |
|---|---|---|
| `position_delta_filled` | `position_verdict == position_delta_filled` + KIS cross-check 실패 | position snapshot에서 FILLED로 보이나 불일치 |
| `position_delta_partial` | `position_verdict == position_delta_partial` | position snapshot에서 PARTIAL |
| `paper_truth_missing` | `match_verdict == paper_truth_missing` | VTTC0081R 데이터 부족 |
| `ord_stat_conflict` | `kis_ord_stat` not in fill codes but `ccld_qty > 0` | ord_stat 비체결코드인데 체결수량 존재 |
| `qty_mismatch` | `verdict==filled` and `ccld_qty != req_qty` | KIS 체결수량 ≠ DB 요청수량 |
| `position_delta_no_verdict` | `position_delta != 0` but `position_verdict` 없음 | delta는 있으나 판정 없음 |

---

## 3. 수정할 파일 (1개)

### [`scripts/backfill_expired_odno_orders.py`](scripts/backfill_expired_odno_orders.py)

#### 3a. `_classify()` 함수

**변경 전 (반환 타입):**
```python
def _classify(result, requested_quantity) -> tuple[str, str | None, str | None]:
    # (classification, target_status, reason)
```

**변경 후 (반환 타입):**
```python
def _classify(result, requested_quantity) -> tuple[str, str | None, str | None, str | None]:
    # (classification, target_status, reason, conflict_type)
```

각 conflict 조건 블록에 `conflict_type` 할당:
- **2a** (position_delta_filled) → `conflict_type = "position_delta_filled"`
- **2a** (position_delta_partial) → `conflict_type = "position_delta_partial"`
- **2b** (paper_truth_missing) → `conflict_type = "paper_truth_missing"`
- **2c** (ord_stat_conflict) → `conflict_type = "ord_stat_conflict"`
- **2d** (qty mismatch) → `conflict_type = "qty_mismatch"`
- **2e** (position_delta no verdict) → `conflict_type = "position_delta_no_verdict"`
- 조건에 맞는 게 없으면 → `conflict_type = None`

#### 3b. call site (`main()` 함수)

`classification, target_status, reason` → `classification, target_status, reason, conflict_type`
`_classify()` 4번째 반환값 처리 및 `orders_output`에 `conflict_type` 필드 포함

#### 3c. `_print_human_summary()`

conflict 항목 출력 시 `Conflict Type:` 라인 추가:
```
  [truth_probe_conflict] 0000031736
    Conflict Type: position_delta_filled
    Reason: position_verdict=position_delta_filled (delta=50)
```

#### 3d. conflict 요약 섹션

type별 집계 추가:
```
  truth_probe_conflict: 75
    qty_mismatch:             30
    position_delta_filled:    25
    paper_truth_missing:      20
```

#### 3e. JSON 출력

각 order 항목에 `conflict_type` 필드 포함.

---

## 4. 하위 Task 분할

| # | Task | 모드 | 내용 |
|---|------|------|------|
| 1 | 개선안 선택 | architect | ✅ 완료 |
| 2 | 코드 수정 | code | `backfill_expired_odno_orders.py` — 5개 변경 포인트 |
| 3 | 테스트 실행 | code | 관련 테스트 실행 |
| 4 | 실제 conflict 사례 검증 | code | 출력 포맷 확인 |
| 5 | 최종 판정 | orchestrator | 결과 보고 |

---

## 5. 질문에 대한 답변

### Q1. 지금 conflict 해석에서 가장 부족한 정보는?
conflict 유형이 구조화되어 있지 않아, 75건의 conflict를 유형별로 집계/필터링할 방법이 없음.

### Q2. 가장 저위험한 read-only 개선은?
`backfill_expired_odno_orders.py`의 `_classify()` 반환값에 `conflict_type` 필드 추가. 1개 파일, CLI 출력 포맷만 변경.

### Q3. 기존 운영 흐름을 깨지 않고 붙일 수 있는가?
가능. 기존 `reason` 문자열은 그대로 유지하고 새 필드만 추가. JSON 출력 호환성 유지.

### Q4. 실제 conflict 사례를 더 명확히 설명할 수 있는가?
가능. `"position_verdict=position_delta_filled (delta=50)"` → `"Conflict Type: position_delta_filled, Reason: position_verdict=..."`

### Q5. 수동 검토 비용이 줄어드는가?
줄어든다. 유형별 분포를 한눈에 파악 가능 (`qty_mismatch: 30건, position_delta_filled: 25건`). 유형별 우선순위 지정 가능.
